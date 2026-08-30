from __future__ import annotations

import json
import sys
import threading
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
from flask import Flask
from werkzeug.serving import BaseWSGIServer, make_server

ROOT = Path(__file__).parents[3]
sys.path.insert(0, str(ROOT / "poc" / "feature-6" / "backend" / "src"))
sys.path.insert(0, str(ROOT / "poc" / "feature-6" / "database" / "src"))

from propertyscope_integration_poc import (  # noqa: E402
    AiModeClient,
    AiModeUnavailableError,
    Feature1HttpError,
    PublicationReceipt,
    PublicationRequest,
    Settings,
    StoreHttpClient,
    create_app,
)
from propertyscope_integration_store.app import (  # noqa: E402
    create_app as create_store_app,
)

PROPERTY_REF = uuid.UUID("a0000000-0000-0000-0000-000000000001")
MARKET_ID = uuid.UUID("b0000000-0000-0000-0000-000000000001")
SITE_ID = uuid.UUID("c0000000-0000-0000-0000-000000000001")
RUN_ID = uuid.UUID("d0000000-0000-0000-0000-000000000001")


@contextmanager
def _serve(app: Flask) -> Iterator[str]:
    server: BaseWSGIServer = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


class FakeFeature1:
    available = True

    def catalogue(self, **_: Any) -> Mapping[str, Any]:
        if not self.available:
            raise Feature1HttpError(503, "provider offline")
        return {"items": [{"dataset_id": "nsw-psi-sales"}], "count": 1, "next_cursor": None}

    def property_search(self, query: str, **_: Any) -> Mapping[str, Any]:
        return {
            "items": [
                {
                    "property_ref": str(PROPERTY_REF),
                    "address_display": "178 HOPETOUN ST KURRI KURRI NSW 2327",
                    "locality": "KURRI KURRI",
                    "postcode": "2327",
                }
            ],
            "count": 1,
            "query": query,
        }

    def report_section(self, property_ref: uuid.UUID, **_: Any) -> Mapping[str, Any]:
        if not self.available:
            raise Feature1HttpError(503, "provider offline")
        return {
            "schema_version": "propertyscope.report-section.v1",
            "property_ref": str(property_ref),
            "address_display": "178 HOPETOUN ST KURRI KURRI NSW 2327",
            "identity": {
                "postcode": "2327",
                "locality": "KURRI KURRI",
                "latitude": -32.82,
                "longitude": 151.48,
            },
            "release_evidence": [],
            "evidence_count": 0,
        }


class FakeStore:
    def __init__(self) -> None:
        self.deleted: list[tuple[str, uuid.UUID, int]] = []
        self.created: list[tuple[str, Mapping[str, Any]]] = []

    def ready(self, **_: Any) -> bool:
        return True

    def list_imports(self, **_: Any) -> Mapping[str, Any]:
        return {"items": [], "count": 0}

    def collection(
        self,
        resource: str,
        *,
        method: str = "GET",
        body: Mapping[str, Any] | None = None,
        **_: Any,
    ) -> Mapping[str, Any]:
        if method == "POST":
            assert body is not None
            self.created.append((resource, body))
            return {"id": str(uuid.uuid4()), **body, "version": 1}
        items: dict[str, list[dict[str, Any]]] = {
            "market-cases": [
                {
                    "id": str(MARKET_ID),
                    "name": "Local sales",
                    "property_ref": str(PROPERTY_REF),
                    "version": 2,
                }
            ],
            "site-reviews": [
                {
                    "id": str(SITE_ID),
                    "name": "Checks",
                    "property_ref": str(PROPERTY_REF),
                    "version": 3,
                }
            ],
            "saved-places": [],
            "buyer-cases": [],
        }
        return {"items": items[resource], "count": len(items[resource])}

    def mutate_item(
        self,
        resource: str,
        item_id: uuid.UUID,
        *,
        method: str,
        expected_version: int | None = None,
        body: Mapping[str, Any] | None = None,
        **_: Any,
    ) -> Mapping[str, Any] | None:
        if method == "DELETE":
            assert expected_version is not None
            self.deleted.append((resource, item_id, expected_version))
            return None
        return {"id": str(item_id), **dict(body or {}), "version": 4}

    def market_summary(self, _: uuid.UUID, **__: Any) -> Mapping[str, Any]:
        return {"selected_transaction_count": 3, "median_price_aud": 900_000}

    def place_summary(self, postcode: str, **_: Any) -> Mapping[str, Any]:
        return {
            "postcode": postcode,
            "crime_series": [{"category": "Fixture offence", "observed_count": 3}],
            "nearby_schools": [{"school_name": "Example Public School"}],
        }

    def site_evidence(self, _: uuid.UUID, **__: Any) -> Mapping[str, Any]:
        return {
            "evidence": [
                {"domain": "planning", "state": "unavailable"},
                {"domain": "building", "state": "unavailable"},
            ]
        }


