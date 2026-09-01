"""Tests for the deterministic same-origin UI fixture host."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.client import HTTPConnection
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.request import Request, urlopen
from uuid import UUID

import pytest
from scripts import ui_smoke
from scripts.ui_fixture_server import LOOPBACK_HOST, SCENARIO_COOKIE, UIFixtureServer
from scripts.ui_fixture_sources import INTERNAL_SOURCES, FixtureSourceStoreClient
from scripts.ui_fixtures import (
    AGENT_RUN_ID,
    DATASET_ID,
    FIXTURE_IDENTITY,
    FIXTURE_REVISION,
    JOB_ID,
    PRODUCT_SCHEMA,
    PROPERTY_ID,
    RELEASE_ID,
    REPORT_SCHEMA,
    REVIEW_RELEASE_ID,
    RUN_ID,
    SCENARIOS,
    SOURCE_ID,
    fixture_response,
)

from propertyscope_data_platform.api import release_detail_contract
from propertyscope_data_platform.domain import PublicationReceiptResult
from propertyscope_data_platform.release_builders import (
    DataProductCatalogueEntry,
    ReleaseDetailContract,
    ReleaseManifestV1,
)
from shared_contracts import (
    AgentRun,
    AgentRunDetail,
    AgentRunEventPage,
    AgentRunPage,
    TypedHealthProjection,
)
from shared_contracts.operations import AgentRunEvidenceDetail

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_ui_audit_artifact_root_is_repository_relative() -> None:
    config = json.loads(
        (REPOSITORY_ROOT / "docs" / "ui" / "feature-1-audit-config.json").read_text(
            encoding="utf-8"
        )
    )
    artifact_root = config["baseline"]["artifactRoot"]

    assert artifact_root == ".propertyscope-runtime/ui-baseline"
    assert not PurePosixPath(artifact_root).is_absolute()
    assert not PureWindowsPath(artifact_root).is_absolute()


@pytest.fixture
def fixture_origin() -> Iterator[str]:
    server = UIFixtureServer(0, "populated")
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield f"http://{LOOPBACK_HOST}:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _json(url: str, *, cookie: str | None = None) -> tuple[dict[str, object], object]:
    headers = {"Cookie": cookie} if cookie else {}
    with urlopen(Request(url, headers=headers), timeout=2) as response:
        return json.load(response), response.headers


def test_same_origin_host_serves_shared_feature_and_structured_unknown_api(
    fixture_origin: str,
) -> None:
    with urlopen(f"{fixture_origin}/", timeout=2) as response:
        assert b"PropertyScope NSW" in response.read()
    with urlopen(
        f"{fixture_origin}/features/data-platform/",
        timeout=2,
    ) as response:
        assert b"Data overview" in response.read()
    with urlopen(
        f"{fixture_origin}/features/data-platform/integration/shell.js",
        timeout=2,
    ) as response:
        assert b"createFeature1ShellAdapter" in response.read()
    with urlopen(
        f"{fixture_origin}/features/data-platform/browser/index.js",
        timeout=2,
    ) as response:
        assert b"append, el" in response.read()
    with urlopen(f"{fixture_origin}/design-system/gallery.html", timeout=2) as response:
        gallery = response.read()
        assert b"Design foundation" in gallery
        assert b"ps-density--comfortable" in gallery
    with urlopen(f"{fixture_origin}/fragments/research-areas.html", timeout=2) as response:
        fragment = response.read()
        assert response.headers.get_content_type() == "text/html"
        assert fragment.count(b"data-feature-id=") == 5
        assert fragment.count(b'data-feature-state="planned"') == 3
    with urlopen(f"{fixture_origin}/vendor/htmx-2.0.10.min.js", timeout=2) as response:
        htmx = response.read()
        assert response.headers.get_content_type() in {"text/javascript", "application/javascript"}
        assert b'version:"2.0.10"' in htmx
    with urlopen(f"{fixture_origin}/operations/ai-mode/assets/app.js", timeout=2) as response:
        assert b'const API_ROOT = "/api/v1"' in response.read()
    with urlopen(f"{fixture_origin}/healthz", timeout=2) as response:
        assert response.headers.get_content_type() == "text/plain"
        assert response.read() == b"ok\n"
    ready, _headers = _json(f"{fixture_origin}/__ui-fixture__/ready")
    assert ready == {
        "scenario": "populated",
        "status": "ready",
        "identity": FIXTURE_IDENTITY,
        "revision": FIXTURE_REVISION,
    }
    feature_ready, _headers = _json(f"{fixture_origin}/health/ready")
    projection = TypedHealthProjection.model_validate(feature_ready)
    assert projection.http_status == 200
    assert projection.checks["database"].required is True

    connection = HTTPConnection(LOOPBACK_HOST, int(fixture_origin.rsplit(":", 1)[1]))
    connection.request("GET", "/api/data-platform/v1/not-registered")
    response = connection.getresponse()
    problem = json.loads(response.read())
    assert response.status == 404
    assert response.getheader("Content-Type") == "application/problem+json; charset=utf-8"
    assert problem["code"] == "fixture_route_not_found"
    connection.close()

    connection = HTTPConnection(LOOPBACK_HOST, int(fixture_origin.rsplit(":", 1)[1]))
    connection.request("DELETE", f"/api/data-platform/v1/sources/{SOURCE_ID}")
    response = connection.getresponse()
    assert response.status == 204
    assert response.read() == b""
    connection.close()


def test_query_scenario_sets_session_cookie_used_by_api(fixture_origin: str) -> None:
    request = Request(f"{fixture_origin}/?scenario=empty")
    with urlopen(request, timeout=2) as response:
        cookie = response.headers["Set-Cookie"]
    assert cookie.startswith(f"{SCENARIO_COOKIE}=empty")

    body, _headers = _json(
        f"{fixture_origin}/api/data-platform/v1/properties/search?q=fixture",
        cookie=cookie,
    )

    assert body["items"] == []
    assert body["count"] == 0


def test_source_fragment_fixture_store_has_isolated_real_crud_and_concurrency() -> None:
    first = FixtureSourceStoreClient(session_key="browser-a", scenario="populated")
    second = FixtureSourceStoreClient(session_key="browser-b", scenario="populated")
    source = {
        "name": "Isolated HTMX source",
        "publisher": "PropertyScope QA",
        "source_url": "https://example.test/source",
        "adapter_key": "fixture.adapter",
        "cadence": "weekly",
        "licence_id": "cc-by-4.0",
        "licence_url": "https://creativecommons.org/licenses/by/4.0/",
        "redistribution_policy": "attribution",
        "target_features": ["feature-1"],
        "status": "draft",
        "notes": "Ephemeral fixture data.",
    }

    created = first.request("POST", INTERNAL_SOURCES, json=source).json()["source"]
    assert created["version"] == 1
    assert first.request("GET", INTERNAL_SOURCES).json()["total"] == 2
    assert second.request("GET", INTERNAL_SOURCES).json()["total"] == 1

    conflict = first.request(
        "PUT", f"{INTERNAL_SOURCES}/{created['id']}", json={**source, "version": 99}
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "version_conflict"

    updated = first.request(
        "PUT",
        f"{INTERNAL_SOURCES}/{created['id']}",
        json={**source, "name": "Updated HTMX source", "version": 1},
    ).json()["source"]
    assert updated["name"] == "Updated HTMX source"
    assert updated["version"] == 2

    deleted = first.request("DELETE", f"{INTERNAL_SOURCES}/{created['id']}")
    assert deleted.status_code == 204
    assert first.request("GET", INTERNAL_SOURCES).json()["total"] == 1


def test_fixture_payload_is_stable_and_uses_contract_envelopes() -> None:
    first = fixture_response("GET", "/api/data-platform/v1/jobs", "limit=100", "populated")
    second = fixture_response("GET", "/api/data-platform/v1/jobs", "limit=100", "populated")

    assert first == second
    assert set(first.body) == {"items", "count", "limit", "offset", "next_offset"}
    assert {
        "id",
        "source_definition_id",
        "name",
        "profile_key",
        "dataset_id",
        "target_feature",
        "status",
        "version",
    } <= set(first.body["items"][0])


def test_data_product_routes_match_the_direct_production_catalogue_shape(
    fixture_origin: str,
) -> None:
    listing, _headers = _json(f"{fixture_origin}/api/data-platform/v1/data-products")
    product, _headers = _json(f"{fixture_origin}/api/data-platform/v1/data-products/{DATASET_ID}")

    assert product == listing["items"][0]
    assert "data_product" not in product
    assert {
        "dataset_id",
        "display_name",
        "target_feature",
        "job_profile",
        "import_profile",
        "builder_key",
        "builder_version",
        "product_schema_version",
        "ordering_rule",
        "supported_scope_profiles",
        "max_rows",
        "max_bytes",
        "redistribution_decision",
        "download_permitted",
        "capability_state",
        "latest_accepted_release",
        "known_limitations",
    } <= set(product)
    assert product["product_schema_version"] == PRODUCT_SCHEMA
    DataProductCatalogueEntry.model_validate(product)


@pytest.mark.parametrize("status", ("accepted", "candidate", "awaiting_review"))
def test_dataset_release_status_filter_returns_only_exact_matches(status: str) -> None:
    response = fixture_response(
        "GET", "/api/data-platform/v1/dataset-releases", f"status={status}", "populated"
    )

    assert response.body["count"] == 1
    assert [item["status"] for item in response.body["items"]] == [status]


def test_required_scenarios_have_distinct_deterministic_behaviour() -> None:
    assert SCENARIOS == (
        "populated",
        "empty",
        "slow",
        "error",
        "partial",
        "long-content",
        "large",
        "validation-error",
    )
    route = "/api/data-platform/v1/properties/search"
    assert fixture_response("GET", route, "", "empty").body["items"] == []
    assert fixture_response("GET", route, "", "slow").delay_seconds > 0
    assert fixture_response("GET", route, "", "error").status == 503
    large = fixture_response("GET", route, "", "large").body
    assert large["count"] == 25
    assert large["total"] == 80
    assert large["next_offset"] == 25
    assert (
        "<script>"
        in fixture_response("GET", route, "", "long-content").body["items"][0]["address_display"]
    )
    validation = fixture_response(
        "POST",
        "/api/data-platform/v1/jobs",
        "",
        "validation-error",
    )
    assert validation.status == 422
    assert validation.content_type == "application/problem+json"


def test_partial_scenario_preserves_primary_content_and_fails_optional_calls() -> None:
    detail = fixture_response(
        "GET",
        f"/api/data-platform/v1/properties/{PROPERTY_ID}",
        "",
        "partial",
    )
    map_context = fixture_response(
        "GET",
        f"/api/data-platform/v1/properties/{PROPERTY_ID}/map-context",
        "",
        "partial",
    )
    overview = fixture_response("GET", "/api/data-platform/v1/overview", "", "partial")
    overview_runs = fixture_response(
        "GET", "/api/data-platform/v1/ingestion-runs", "limit=25", "partial"
    )
    sources = fixture_response("GET", "/api/data-platform/v1/sources", "", "partial")

    assert detail.status == 200
    assert "property" in detail.body
    assert map_context.status == 503
    assert overview.status == 503
    assert overview_runs.status == 503
    assert sources.status == 200
    assert sources.body["items"]


@pytest.mark.parametrize(
    ("route", "code"),
    (
        ("properties/00000000-0000-4000-8000-000000000099", "property_not_found"),
        ("sources/00000000-0000-4000-8000-000000000099", "source_not_found"),
        ("jobs/00000000-0000-4000-8000-000000000099", "job_not_found"),
        ("ingestion-runs/00000000-0000-4000-8000-000000000099", "ingestion_run_not_found"),
        ("dataset-releases/00000000-0000-4000-8000-000000000099", "release_not_found"),
        ("data-products/not-a-product", "data_product_not_found"),
        ("agent-runs/00000000-0000-4000-8000-000000000099", "agent_run_not_found"),
    ),
)
def test_detail_routes_do_not_fall_back_to_the_first_record(route: str, code: str) -> None:
    response = fixture_response("GET", f"/api/data-platform/v1/{route}", "", "populated")

    assert response.status == 404
    assert response.content_type == "application/problem+json"
    assert response.body["code"] == code


def test_shared_health_evidence_and_ai_operations_projections_are_contract_valid() -> None:
    health = fixture_response("GET", "/api/shared-health/data-platform", "", "populated")
    ai_health = fixture_response("GET", "/api/shared-health/ai-mode", "", "populated")
    releases = fixture_response(
        "GET", "/api/data-platform/v1/dataset-releases", "status=accepted", "populated"
    )
    page = fixture_response("GET", "/api/v1/agent-runs", "", "populated")
    detail = fixture_response(
        "GET", f"/api/v1/operations/agent-runs/{AGENT_RUN_ID}", "", "populated"
    )
    events = fixture_response("GET", f"/api/v1/agent-runs/{AGENT_RUN_ID}/events", "", "populated")
    feature_detail = fixture_response(
        "GET", f"/api/data-platform/v1/agent-runs/{AGENT_RUN_ID}", "", "populated"
    )
    assistant = fixture_response(
        "GET", "/api/data-platform/v1/assistant/capabilities", "", "populated"
    )

    feature_projection = TypedHealthProjection.model_validate(health.body)
    ai_projection = TypedHealthProjection.model_validate(ai_health.body)
    assert feature_projection.checks["database"].required is True
    assert ai_projection.checks["llm_provider"].required is False
    assert ai_health.body["checks"]["llm_provider"]["status"] == "healthy"
    assert releases.body["count"] == 1
    assert [item["status"] for item in releases.body["items"]] == ["accepted"]
    assert releases.body["items"][0]["target_feature"] == "feature-1"
    AgentRunPage.model_validate(page.body)
    AgentRunEvidenceDetail.model_validate(detail.body)
    AgentRunEventPage.model_validate(events.body)
    AgentRunDetail.model_validate(feature_detail.body)
    assert assistant.status == 200
    assert assistant.body["application"]["name"] == "PropertyScope NSW"
    assert assistant.body["features"][0]["status"] == "available"


def test_release_ai_creation_and_operator_mutation_statuses_match_production() -> None:
    created_agent = fixture_response(
        "POST",
        f"/api/data-platform/v1/dataset-releases/{RELEASE_ID}/agent-runs",
        "",
        "populated",
    )
    source_created = fixture_response("POST", "/api/data-platform/v1/sources", "", "populated")
    job_created = fixture_response("POST", "/api/data-platform/v1/jobs", "", "populated")
    source_deleted = fixture_response(
        "DELETE", f"/api/data-platform/v1/sources/{SOURCE_ID}", "", "populated"
    )
    job_deleted = fixture_response(
        "DELETE", f"/api/data-platform/v1/jobs/{JOB_ID}", "", "populated"
    )
    retry = fixture_response(
        "POST", f"/api/data-platform/v1/ingestion-runs/{RUN_ID}/retry", "", "populated"
    )
    reprocess = fixture_response(
        "POST",
        f"/api/data-platform/v1/ingestion-runs/{RUN_ID}/reprocess-cached",
        "",
        "populated",
    )

    assert created_agent.status == 201
    AgentRun.model_validate(created_agent.body)
    assert source_created.status == job_created.status == 201
    assert set(source_created.body) == {"source"}
    assert set(job_created.body) == {"job"}
    assert source_deleted.status == job_deleted.status == 204
    assert source_deleted.body == job_deleted.body == {}
    assert retry.status == reprocess.status == 201
    assert retry.body["created"] is reprocess.body["created"] is True


def test_release_update_and_publish_use_production_envelopes() -> None:
    update = fixture_response(
        "PUT", f"/api/data-platform/v1/dataset-releases/{RELEASE_ID}", "", "populated"
    )
    publication = fixture_response(
        "POST",
        f"/api/data-platform/v1/dataset-releases/{REVIEW_RELEASE_ID}/publish",
        "",
        "populated",
    )

    assert update.status == 200
    assert set(update.body) == {"release"}
    assert update.body["release"]["id"] == RELEASE_ID
    assert publication.status == 200
    assert set(publication.body) == {
        "release",
        "receipt",
        "publication_status",
        "replayed",
    }
    assert publication.body["release"]["status"] == "accepted"
    assert publication.body["publication_status"] == "completed"
    assert publication.body["replayed"] is False
    PublicationReceiptResult.model_validate(publication.body["receipt"])
    release_detail_contract(publication.body["release"])


def test_capabilities_plan_manifest_and_release_inspection_match_production_shapes() -> None:
    runtime = fixture_response("GET", "/api/data-platform/v1/runtime-capabilities", "", "populated")
    capabilities = fixture_response(
        "GET", f"/api/data-platform/v1/jobs/{JOB_ID}/capabilities", "", "populated"
    )
    plan = fixture_response("POST", f"/api/data-platform/v1/jobs/{JOB_ID}/plans", "", "populated")
    manifest = fixture_response(
        "GET", f"/api/data-platform/v1/dataset-releases/{RELEASE_ID}/manifest", "", "populated"
    )
    inspection = fixture_response(
        "GET", f"/api/data-platform/v1/dataset-releases/{RELEASE_ID}", "", "populated"
    )

    assert set(runtime.body) == {
        "implemented_live_profiles",
        "host_verified_profiles",
        "connected_live_profiles",
        "cached_live_profiles",
        "cached_source_years",
        "cached_source_weeks",
        "catalogued_profiles",
    }
    assert set(capabilities.body) == {
        "job_id",
        "profile_key",
        "refresh_strategy",
        "supported_modes",
        "registered",
    }
    assert set(plan.body) == {
        "valid",
        "job_id",
        "run_mode",
        "scope",
        "network_required",
        "source_cache_required",
        "tasks",
        "accepted_watermark_unchanged_until_publication",
    }
    assert [task["stage"] for task in plan.body["tasks"]] == [
        "discover",
        "acquire",
        "validate_artifact",
        "import",
        "normalise",
        "quality",
        "build_release",
    ]
    ReleaseManifestV1.model_validate(manifest.body)
    assert set(inspection.body) == {
        "release",
        "quality_results",
        "quality_summary",
        "receipts",
        "accepted_predecessor",
        "release_contract",
    }
    ReleaseDetailContract.model_validate(inspection.body["release_contract"])


def test_projection_values_match_report_preview_overview_and_uuid_contracts() -> None:
    report = fixture_response(
        "GET", f"/api/data-platform/v1/properties/{PROPERTY_ID}/report-section", "", "populated"
    )
    preview = fixture_response(
        "GET", f"/api/data-platform/v1/dataset-releases/{RELEASE_ID}/records", "", "populated"
    )
    overview = fixture_response("GET", "/api/data-platform/v1/overview", "", "populated")
    large = fixture_response("GET", "/api/data-platform/v1/jobs", "", "large")
    generated_job = large.body["items"][-1]
    generated_detail = fixture_response(
        "GET", f"/api/data-platform/v1/jobs/{generated_job['id']}", "", "large"
    )
    referenced_source = fixture_response(
        "GET",
        f"/api/data-platform/v1/sources/{generated_job['source_definition_id']}",
        "",
        "large",
    )

    assert report.body["schema_version"] == REPORT_SCHEMA
    assert {"state", "postcode", "longitude", "latitude", "geometry"} <= set(
        report.body["identity"]
    )
    assert preview.body["profile"] == "property-fixture"
    assert set(preview.body["columns"]) == set(preview.body["items"][0])
    assert set(overview.body) == {
        "runs",
        "releases",
        "failed_quality_checks",
        "properties",
    }
    assert all(UUID(item["id"]) for item in large.body["items"])
    assert UUID(SOURCE_ID) and UUID(JOB_ID) and UUID(RUN_ID) and UUID(RELEASE_ID)
    assert generated_detail.status == 200
    assert referenced_source.status == 200


def test_host_header_and_traversal_are_rejected(fixture_origin: str) -> None:
    port = int(fixture_origin.rsplit(":", 1)[1])
    connection = HTTPConnection(LOOPBACK_HOST, port)
    connection.request("GET", "/", headers={"Host": "example.test"})
    response = connection.getresponse()
    assert response.status == 403
    response.read()
    connection.close()

    connection = HTTPConnection(LOOPBACK_HOST, port)
    connection.request("GET", "/features/data-platform/%2e%2e/%2e%2e/README.md")
    response = connection.getresponse()
    assert response.status == 404
    response.read()
    connection.close()


def test_smoke_cleans_up_owned_child_when_readiness_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailedChild:
        terminated = False

        def poll(self) -> int:
            return 1

        def terminate(self) -> None:
            self.terminated = True

        def wait(self, *, timeout: int) -> int:
            assert timeout == 5
            return 1

    child = FailedChild()
    monkeypatch.setattr(ui_smoke, "_ready", lambda _base_url: False)
    monkeypatch.setattr(ui_smoke.subprocess, "Popen", lambda *_args, **_kwargs: child)

    with (
        pytest.raises(RuntimeError, match="readiness check"),
        ui_smoke.fixture_runtime(5319, "populated"),
    ):
        pass

    assert child.terminated is True
