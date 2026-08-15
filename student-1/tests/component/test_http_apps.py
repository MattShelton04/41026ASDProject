from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import httpx
import yaml

from propertyscope_data_platform.app import create_app as create_backend_app
from propertyscope_data_platform.clients import (
    AiModeClient,
    ConsumerEndpoint,
    ConsumerImportClient,
    DataStoreClient,
)


def test_backend_proxies_property_search_and_preserves_expected_negative() -> None:
    def database(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-PropertyScope-Internal-Token"] == "secret"
        if request.url.path == "/health/ready":
            return httpx.Response(200, json={"status": "healthy"})
        assert request.url.params["state"] == "VIC"
        return httpx.Response(
            200,
            json={"items": [], "count": 0, "query": "10 Example Street", "supported": False},
        )

    store = DataStoreClient(
        "http://database", "secret", client=httpx.Client(transport=httpx.MockTransport(database))
    )
    app = create_backend_app(
        store_client=store,
        ai_mode_client=AiModeClient(
            "http://ai",
            client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503))),
        ),
    )
    response = app.test_client().get(
        "/api/data-platform/v1/properties/search?q=10%20Example%20Street&state=VIC"
    )
    assert response.status_code == 200
    assert response.get_json()["supported"] is False


def test_backend_proxies_bounded_release_record_preview() -> None:
    release_id = "60000000-0000-0000-0000-000000000004"

    def database(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/internal/data-platform/v1/releases/{release_id}/records"
        assert request.url.params["limit"] == "25"
        assert request.url.params["offset"] == "50"
        return httpx.Response(
            200,
            json={
                "release": {"id": release_id, "status": "candidate"},
                "profile": "schools-master",
                "columns": ["school_code", "school_name"],
                "items": [{"school_code": "1001", "school_name": "Example Public School"}],
                "count": 1,
                "total": 2210,
                "limit": 25,
                "offset": 50,
                "next_offset": 75,
            },
        )

    store = DataStoreClient(
        "http://database",
        "secret",
        client=httpx.Client(transport=httpx.MockTransport(database)),
    )
    app = create_backend_app(
        store_client=store,
        ai_mode_client=AiModeClient(
            "http://ai",
            client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503))),
        ),
    )

    response = app.test_client().get(
        f"/api/data-platform/v1/dataset-releases/{release_id}/records?limit=25&offset=50"
    )

    assert response.status_code == 200
    assert response.get_json()["total"] == 2210


def test_backend_protects_runner_and_publication() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(500, json={"code": "unexpected"}))
    app = create_backend_app(
        store_client=DataStoreClient(
            "http://database", "secret", client=httpx.Client(transport=transport)
        ),
        ai_mode_client=AiModeClient("http://ai", client=httpx.Client(transport=transport)),
    )
    client = app.test_client()
    assert client.post("/internal/data-platform/v1/worker/tasks/claim", json={}).status_code == 401
    response = client.post(
        "/api/data-platform/v1/dataset-releases/60000000-0000-0000-0000-000000000011/publish",
        json={"version": 1, "comment": "reviewed", "approved": False},
    )
    assert response.status_code == 422
    assert response.content_type == "application/problem+json"