class FakeImporter:
    def import_callback(self, *_: Any, **__: Any) -> PublicationReceipt:
        return PublicationReceipt(
            consumer_operation_id="publication-key",
            status="accepted",
            schema_version="propertyscope.school-points.v1",
            content_sha256="a" * 64,
            rows_received=2,
            rows_accepted=2,
            rows_rejected=0,
        )

    def reconcile_accepted(self, *_: Any, **__: Any) -> None:
        return None


class FakeAiMode:
    available = True

    def ready(self) -> bool:
        return self.available

    def create_research_run(self, property_ref: uuid.UUID, *_: Any, **__: Any) -> Mapping[str, Any]:
        if not self.available:
            raise AiModeUnavailableError(
                "AI mode is unavailable; deterministic research remains usable"
            )
        return {
            "id": "d0000000-0000-0000-0000-000000000001",
            "feature_key": "propertyscope-integration-poc",
            "status": "queued",
            "trusted_property_ref": str(property_ref),
        }

    def get_run(self, run_id: uuid.UUID, **_: Any) -> Mapping[str, Any]:
        return {
            "id": str(run_id),
            "feature_key": "propertyscope-integration-poc",
            "status": "completed",
        }


def _app(
    feature1: FakeFeature1 | None = None,
    store: FakeStore | None = None,
    ai_mode: FakeAiMode | None = None,
) -> Any:
    return create_app(
        {"TESTING": True},
        settings=Settings(
            feature1_origin="http://feature-1.local",
            ai_mode_origin="http://ai-mode.local",
            store_origin="http://store.local",
            internal_token="secret",
            contract_root=ROOT / "student-1" / "contracts",
            maximum_artifact_bytes=1_000_000,
            maximum_legacy_json_bytes=1_000_000,
        ),
        feature1_client=feature1 or FakeFeature1(),  # type: ignore[arg-type]
        ai_mode_client=ai_mode or FakeAiMode(),  # type: ignore[arg-type]
        store_client=store or FakeStore(),  # type: ignore[arg-type]
        importer=FakeImporter(),  # type: ignore[arg-type]
    )


def test_research_composes_independent_evidence_states() -> None:
    client = _app().test_client()

    response = client.get(f"/api/integration-poc/v1/properties/{PROPERTY_REF}/research")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["state"] == "needs_verification"
    assert payload["sections"]["property_identity"]["state"] == "complete"
    assert payload["sections"]["market"]["state"] == "complete"
    assert payload["sections"]["place"]["state"] == "complete"
    assert payload["sections"]["site_due_diligence"]["state"] == "needs_verification"


def test_provider_failure_does_not_disable_store_or_erase_other_sections() -> None:
    feature1 = FakeFeature1()
    feature1.available = False
    client = _app(feature1=feature1).test_client()

    ready = client.get("/health/ready")
    research = client.get(f"/api/integration-poc/v1/properties/{PROPERTY_REF}/research")

    assert ready.status_code == 200
    assert ready.get_json()["provider_state"] == "unavailable"
    assert research.status_code == 200
    sections = research.get_json()["sections"]
    assert sections["property_identity"]["state"] == "unavailable"
    assert sections["market"]["state"] == "complete"
    assert sections["site_due_diligence"]["state"] == "needs_verification"


def test_read_only_tools_match_public_compositions() -> None:
    client = _app().test_client()

    research = client.post(
        "/api/integration-poc/v1/tools/research.compose.v1",
        json={"property_ref": str(PROPERTY_REF)},
    )
    readiness = client.post("/api/integration-poc/v1/tools/provider.readiness.v1", json={})

    assert research.status_code == 200
    assert research.get_json()["property_ref"] == str(PROPERTY_REF)
    assert set(research.get_json()) == {"property_ref", "identity", "sections", "limitations"}
    assert readiness.status_code == 200
    assert readiness.get_json()["feature_1"]["ready"] is True
    assert set(readiness.get_json()) == {"feature_1", "store", "catalogue", "poc"}


def test_ai_run_proxy_is_optional_bounded_and_feature_scoped() -> None:
    client = _app().test_client()

    created = client.post(
        "/api/integration-poc/v1/agent-runs",
        json={"property_ref": str(PROPERTY_REF), "question": "Explain the available evidence."},
        headers={"Idempotency-Key": "poc-ai-run-key"},
    )
    fetched = client.get("/api/integration-poc/v1/agent-runs/d0000000-0000-0000-0000-000000000001")

    assert created.status_code == 202
    assert created.get_json()["ai_state"] == "queued"
    assert created.get_json()["run"]["feature_key"] == "propertyscope-integration-poc"
    assert fetched.status_code == 200
    assert fetched.get_json()["feature_key"] == "propertyscope-integration-poc"


def test_ai_unavailability_is_explicit_without_disabling_research() -> None:
    ai_mode = FakeAiMode()
    ai_mode.available = False
    client = _app(ai_mode=ai_mode).test_client()

    ai_response = client.post(
        "/api/integration-poc/v1/agent-runs",
        json={"property_ref": str(PROPERTY_REF), "question": "Explain evidence."},
        headers={"Idempotency-Key": "poc-ai-run-key"},
    )
    research = client.get(f"/api/integration-poc/v1/properties/{PROPERTY_REF}/research")

    assert ai_response.status_code == 503
    assert ai_response.content_type == "application/problem+json"
    assert "deterministic research remains usable" in ai_response.get_json()["detail"]
    assert research.status_code == 200