def test_publication_records_consumer_receipt_before_pointer_transition() -> None:
    release_id = "60000000-0000-0000-0000-000000000011"
    digest = "a" * 64
    events: list[str] = []
    release = {
        "id": release_id,
        "dataset_id": "bocsar-crime",
        "target_feature": "feature-3",
        "schema_version": "crime-series.v1",
        "content_sha256": digest,
        "record_count": 3,
        "manifest_json": {"schema_version": "crime-series.v1"},
        "status": "awaiting_review",
        "version": 2,
    }

    def database(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"release": release, "receipts": []})
        if request.url.path.endswith("/receipts"):
            events.append("receipt")
            body = cast(dict[str, Any], json.loads(request.content))
            return httpx.Response(
                201,
                json={"receipt": {"id": "receipt-1", **body}, "created": True},
            )
        events.append("transition")
        return httpx.Response(200, json={"release": {**release, "status": "accepted"}})

    def consumer(_: httpx.Request) -> httpx.Response:
        events.append("consumer")
        return httpx.Response(
            200,
            json={
                "consumer_operation_id": "publish-release-11",
                "status": "accepted",
                "schema_version": "crime-series.v1",
                "content_sha256": digest,
                "rows_received": 3,
                "rows_accepted": 3,
                "rows_rejected": 0,
                "error": None,
            },
        )

    transport = httpx.MockTransport(database)
    app = create_backend_app(
        store_client=DataStoreClient(
            "http://database", "secret", client=httpx.Client(transport=transport)
        ),
        ai_mode_client=AiModeClient(
            "http://ai",
            client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503))),
        ),
        consumer_client=ConsumerImportClient(
            {"feature-3": ConsumerEndpoint("http://feature-3", "/api/imports")},
            client=httpx.Client(transport=httpx.MockTransport(consumer)),
        ),
    )
    response = app.test_client().post(
        f"/api/data-platform/v1/dataset-releases/{release_id}/publish",
        headers={"Idempotency-Key": "publish-release-11"},
        json={"version": 2, "comment": "Reviewed", "approved": True},
    )
    assert response.status_code == 200
    assert events == ["consumer", "receipt", "transition"]
    assert response.get_json()["receipt"]["id"] == "receipt-1"


def test_consumer_rejection_records_receipt_without_advancing_release() -> None:
    release_id = "60000000-0000-0000-0000-000000000012"
    digest = "b" * 64
    events: list[str] = []
    release = {
        "id": release_id,
        "dataset_id": "bocsar-crime",
        "target_feature": "feature-3",
        "schema_version": "crime-series.v1",
        "content_sha256": digest,
        "record_count": 3,
        "manifest_json": {},
        "status": "awaiting_review",
        "version": 1,
    }

    def database(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"release": release, "receipts": []})
        assert request.url.path.endswith("/receipts")
        events.append("receipt")
        body = cast(dict[str, Any], json.loads(request.content))
        assert body["status"] == "rejected"
        return httpx.Response(201, json={"receipt": {"id": "receipt-2", **body}, "created": True})

    consumer = httpx.MockTransport(
        lambda _: httpx.Response(422, json={"code": "consumer_rejected"})
    )
    app = create_backend_app(
        store_client=DataStoreClient(
            "http://database",
            "secret",
            client=httpx.Client(transport=httpx.MockTransport(database)),
        ),
        ai_mode_client=AiModeClient(
            "http://ai",
            client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503))),
        ),
        consumer_client=ConsumerImportClient(
            {"feature-3": ConsumerEndpoint("http://feature-3", "/api/imports")},
            client=httpx.Client(transport=consumer),
        ),
    )
    response = app.test_client().post(
        f"/api/data-platform/v1/dataset-releases/{release_id}/publish",
        headers={"Idempotency-Key": "publish-release-12"},
        json={"version": 1, "comment": "Reviewed", "approved": True},
    )
    assert response.status_code == 424
    assert events == ["receipt"]
    assert response.get_json()["code"] == "consumer_publication_failed"


def test_ai_unavailable_does_not_break_readiness() -> None:
    def database(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "healthy"})

    store = DataStoreClient(
        "http://database", "secret", client=httpx.Client(transport=httpx.MockTransport(database))
    )
    app = create_backend_app(
        store_client=store,
        ai_mode_client=AiModeClient(
            "http://ai",
            client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503))),
        ),
    )
    response = app.test_client().get("/health/ready")
    assert response.status_code == 200
    assert response.get_json()["dependencies"]["database"] is True