def test_ai_mode_client_sends_exact_feature_tool_and_limit_boundary() -> None:
    observed: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["payload"] = json.loads(request.content)
        observed["key"] = request.headers["Idempotency-Key"]
        return httpx.Response(
            202,
            json={
                "id": "d0000000-0000-0000-0000-000000000001",
                "feature_key": "propertyscope-integration-poc",
                "status": "queued",
            },
        )

    ai_mode = AiModeClient(
        "http://ai-mode.local",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    ai_mode.create_research_run(
        PROPERTY_REF,
        "Explain only supported evidence.",
        idempotency_key="poc-ai-run-key",
    )

    payload = observed["payload"]
    assert payload["feature_key"] == "propertyscope-integration-poc"
    assert payload["tool_allowlist"] == [
        "integration.provider_readiness.v1",
        "integration.research_compose.v1",
    ]
    assert payload["trusted_identifiers"] == [{"kind": "property_ref", "value": str(PROPERTY_REF)}]
    assert payload["limits"] == {
        "max_iterations": 4,
        "max_tool_calls": 4,
        "time_budget_ms": 60_000,
        "max_model_repairs": 1,
    }
    assert "User question" in payload["objective"]
    assert observed["key"] == "poc-ai-run-key"


def test_ai_mode_client_reads_the_run_detail_envelope() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/api/v1/agent-runs/{RUN_ID}"
        return httpx.Response(
            200,
            json={
                "run": {
                    "id": str(RUN_ID),
                    "feature_key": "propertyscope-integration-poc",
                    "status": "failed",
                },
                "steps": [],
                "reviews": [],
            },
        )

    ai_mode = AiModeClient(
        "http://ai-mode.local",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = ai_mode.get_run(RUN_ID)

    assert result["run"]["feature_key"] == "propertyscope-integration-poc"
    assert result["run"]["status"] == "failed"


def test_callback_returns_closed_consumer_receipt_and_request_id() -> None:
    client = _app().test_client()

    response = client.post(
        "/api/data-import/v1/propertyscope-releases",
        json={"ignored-by-injected-importer": True},
        headers={"Idempotency-Key": "publication-key", "X-Request-ID": "poc-test-request"},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "poc-test-request"
    assert set(response.get_json()) == {
        "consumer_operation_id",
        "status",
        "schema_version",
        "content_sha256",
        "rows_received",
        "rows_accepted",
        "rows_rejected",
        "error",
    }


def test_frontend_shaped_crud_is_normalised_and_delete_uses_retained_version() -> None:
    store = FakeStore()
    client = _app(store=store).test_client()

    created = client.post(
        "/api/integration-poc/v1/market-cases",
        json={"title": "My case", "property_ref": str(PROPERTY_REF), "notes": "Evidence"},
    )
    deleted = client.delete(f"/api/integration-poc/v1/market-cases/{MARKET_ID}")

    assert created.status_code == 201
    assert store.created[0][1]["name"] == "My case"
    assert deleted.status_code == 204
    assert store.deleted == [("market-cases", MARKET_ID, 2)]


def test_problem_details_replace_invalid_request_ids() -> None:
    response = (
        _app()
        .test_client()
        .get(
            "/api/integration-poc/v1/properties/search",
            headers={"X-Request-ID": "contains spaces"},
        )
    )

    assert response.status_code == 422
    assert response.content_type == "application/problem+json"
    assert response.get_json()["request_id"] == response.headers["X-Request-ID"]
    uuid.UUID(response.headers["X-Request-ID"])


def test_store_http_client_streams_publication_ndjson_without_materialising_records() -> None:
    observed: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["authorization"] = request.headers["Authorization"]
        observed["content_type"] = request.headers["Content-Type"]
        observed["lines"] = [json.loads(line) for line in request.read().splitlines()]
        return httpx.Response(
            201,
            json={
                "consumer_operation_id": "stream-import-key",
                "status": "accepted",
                "schema_version": "propertyscope.property-sales.v2",
                "content_sha256": "a" * 64,
                "rows_received": 1,
                "rows_accepted": 1,
                "rows_rejected": 0,
                "error": None,
            },
        )

    store = StoreHttpClient(
        "http://store.local",
        "private-token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    publication = PublicationRequest(
        release_id=uuid.UUID("60000000-0000-0000-0000-000000000002"),
        dataset_id="nsw-psi-sales",
        target_feature="feature-2",
        schema_version="propertyscope.property-sales.v2",
        content_sha256="a" * 64,
        record_count=1,
        manifest={"release_id": "unused-in-wire-test"},
        artifact_path=(
            "/api/data-platform/v1/dataset-releases/60000000-0000-0000-0000-000000000002/artifact"
        ),
        idempotency_key="stream-import-key",
    )

    receipt = store.import_release_atomic(publication, ({"row": 1},))

    assert receipt["status"] == "accepted"
    assert observed["authorization"] == "Bearer private-token"
    assert observed["content_type"] == "application/x-ndjson"
    assert observed["lines"][0]["publication"]["release_id"] == str(publication.release_id)
    assert observed["lines"][1] == {"row": 1}


def test_store_http_client_matches_private_database_api(tmp_path: Path) -> None:
    release_id = uuid.UUID("60000000-0000-0000-0000-000000000003")
    manifest = {
        "manifest_schema_version": "propertyscope.release-manifest.v1",
        "product_schema_version": "propertyscope.school-points.v1",
        "release_id": str(release_id),
        "release_version": "schools-poc-v1",
        "dataset_id": "nsw-government-schools",
        "target_feature": "feature-3",
        "candidate_generation_id": str(release_id),
        "normalisation_version": "1.0.0",
        "record_count": 1,
        "content_sha256": "b" * 64,
        "byte_count": 100,
        "media_type": "application/x-ndjson",
        "content_encoding": "gzip",
    }
    publication = PublicationRequest(
        release_id=release_id,
        dataset_id="nsw-government-schools",
        target_feature="feature-3",
        schema_version="propertyscope.school-points.v1",
        content_sha256="b" * 64,
        record_count=1,
        manifest=manifest,
        artifact_path=f"/api/data-platform/v1/dataset-releases/{release_id}/artifact",
        idempotency_key="private-http-import",
    )
    record = {
        "school_code": "1001",
        "school_name": "Example Public School",
        "school_type": "Primary",
        "operational_status": "Open",
        "locality_normalised": "PARRAMATTA",
        "latitude": -33.81,
        "longitude": 151.01,
        "provenance": {"release_id": str(release_id)},
    }
    database = create_store_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "integration.sqlite3"),
            "INTERNAL_TOKEN": "private-token",
        }
    )

    with _serve(database) as origin:
        store = StoreHttpClient(origin, "private-token")
        first = store.import_release_atomic(publication, (record,))
        retained = store.find_publication("feature-3", "private-http-import")

    assert first["status"] == "accepted"
    assert retained is not None
    assert retained.release_id == release_id
    assert retained.receipt.rows_accepted == 1