def test_release_diagnosis_uses_supported_prompt_contract() -> None:
    release_id = "60000000-0000-0000-0000-000000000011"

    def upstream(request: httpx.Request) -> httpx.Response:
        if request.url.host == "database":
            return httpx.Response(200, json={"release": {"id": release_id}})
        body = cast(dict[str, Any], json.loads(request.content))
        assert body["prompt_set"] == "default.v3"
        assert body["feature_key"] == "student-1-propertyscope-data-platform"
        assert release_id in body["objective"]
        assert body["limits"]["time_budget_ms"] == 300000
        return httpx.Response(201, json={"run": {"id": "70000000-0000-0000-0000-000000000001"}})

    transport = httpx.MockTransport(upstream)
    app = create_backend_app(
        store_client=DataStoreClient(
            "http://database", "secret", client=httpx.Client(transport=transport)
        ),
        ai_mode_client=AiModeClient("http://ai", client=httpx.Client(transport=transport)),
    )
    response = app.test_client().post(
        f"/api/data-platform/v1/dataset-releases/{release_id}/agent-runs"
    )
    assert response.status_code == 201


def test_agent_history_is_scoped_to_propertyscope_feature() -> None:
    def upstream(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "ai"
        assert request.url.path == "/api/v1/agent-runs"
        assert request.url.params["feature_key"] == "student-1-propertyscope-data-platform"
        assert request.url.params["limit"] == "25"
        return httpx.Response(200, json={"items": [], "next_cursor": None})

    app = create_backend_app(
        store_client=DataStoreClient(
            "http://database",
            "secret",
            client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503))),
        ),
        ai_mode_client=AiModeClient(
            "http://ai", client=httpx.Client(transport=httpx.MockTransport(upstream))
        ),
    )
    response = app.test_client().get("/api/data-platform/v1/agent-runs?limit=25")
    assert response.status_code == 200
    assert response.get_json()["items"] == []


def test_job_plan_exposes_real_network_work_only_for_connected_live_scope() -> None:
    job_id = "20000000-0000-0000-0000-000000000004"

    def database(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(
            200,
            json={
                "job": {
                    "id": job_id,
                    "adapter_key": "schools-csv",
                    "import_profile_key": "schools-master",
                    "scope_json": {"profile": "showcase"},
                    "max_objects": 2,
                    "max_bytes": 25_000_000,
                    "max_rows": 5_000,
                    "timeout_seconds": 300,
                }
            },
        )

    transport = httpx.MockTransport(database)
    app = create_backend_app(
        store_client=DataStoreClient(
            "http://database", "secret", client=httpx.Client(transport=transport)
        ),
        ai_mode_client=AiModeClient("http://ai", client=httpx.Client(transport=transport)),
        full_data_enabled=True,
    )
    response = app.test_client().post(
        f"/api/data-platform/v1/jobs/{job_id}/plans",
        json={"run_mode": "full_refresh", "scope": {"profile": "full-data"}},
    )

    assert response.status_code == 200
    assert response.get_json()["network_required"] is True


def test_default_runtime_reports_and_rejects_disabled_live_acquisition() -> None:
    job_id = "20000000-0000-0000-0000-000000000004"

    def database(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "job": {
                    "id": job_id,
                    "adapter_key": "schools-csv",
                    "import_profile_key": "schools-master",
                    "scope_json": {"profile": "showcase"},
                    "max_objects": 2,
                    "max_bytes": 25_000_000,
                    "max_rows": 5_000,
                    "timeout_seconds": 300,
                }
            },
        )

    transport = httpx.MockTransport(database)
    app = create_backend_app(
        store_client=DataStoreClient(
            "http://database", "secret", client=httpx.Client(transport=transport)
        ),
        ai_mode_client=AiModeClient("http://ai", client=httpx.Client(transport=transport)),
        full_data_enabled=False,
    )
    client = app.test_client()

    capabilities = client.get("/api/data-platform/v1/runtime-capabilities")
    plan = client.post(
        f"/api/data-platform/v1/jobs/{job_id}/plans",
        json={"run_mode": "full_refresh", "scope": {"profile": "full-data"}},
    )

    assert capabilities.get_json()["full_data_enabled"] is False
    assert capabilities.get_json()["connected_live_profiles"] == []
    assert plan.status_code == 422
    assert plan.get_json()["code"] == "full_data_runtime_disabled"


def test_job_plan_rejects_catalogued_source_without_live_transport() -> None:
    job_id = "20000000-0000-0000-0000-000000000001"

    def database(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "job": {
                    "id": job_id,
                    "adapter_key": "psi-yearly-zip",
                    "import_profile_key": "psi-sales",
                    "scope_json": {"profile": "showcase"},
                    "max_objects": 10,
                    "max_bytes": 800_000_000,
                    "max_rows": 500_000,
                    "timeout_seconds": 7_200,
                }
            },
        )

    transport = httpx.MockTransport(database)
    app = create_backend_app(
        store_client=DataStoreClient(
            "http://database", "secret", client=httpx.Client(transport=transport)
        ),
        ai_mode_client=AiModeClient("http://ai", client=httpx.Client(transport=transport)),
        full_data_enabled=True,
    )
    response = app.test_client().post(
        f"/api/data-platform/v1/jobs/{job_id}/plans",
        json={
            "run_mode": "full_refresh",
            "scope": {"profile": "full-data", "years": [2025]},
        },
    )

    assert response.status_code == 422
    assert response.get_json()["code"] == "live_transport_unavailable"


def test_job_plan_enables_psi_when_official_archive_cache_is_available() -> None:
    job_id = "20000000-0000-0000-0000-000000000001"

    def database(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "job": {
                    "id": job_id,
                    "adapter_key": "psi-yearly-zip",
                    "import_profile_key": "psi-sales",
                    "scope_json": {"profile": "showcase"},
                    "max_objects": 10,
                    "max_bytes": 800_000_000,
                    "max_rows": 500_000,
                    "timeout_seconds": 7_200,
                }
            },
        )

    transport = httpx.MockTransport(database)
    app = create_backend_app(
        store_client=DataStoreClient(
            "http://database", "secret", client=httpx.Client(transport=transport)
        ),
        ai_mode_client=AiModeClient("http://ai", client=httpx.Client(transport=transport)),
        full_data_enabled=True,
        psi_transport_enabled=True,
        psi_cached_years=(2025,),
        psi_cached_weeks=("2026-08-10",),
    )
    client = app.test_client()

    capabilities = client.get("/api/data-platform/v1/runtime-capabilities")
    response = client.post(
        f"/api/data-platform/v1/jobs/{job_id}/plans",
        json={
            "run_mode": "full_refresh",
            "scope": {"profile": "full-data", "years": [2025]},
        },
    )

    assert "psi-sales" in capabilities.get_json()["connected_live_profiles"]
    assert capabilities.get_json()["cached_live_profiles"] == ["psi-sales"]
    assert response.status_code == 200
    assert response.get_json()["network_required"] is False
    assert response.get_json()["source_cache_required"] is True
    assert capabilities.get_json()["cached_source_years"] == {"psi-sales": [2025]}
    assert capabilities.get_json()["cached_source_weeks"] == {"psi-sales": ["2026-08-10"]}

    missing = client.post(
        f"/api/data-platform/v1/jobs/{job_id}/plans",
        json={
            "run_mode": "full_refresh",
            "scope": {"profile": "full-data", "years": [2024]},
        },
    )
    assert missing.status_code == 200
    assert missing.get_json()["network_required"] is True
    assert missing.get_json()["source_cache_required"] is False

    weekly = client.post(
        f"/api/data-platform/v1/jobs/{job_id}/plans",
        json={
            "run_mode": "full_refresh",
            "scope": {"profile": "full-data", "weeks": ["2026-08-10"]},
        },
    )
    assert weekly.status_code == 200
    assert weekly.get_json()["network_required"] is False
    assert weekly.get_json()["source_cache_required"] is True

    showcase = client.post(
        f"/api/data-platform/v1/jobs/{job_id}/plans",
        json={
            "run_mode": "full_refresh",
            "scope": {"profile": "showcase", "years": [2025]},
        },
    )
    assert showcase.status_code == 200
    assert showcase.get_json()["source_cache_required"] is False


def test_protected_tool_rejects_forged_agent_run_header() -> None:
    run_id = "70000000-0000-0000-0000-000000000001"
    source_run_id = "30000000-0000-0000-0000-000000000003"

    def upstream(request: httpx.Request) -> httpx.Response:
        if request.url.host == "ai":
            return httpx.Response(404, json={"code": "agent_run_not_found"})
        raise AssertionError("database must not be called without durable approval evidence")

    transport = httpx.MockTransport(upstream)
    app = create_backend_app(
        store_client=DataStoreClient(
            "http://database", "secret", client=httpx.Client(transport=transport)
        ),
        ai_mode_client=AiModeClient("http://ai", client=httpx.Client(transport=transport)),
    )
    response = app.test_client().post(
        "/api/data-platform/v1/tools/runs.retry.v1",
        headers={"X-Agent-Run-ID": run_id},
        json={
            "run_id": source_run_id,
            "profile_key": "fixture-property-full",
            "idempotency_key": "approved-retry-1",
        },
    )
    assert response.status_code == 422
    assert response.get_json()["code"] == "human_approval_required"


def test_report_section_projects_bounded_identity_and_release_evidence() -> None:
    property_ref = "a0000000-0000-0000-0000-000000000001"

    def database(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "property": {
                    "address_display": "1 Example Street, Sydney NSW 2000",
                    "resolution_status": "resolved",
                    "locality": "Sydney",
                    "postcode": "2000",
                    "state": "NSW",
                    "longitude": 151.2,
                    "latitude": -33.8,
                    "geometry": {"type": "Point", "coordinates": [151.2, -33.8]},
                },
                "identifiers": [{"scheme": "GNAF_PID", "identifier_value": "GANSW123"}],
                "coverage": [
                    {
                        "dataset_id": "bocsar-crime",
                        "target_feature": "feature-3",
                        "dataset_release_id": "60000000-0000-0000-0000-000000000003",
                        "release_version": "2026-Q2",
                        "schema_version": "1.0.0",
                        "coverage_status": "supported",
                        "coverage_scope": {"postcode": "2000"},
                        "accepted_at": "2026-08-03T00:00:00Z",
                        "checked_at": "2026-08-03T00:00:00Z",
                    }
                ],
            },
        )

    app = create_backend_app(
        store_client=DataStoreClient(
            "http://database",
            "secret",
            client=httpx.Client(transport=httpx.MockTransport(database)),
        ),
        ai_mode_client=AiModeClient(
            "http://ai",
            client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503))),
        ),
    )
    response = app.test_client().get(
        f"/api/data-platform/v1/properties/{property_ref}/report-section"
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["schema_version"] == "propertyscope.report-section.v1"
    assert body["identity"]["gnaf_pid"] == "GANSW123"
    assert body["release_evidence"][0]["dataset_id"] == "bocsar-crime"


def test_every_catalog_tool_binds_to_a_real_backend_route() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={}))
    app = create_backend_app(
        store_client=DataStoreClient(
            "http://database", "secret", client=httpx.Client(transport=transport)
        ),
        ai_mode_client=AiModeClient("http://ai", client=httpx.Client(transport=transport)),
    )
    catalog = cast(
        dict[str, Any],
        yaml.safe_load(
            (Path(__file__).resolve().parents[2] / "tool-catalog.yaml").read_text(encoding="utf-8")
        ),
    )
    rules = {rule.rule: set(rule.methods or ()) for rule in app.url_map.iter_rules()}
    for binding in catalog["tools"]:
        assert binding["path"] in rules
        assert binding["method"] in rules[binding["path"]]
