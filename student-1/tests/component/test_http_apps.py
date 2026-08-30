from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
import yaml

from propertyscope_data_platform.app import create_app as create_backend_app
from propertyscope_data_platform.clients import (
    AiModeClient,
    ConsumerEndpoint,
    ConsumerImportClient,
    DataStoreClient,
)
from propertyscope_data_platform.domain import ConsumerPublicationRequest
from shared_contracts import TypedHealthProjection


def _backend_with_database(database: Any) -> Any:
    transport = httpx.MockTransport(database)
    return create_backend_app(
        store_client=DataStoreClient(
            "http://database", "secret", client=httpx.Client(transport=transport)
        ),
        ai_mode_client=AiModeClient(
            "http://ai",
            client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503))),
        ),
    )


def test_cancel_reconciles_a_lost_response_after_durable_persistence() -> None:
    run_id = "60000000-0000-0000-0000-000000000041"
    calls: list[str] = []

    def database(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.method == "POST":
            raise httpx.ReadError("response was lost after commit", request=request)
        return httpx.Response(
            200,
            json={
                "run": {
                    "id": run_id,
                    "status": "running",
                    "cancel_requested_at": "2026-08-30T01:02:03Z",
                }
            },
        )

    response = (
        _backend_with_database(database)
        .test_client()
        .post(f"/api/data-platform/v1/ingestion-runs/{run_id}/cancel", json={})
    )

    assert response.status_code == 200
    assert response.get_json()["run"]["cancel_requested_at"] == "2026-08-30T01:02:03Z"
    assert calls == [
        f"POST /internal/data-platform/v1/runs/{run_id}/cancel",
        f"GET /internal/data-platform/v1/runs/{run_id}",
    ]


def test_cancel_reconciles_persisted_503_and_idempotent_retry() -> None:
    run_id = "60000000-0000-0000-0000-000000000042"
    calls: list[str] = []

    def database(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.method == "POST":
            return httpx.Response(503, json={"code": "dependency_unavailable"})
        return httpx.Response(
            200,
            json={
                "run": {
                    "id": run_id,
                    "status": "cancelled",
                    "cancel_requested_at": "2026-08-30T02:03:04Z",
                }
            },
        )

    client = _backend_with_database(database).test_client()
    first = client.post(f"/api/data-platform/v1/ingestion-runs/{run_id}/cancel", json={})
    replay = client.post(f"/api/data-platform/v1/ingestion-runs/{run_id}/cancel", json={})

    assert first.status_code == replay.status_code == 200
    assert first.get_json() == replay.get_json()
    assert replay.get_json()["run"]["status"] == "cancelled"
    assert calls == [
        f"POST /internal/data-platform/v1/runs/{run_id}/cancel",
        f"GET /internal/data-platform/v1/runs/{run_id}",
        f"POST /internal/data-platform/v1/runs/{run_id}/cancel",
        f"GET /internal/data-platform/v1/runs/{run_id}",
    ]


def test_cancel_keeps_safe_failure_when_persistence_is_unproven() -> None:
    run_id = "60000000-0000-0000-0000-000000000043"

    def database(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(503, json={"code": "dependency_unavailable"})
        return httpx.Response(
            200,
            json={
                "run": {
                    "id": run_id,
                    "status": "running",
                    "cancel_requested_at": None,
                }
            },
        )

    response = (
        _backend_with_database(database)
        .test_client()
        .post(f"/api/data-platform/v1/ingestion-runs/{run_id}/cancel", json={})
    )

    assert response.status_code == 503
    assert response.content_type == "application/problem+json"
    assert response.get_json()["code"] == "cancellation_unconfirmed"


def test_cancel_preserves_terminal_run_conflict_without_reconciliation() -> None:
    run_id = "60000000-0000-0000-0000-000000000044"
    calls: list[str] = []

    def database(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        return httpx.Response(
            409,
            json={
                "status": 409,
                "code": "conflict",
                "detail": "terminal run cannot be cancelled",
            },
            headers={"Content-Type": "application/problem+json"},
        )

    response = (
        _backend_with_database(database)
        .test_client()
        .post(f"/api/data-platform/v1/ingestion-runs/{run_id}/cancel", json={})
    )

    assert response.status_code == 409
    assert response.get_json()["detail"] == "terminal run cannot be cancelled"
    assert calls == [f"POST /internal/data-platform/v1/runs/{run_id}/cancel"]


def test_backend_proxies_property_search_and_preserves_expected_negative() -> None:
    def database(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-PropertyScope-Internal-Token"] == "secret"
        if request.url.path == "/health/ready":
            return httpx.Response(200, json={"status": "healthy"})
        assert request.url.params["state"] == "VIC"
        return httpx.Response(
            200,
            json={
                "items": [],
                "count": 0,
                "total": 0,
                "limit": 25,
                "offset": 0,
                "next_offset": None,
                "query": "10 Example Street",
                "supported": False,
            },
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
    assert response.get_json() == {
        "items": [],
        "count": 0,
        "total": 0,
        "limit": 25,
        "offset": 0,
        "next_offset": None,
        "query": "10 Example Street",
        "supported": False,
    }


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


def test_backend_exposes_complete_sales_source_pages_from_accepted_generation() -> None:
    release_id = "60000000-0000-0000-0000-000000000022"
    requests: list[str] = []

    def database(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/internal/data-platform/v1/releases":
            assert request.url.params["status"] == "accepted"
            assert request.url.params["dataset_id"] == "nsw-psi-sales"
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": release_id,
                            "schema_version": "propertyscope.property-sales.v3",
                        }
                    ]
                },
            )
        assert request.url.path == (
            f"/internal/data-platform/v1/releases/{release_id}/sales-source-records"
        )
        assert request.url.params["year"] == "1999"
        assert request.url.params["limit"] == "5000"
        assert request.url.params["offset"] == "10000"
        return httpx.Response(
            200,
            json={
                "schema_version": "propertyscope.psi-source-records.v1",
                "release": {
                    "id": release_id,
                    "dataset_id": "nsw-psi-sales",
                    "release_version": "2026-08",
                    "status": "accepted",
                    "schema_version": "propertyscope.property-sales.v3",
                },
                "source_partition_year": 1999,
                "items": [{"source_business_key": "001:P1:1"}],
                "count": 1,
                "total": 12345,
                "limit": 5000,
                "offset": 10000,
                "next_offset": 10001,
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
        "/api/data-platform/v1/data-products/nsw-psi-sales/source-records"
        "?year=1999&limit=5000&offset=10000"
    )

    assert response.status_code == 200
    assert response.get_json()["total"] == 12345
    assert requests == [
        "/internal/data-platform/v1/releases",
        f"/internal/data-platform/v1/releases/{release_id}/sales-source-records",
    ]


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


def test_publication_queues_durable_consumer_import_without_calling_consumer() -> None:
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
        "manifest_json": {"target_feature": "feature-3"},
        "status": "awaiting_review",
        "version": 2,
    }

    def database(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200, json={"release": release, "receipts": [], "consumer_imports": []}
            )
        assert request.url.path.endswith("/consumer-imports")
        events.append("queue")
        body = cast(dict[str, Any], json.loads(request.content))
        assert body["dataset_id"] == release["dataset_id"]
        assert body["content_sha256"] == digest
        return httpx.Response(
            202,
            json={
                "operation": {
                    "id": "70000000-0000-0000-0000-000000000001",
                    "dataset_release_id": release_id,
                    "status": "queued",
                    "phase_key": "connect",
                    "attempt_number": 1,
                    "requested_at": "2026-08-26T10:00:00Z",
                    "version": 1,
                    "lease_token": "must-not-leak",
                },
                "created": True,
            },
        )

    def consumer(_: httpx.Request) -> httpx.Response:
        raise AssertionError("browser publication must not call the consumer")

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
    assert response.status_code == 202
    assert events == ["queue"]
    assert response.get_json()["release"]["status"] == "awaiting_review"
    assert response.get_json()["consumer_import"]["status"] == "queued"
    assert response.get_json()["consumer_import"]["budgets"]["connect_timeout_seconds"] == 5
    assert "lease_token" not in response.get_json()["consumer_import"]


def test_publication_retry_replays_durable_delivery_without_calling_consumer() -> None:
    release_id = "60000000-0000-0000-0000-000000000013"
    digest = "c" * 64
    release = {
        "id": release_id,
        "dataset_id": "bocsar-crime",
        "target_feature": "feature-3",
        "schema_version": "propertyscope.crime-series.v1",
        "content_sha256": digest,
        "record_count": 2,
        "manifest_json": {},
        "status": "awaiting_review",
        "version": 2,
    }
    operation: dict[str, Any] | None = None
    consumer_calls = 0

    def database(request: httpx.Request) -> httpx.Response:
        nonlocal operation
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "release": release,
                    "receipts": [],
                    "consumer_imports": [operation] if operation else [],
                },
            )
        created = operation is None
        operation = {
            "id": "72000000-0000-0000-0000-000000000013",
            "dataset_release_id": release_id,
            "idempotency_key": "publish-recovery",
            "status": "queued",
            "phase_key": "connect",
            "attempt_number": 1,
            "version": 1,
        }
        return httpx.Response(
            202 if created else 200,
            json={"operation": operation, "created": created},
        )

    def consumer(_: httpx.Request) -> httpx.Response:
        nonlocal consumer_calls
        consumer_calls += 1
        return httpx.Response(
            200,
            json={
                "consumer_operation_id": "publish-recovery",
                "status": "accepted",
                "schema_version": "propertyscope.crime-series.v1",
                "content_sha256": digest,
                "rows_received": 2,
                "rows_accepted": 2,
                "rows_rejected": 0,
                "error": None,
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
        consumer_client=ConsumerImportClient(
            {"feature-3": ConsumerEndpoint("http://feature-3", "/api/imports")},
            client=httpx.Client(transport=httpx.MockTransport(consumer)),
        ),
    )
    client = app.test_client()
    kwargs = {
        "headers": {"Idempotency-Key": "publish-recovery"},
        "json": {"version": 2, "comment": "Reviewed", "approved": True},
    }

    first = client.post(f"/api/data-platform/v1/dataset-releases/{release_id}/publish", **kwargs)
    second = client.post(f"/api/data-platform/v1/dataset-releases/{release_id}/publish", **kwargs)

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.get_json()["replayed"] is True
    assert consumer_calls == 0


@pytest.mark.parametrize(
    ("activation_status", "database_status", "expected_http"),
    [("succeeded", 200, 200), ("failed", 409, 409)],
)
def test_publication_replay_preserves_terminal_activation_outcome(
    activation_status: str,
    database_status: int,
    expected_http: int,
) -> None:
    release_id = "60000000-0000-0000-0000-000000000015"
    receipt_id = "71000000-0000-0000-0000-000000000015"
    digest = "d" * 64
    release = {
        "id": release_id,
        "dataset_id": "fixture-property",
        "target_feature": "feature-1",
        "schema_version": "propertyscope.property-snapshot.v1",
        "content_sha256": digest,
        "record_count": 1,
        "manifest_json": {},
        "status": "awaiting_review",
        "version": 4,
    }
    receipt = {
        "id": receipt_id,
        "consumer_operation_id": "terminal-activation-replay",
        "status": "accepted",
        "schema_version": release["schema_version"],
        "content_sha256": digest,
        "rows_received": 1,
        "rows_accepted": 1,
        "rows_rejected": 0,
    }

    def database(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"release": release, "receipts": [receipt]})
        assert request.url.path.endswith("/activations")
        if activation_status == "failed":
            return httpx.Response(
                database_status,
                json={
                    "status": database_status,
                    "code": "release_activation_failed",
                    "detail": "The publication activation failed before the live version changed; "
                    "a fresh request can retry it",
                },
            )
        return httpx.Response(
            database_status,
            json={
                "activation": {"id": "activation-winner", "status": activation_status},
                "created": False,
                "outcome": "completed",
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

    response = app.test_client().post(
        f"/api/data-platform/v1/dataset-releases/{release_id}/publish",
        headers={"Idempotency-Key": "terminal-activation-replay"},
        json={"version": 4, "comment": "Reviewed", "approved": True},
    )

    assert response.status_code == expected_http
    if activation_status == "failed":
        assert response.get_json()["code"] == "release_activation_failed"
        assert "fresh request" in response.get_json()["detail"]
    else:
        assert response.get_json()["publication_status"] == "completed"
        assert response.get_json()["activation"]["status"] == "succeeded"


def test_browser_publish_does_not_wait_for_consumer_rejection() -> None:
    release_id = "60000000-0000-0000-0000-000000000012"
    digest = "b" * 64
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
            return httpx.Response(
                200, json={"release": release, "receipts": [], "consumer_imports": []}
            )
        return httpx.Response(
            202,
            json={
                "operation": {
                    "id": "72000000-0000-0000-0000-000000000012",
                    "dataset_release_id": release_id,
                    "status": "queued",
                    "phase_key": "connect",
                    "attempt_number": 1,
                    "version": 1,
                },
                "created": True,
            },
        )

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
    assert response.status_code == 202
    assert response.get_json()["publication_status"] == "pending"


@pytest.mark.parametrize("status_code", [200, 422])
def test_typed_consumer_rejection_preserves_receipt_evidence(status_code: int) -> None:
    publication = ConsumerPublicationRequest(
        release_id="60000000-0000-0000-0000-000000000099",
        dataset_id="bocsar-crime",
        schema_version="crime-series.v1",
        content_sha256="a" * 64,
        record_count=3,
        manifest={},
        artifact_path=(
            "/api/data-platform/v1/dataset-releases/60000000-0000-0000-0000-000000000099/artifact"
        ),
        idempotency_key="publish-release",
    )
    response = httpx.Response(
        status_code,
        json={
            "consumer_operation_id": "publish-release",
            "status": "rejected",
            "schema_version": "crime-series.v1",
            "content_sha256": "a" * 64,
            "rows_received": 3,
            "rows_accepted": 0,
            "rows_rejected": 3,
            "error": {
                "code": "unsupported_period",
                "message": "The release period is outside the supported range",
                "retryable": False,
                "details": {"supported_from": "2024-01"},
            },
        },
    )
    client = ConsumerImportClient(
        {"feature-3": ConsumerEndpoint("http://feature-3", "/api/imports")},
        client=httpx.Client(transport=httpx.MockTransport(lambda _: response)),
    )

    receipt = client.publish("feature-3", publication, {})

    assert receipt.status == "rejected"
    assert receipt.rows_received == 3
    assert receipt.rows_rejected == 3
    assert receipt.error is not None
    assert receipt.error.code == "unsupported_period"


def test_source_scale_local_publication_queues_without_rereading_artifact(
    tmp_path: Path,
) -> None:
    release_id = "60000000-0000-0000-0000-000000000014"
    digest = "a" * 64
    manifest = {
        "manifest_schema_version": "propertyscope.release-manifest.v1",
        "product_schema_version": "propertyscope.property-snapshot.v2",
        "release_id": release_id,
        "release_version": "fixture-local-failure-v1",
        "dataset_id": "fixture-property",
        "target_feature": "feature-1",
        "builder_key": "property-snapshot",
        "builder_version": "3.0.0",
        "import_profile": "property-fixture",
        "normalisation_version": "1.0.0",
        "publisher": "PropertyScope test",
        "source": "Source-scale asynchronous binding test",
        "source_release": "fixture-v1",
        "source_retrieved_at": "2026-08-16T01:02:03Z",
        "source_effective_at": None,
        "candidate_generation_id": release_id,
        "record_count": 5_190_134,
        "record_count_definition": "property records",
        "content_sha256": digest,
        "media_type": "application/x-ndjson",
        "content_encoding": "gzip",
        "byte_count": 515_790_493,
        "geography_coverage": ["NSW"],
        "temporal_coverage": None,
        "measures": [],
        "entity_types": ["property"],
        "source_licence": "synthetic-test-data",
        "licence_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "redistribution_decision": "committed-synthetic-fixture",
        "download_permitted": True,
        "known_limitations": ["test"],
        "created_at": "2026-08-16T01:02:03Z",
        "supersedes_release_id": None,
    }
    release = {
        "id": release_id,
        "dataset_id": "fixture-property",
        "target_feature": "feature-1",
        "schema_version": "propertyscope.property-snapshot.v2",
        "content_sha256": digest,
        "record_count": 5_190_134,
        "manifest_json": manifest,
        "status": "awaiting_review",
        "version": 1,
    }
    receipts: list[dict[str, Any]] = []

    def database(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/artifact"):
            return httpx.Response(
                200,
                json={
                    "artifact": {
                        "artifact_kind": "release_export",
                        "content_sha256": digest,
                        "bytes": 515_790_493,
                        "storage_key": f"sha256/{digest[:2]}/{digest}",
                    }
                },
            )
        if request.method == "GET":
            return httpx.Response(200, json={"release": release, "receipts": receipts})
        if request.url.path.endswith("/activations"):
            return httpx.Response(
                202,
                json={
                    "activation": {
                        "id": "70000000-0000-0000-0000-000000000014",
                        "status": "queued",
                        "attempt_number": 1,
                    },
                    "created": True,
                },
            )
        assert request.url.path.endswith("/receipts")
        body = cast(dict[str, Any], json.loads(request.content))
        assert body["status"] == "accepted"
        assert body["rows_received"] == body["rows_accepted"] == 5_190_134
        receipt = {"id": "receipt-local-binding", **body}
        receipts.append(receipt)
        return httpx.Response(201, json={"receipt": receipt, "created": True})

    transport = httpx.MockTransport(database)
    app = create_backend_app(
        store_client=DataStoreClient(
            "http://database", "secret", client=httpx.Client(transport=transport)
        ),
        ai_mode_client=AiModeClient("http://ai", client=httpx.Client(transport=transport)),
        artifact_root=tmp_path,
    )

    started = time.perf_counter()
    response = app.test_client().post(
        f"/api/data-platform/v1/dataset-releases/{release_id}/publish",
        headers={"Idempotency-Key": "publish-source-scale"},
        json={"version": 1, "comment": "Reviewed", "approved": True},
    )
    elapsed = time.perf_counter() - started

    assert response.status_code == 202
    assert elapsed < 10
    assert response.get_json()["activation"]["status"] == "queued"
    assert release["status"] == "awaiting_review"
    assert len(receipts) == 1
    assert receipts[0]["consumer_operation_id"] != "publish-source-scale"
    assert receipts[0]["consumer_operation_id"].startswith("feature-1-local:")


@pytest.mark.parametrize(
    ("response", "expected_code"),
    [
        (
            httpx.Response(
                200,
                json={
                    "consumer_operation_id": "publish-release",
                    "status": "accepted",
                    "schema_version": "propertyscope.wrong.v1",
                    "content_sha256": "a" * 64,
                    "rows_received": 1,
                    "rows_accepted": 1,
                    "rows_rejected": 0,
                    "error": None,
                },
            ),
            "consumer_evidence_mismatch",
        ),
        (
            httpx.Response(
                200,
                json={
                    "consumer_operation_id": "publish-release",
                    "status": "accepted",
                    "schema_version": "propertyscope.property-sales.v2",
                    "content_sha256": "b" * 64,
                    "rows_received": 1,
                    "rows_accepted": 1,
                    "rows_rejected": 0,
                    "error": None,
                },
            ),
            "consumer_evidence_mismatch",
        ),
        (
            httpx.Response(200, content=b"not-json"),
            "consumer_response_invalid",
        ),
        (
            httpx.Response(302, headers={"Location": "http://untrusted.invalid/import"}),
            "consumer_redirect_rejected",
        ),
    ],
)
def test_consumer_receipt_mismatch_and_redirects_fail_closed(
    response: httpx.Response, expected_code: str
) -> None:
    publication = ConsumerPublicationRequest(
        release_id="60000000-0000-0000-0000-000000000099",
        dataset_id="nsw-psi-sales",
        schema_version="propertyscope.property-sales.v2",
        content_sha256="a" * 64,
        record_count=1,
        manifest={},
        artifact_path=(
            "/api/data-platform/v1/dataset-releases/60000000-0000-0000-0000-000000000099/artifact"
        ),
        idempotency_key="publish-release",
    )
    client = ConsumerImportClient(
        {"feature-2": ConsumerEndpoint("http://feature-2", "/api/imports")},
        client=httpx.Client(transport=httpx.MockTransport(lambda _: response)),
    )

    outcome = client.connect("feature-2", publication, {})

    assert outcome.consumer_operation_id is None
    assert outcome.error is not None and outcome.error.code == expected_code


def test_consumer_unavailability_returns_retryable_safe_receipt() -> None:
    def unavailable(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    publication = ConsumerPublicationRequest(
        release_id="60000000-0000-0000-0000-000000000099",
        dataset_id="nsw-psi-sales",
        schema_version="propertyscope.property-sales.v2",
        content_sha256="a" * 64,
        record_count=1,
        manifest={},
        artifact_path=(
            "/api/data-platform/v1/dataset-releases/60000000-0000-0000-0000-000000000099/artifact"
        ),
        idempotency_key="publish-release",
    )
    client = ConsumerImportClient(
        {"feature-2": ConsumerEndpoint("http://feature-2", "/api/imports")},
        client=httpx.Client(transport=httpx.MockTransport(unavailable)),
    )

    outcome = client.connect("feature-2", publication, {})

    assert outcome.consumer_operation_id is None
    assert outcome.error is not None
    assert outcome.error.code == "consumer_unavailable"
    assert outcome.error.retryable is True


@pytest.mark.parametrize("path", ["/api/../admin", "/api/imports?next=evil", "//evil"])
def test_consumer_endpoint_rejects_unfixed_paths(path: str) -> None:
    with pytest.raises(ValueError, match="fixed API path"):
        ConsumerEndpoint("http://feature-2", path)


@pytest.mark.parametrize(
    "origin",
    [
        "ftp://feature-2",
        "http://user:secret@feature-2",
        "http://feature-2/base",
        "http://feature-2?next=evil",
        "http://feature-2#fragment",
        "http://feature-2:invalid",
    ],
)
def test_consumer_endpoint_rejects_non_origin_base_urls(origin: str) -> None:
    with pytest.raises(ValueError, match=r"HTTP\(S\) origin"):
        ConsumerEndpoint(origin, "/api/imports")


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
    assert response.mimetype == "application/json"
    payload = response.get_json()
    TypedHealthProjection.model_validate(payload)
    assert payload["status"] == "healthy"
    assert payload["http_status"] == 200
    assert payload["checks"]["database"] == {
        "required": True,
        "status": "healthy",
        "detail": "Feature-owned database API is ready",
    }


def test_release_diagnosis_uses_supported_prompt_contract() -> None:
    release_id = "60000000-0000-0000-0000-000000000011"

    def upstream(request: httpx.Request) -> httpx.Response:
        if request.url.host == "database":
            return httpx.Response(200, json={"release": {"id": release_id}})
        body = cast(dict[str, Any], json.loads(request.content))
        assert body["prompt_set"] == "default.v6"
        assert body["feature_key"] == "student-1-propertyscope-data-platform"
        assert "model_profile" not in body
        assert release_id in body["objective"]
        assert body["trusted_identifiers"] == [{"kind": "release_id", "value": release_id}]
        assert body["limits"]["time_budget_ms"] == 300000
        assert body["limits"]["max_model_repairs"] == 2
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


def test_assistant_turn_creates_one_read_only_feature_scoped_agent_run() -> None:
    def upstream(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "ai"
        assert request.url.path == "/api/v1/agent-runs"
        body = json.loads(request.content)
        assert body["feature_key"] == "student-1-propertyscope-data-platform"
        assert body["prompt_set"] == "default.v6"
        assert body["limits"]["max_tool_calls"] == 10
        assert "data.run_retry.v1" not in body["tool_allowlist"]
        assert "data.release_publish.v1" not in body["tool_allowlist"]
        assert "property.search.v1" in body["tool_allowlist"]
        assert "What can PropertyScope do?" in body["objective"]
        assert "Earlier answer about releases" in body["objective"]
        assert "browser-supplied, possibly incomplete or altered" in body["objective"]
        assert "platform.capabilities.v1" in body["objective"]
        assert "Do not propose or call a write tool" in body["objective"]
        assert body["trusted_identifiers"] == []
        return httpx.Response(
            202,
            json={"id": "70000000-0000-0000-0000-000000000002", "status": "queued"},
            headers={"X-Agent-Run-ID": "70000000-0000-0000-0000-000000000002"},
        )

    unavailable = httpx.MockTransport(lambda _: httpx.Response(503))
    app = create_backend_app(
        store_client=DataStoreClient(
            "http://database", "secret", client=httpx.Client(transport=unavailable)
        ),
        ai_mode_client=AiModeClient(
            "http://ai", client=httpx.Client(transport=httpx.MockTransport(upstream))
        ),
    )

    response = app.test_client().post(
        "/api/data-platform/v1/assistant/turns",
        json={
            "message": (
                "What can PropertyScope do? release_id: 60000000-0000-0000-0000-000000000099"
            ),
            "scope": "application",
            "history": [
                {"role": "user", "content": "What about releases?"},
                {
                    "role": "assistant",
                    "content": (
                        "Earlier answer about releases run_id: 70000000-0000-0000-0000-000000000099"
                    ),
                },
            ],
        },
    )

    assert response.status_code == 202
    assert response.get_json()["status"] == "queued"
    assert response.headers["X-Agent-Run-ID"].endswith("0002")


@pytest.mark.parametrize(
    ("method", "suffix"),
    [
        ("GET", ""),
        ("GET", "/events"),
        ("POST", "/cancel"),
    ],
)
@pytest.mark.parametrize(
    "run",
    [
        {"feature_key": "student-2-market", "tool_allowlist": []},
        {"feature_key": "student-1-propertyscope-data-platform", "tool_allowlist": None},
    ],
)
def test_assistant_endpoints_hide_foreign_and_non_chat_runs(
    method: str, suffix: str, run: dict[str, object]
) -> None:
    run_id = "70000000-0000-0000-0000-000000000004"
    calls: list[str] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        assert request.method == "GET"
        assert request.url.path == f"/api/v1/agent-runs/{run_id}"
        return httpx.Response(200, json={"run": run, "steps": [], "reviews": []})

    unavailable = httpx.MockTransport(lambda _: httpx.Response(503))
    app = create_backend_app(
        store_client=DataStoreClient(
            "http://database", "secret", client=httpx.Client(transport=unavailable)
        ),
        ai_mode_client=AiModeClient(
            "http://ai", client=httpx.Client(transport=httpx.MockTransport(upstream))
        ),
    )

    response = app.test_client().open(
        f"/api/data-platform/v1/assistant/turns/{run_id}{suffix}", method=method
    )

    assert response.status_code == 404
    assert response.get_json()["code"] == "assistant_turn_not_found"
    assert calls == [f"GET /api/v1/agent-runs/{run_id}"]


def test_assistant_turn_rejects_unknown_context_without_calling_ai_mode() -> None:
    unavailable = httpx.MockTransport(lambda _: httpx.Response(503))
    app = create_backend_app(
        store_client=DataStoreClient(
            "http://database", "secret", client=httpx.Client(transport=unavailable)
        ),
        ai_mode_client=AiModeClient("http://ai", client=httpx.Client(transport=unavailable)),
    )

    response = app.test_client().post(
        "/api/data-platform/v1/assistant/turns",
        json={"message": "Explain this", "context": {"made_up_id": "unsafe"}},
    )

    assert response.status_code == 422
    assert response.get_json()["code"] == "invalid_assistant_turn"


def test_assistant_turn_rejects_noncanonical_context_without_calling_ai_mode() -> None:
    unavailable = httpx.MockTransport(lambda _: httpx.Response(503))
    app = create_backend_app(
        store_client=DataStoreClient(
            "http://database", "secret", client=httpx.Client(transport=unavailable)
        ),
        ai_mode_client=AiModeClient("http://ai", client=httpx.Client(transport=unavailable)),
    )

    response = app.test_client().post(
        "/api/data-platform/v1/assistant/turns",
        json={
            "message": "Explain this",
            "context": {
                "route": "releases/detail",
                "ingestion_run_id": "70000000-0000-0000-0000-000000000004",
            },
        },
    )

    assert response.status_code == 422
    assert response.get_json()["code"] == "invalid_assistant_turn"


def test_assistant_capability_tool_is_the_public_guide_projection() -> None:
    unavailable = httpx.MockTransport(lambda _: httpx.Response(503))
    app = create_backend_app(
        store_client=DataStoreClient(
            "http://database", "secret", client=httpx.Client(transport=unavailable)
        ),
        ai_mode_client=AiModeClient("http://ai", client=httpx.Client(transport=unavailable)),
    )
    client = app.test_client()

    public = client.get("/api/data-platform/v1/assistant/capabilities")
    tool = client.post("/api/data-platform/v1/tools/platform.capabilities.v1", json={})

    assert public.status_code == 200
    assert tool.status_code == 200
    assert tool.get_json() == public.get_json()
    assert tool.get_json()["features"][0]["status"] == "available"


def test_release_list_tool_proxies_bounded_release_evidence() -> None:
    release_id = "60000000-0000-0000-0000-000000000001"

    def database(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/internal/data-platform/v1/releases"
        assert request.url.params["status"] == "candidate"
        assert request.url.params["dataset_id"] == "gnaf-address"
        assert request.url.params["limit"] == "50"
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": release_id,
                        "dataset_id": "gnaf-address",
                        "status": "candidate",
                        "record_count": 5_190_134,
                        "manifest_json": {"geography_coverage": ["large"] * 5_000},
                        "coverage_json": {"localities": ["large"] * 5_000},
                    }
                ],
                "count": 1,
            },
        )

    transport = httpx.MockTransport(database)
    app = create_backend_app(
        store_client=DataStoreClient(
            "http://database", "secret", client=httpx.Client(transport=transport)
        ),
        ai_mode_client=AiModeClient("http://ai", client=httpx.Client(transport=transport)),
    )

    response = app.test_client().post(
        "/api/data-platform/v1/tools/releases.list.v1",
        json={"status": "candidate", "dataset_id": "gnaf-address", "limit": 999},
    )

    assert response.status_code == 200
    item = response.get_json()["items"][0]
    assert item["record_count"] == 5_190_134
    assert "manifest_json" not in item
    assert "coverage_json" not in item


def test_run_list_tool_omits_large_snapshots_and_lease_internals() -> None:
    def database(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/internal/data-platform/v1/runs"
        assert request.url.params["status"] == "succeeded"
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "70000000-0000-0000-0000-000000000001",
                        "source_name": "G-NAF Open NSW",
                        "status": "succeeded",
                        "requested_scope_json": {
                            "profile": "full-data",
                            "all_records": True,
                        },
                        "rows_accepted": 5_190_134,
                        "source_snapshot_json": {"objects": [{"secret": "large"}] * 70},
                        "lease_token": "internal-token",
                    }
                ]
            },
        )

    transport = httpx.MockTransport(database)
    app = create_backend_app(
        store_client=DataStoreClient(
            "http://database", "secret", client=httpx.Client(transport=transport)
        ),
        ai_mode_client=AiModeClient("http://ai", client=httpx.Client(transport=transport)),
    )

    response = app.test_client().post(
        "/api/data-platform/v1/tools/runs.list.v1",
        json={"status": "succeeded"},
    )

    assert response.status_code == 200
    item = response.get_json()["items"][0]
    assert item["rows_accepted"] == 5_190_134
    assert item["requested_scope_json"]["profile"] == "full-data"
    assert "source_snapshot_json" not in item
    assert "lease_token" not in item


def test_run_list_tool_defaults_to_ten_succeeded_runs() -> None:
    def database(request: httpx.Request) -> httpx.Response:
        assert request.url.params["status"] == "succeeded"
        assert request.url.params["limit"] == "10"
        return httpx.Response(200, json={"items": []})

    transport = httpx.MockTransport(database)
    app = create_backend_app(
        store_client=DataStoreClient(
            "http://database", "secret", client=httpx.Client(transport=transport)
        ),
        ai_mode_client=AiModeClient("http://ai", client=httpx.Client(transport=transport)),
    )

    response = app.test_client().post("/api/data-platform/v1/tools/runs.list.v1", json={})

    assert response.status_code == 200
    assert response.get_json() == {"items": [], "count": 0}


def test_property_inspection_tool_returns_bounded_evidence_shape() -> None:
    property_ref = "a0000000-0000-0000-0000-000000000002"

    def database(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/internal/data-platform/v1/properties/{property_ref}"
        return httpx.Response(
            200,
            json={
                "property": {"property_ref": property_ref, "address_display": "12 Example St"},
                "identifiers": [{"scheme": "gnaf_pid"}] * 30,
                "aliases": [{"address": "Alias"}] * 30,
                "coverage": [{"dataset_id": "gnaf-nsw"}] * 30,
            },
        )

    transport = httpx.MockTransport(database)
    app = create_backend_app(
        store_client=DataStoreClient(
            "http://database", "secret", client=httpx.Client(transport=transport)
        ),
        ai_mode_client=AiModeClient("http://ai", client=httpx.Client(transport=transport)),
    )

    response = app.test_client().post(
        "/api/data-platform/v1/tools/properties.inspect.v1",
        json={"property_ref": property_ref},
    )

    assert response.status_code == 200
    assert set(response.get_json()) == {"property", "identifiers", "aliases", "coverage"}
    assert len(response.get_json()["identifiers"]) == 25
    assert len(response.get_json()["aliases"]) == 25
    assert len(response.get_json()["coverage"]) == 25


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
    )
    response = app.test_client().post(
        f"/api/data-platform/v1/jobs/{job_id}/plans",
        json={"run_mode": "full_refresh", "scope": {"profile": "full-data"}},
    )

    assert response.status_code == 200
    assert response.get_json()["network_required"] is True


def test_complete_fixture_plan_does_not_claim_network_work() -> None:
    job_id = "20000000-0000-0000-0000-000000000010"

    def database(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "job": {
                    "id": job_id,
                    "profile_key": "fixture-property-full",
                    "release_builder_key": "property-snapshot",
                    "import_profile_key": "property-fixture",
                }
            },
        )

    transport = httpx.MockTransport(database)
    app = create_backend_app(
        store_client=DataStoreClient(
            "http://database", "secret", client=httpx.Client(transport=transport)
        ),
        ai_mode_client=AiModeClient("http://ai", client=httpx.Client(transport=transport)),
    )

    response = app.test_client().post(
        f"/api/data-platform/v1/jobs/{job_id}/plans",
        json={"run_mode": "full_refresh", "scope": {"profile": "full-data"}},
    )

    assert response.status_code == 200
    assert response.get_json()["network_required"] is False


def test_default_runtime_reports_and_allows_official_acquisition() -> None:
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
    )
    client = app.test_client()

    capabilities = client.get("/api/data-platform/v1/runtime-capabilities")
    plan = client.post(
        f"/api/data-platform/v1/jobs/{job_id}/plans",
        json={"run_mode": "full_refresh", "scope": {"profile": "full-data"}},
    )

    assert "full_data_enabled" not in capabilities.get_json()
    assert "schools-master" in capabilities.get_json()["connected_live_profiles"]
    assert plan.status_code == 200


def test_job_plan_requires_the_complete_psi_history_even_when_one_archive_is_cached() -> None:
    job_id = "20000000-0000-0000-0000-000000000001"

    def database(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "job": {
                    "id": job_id,
                    "adapter_key": "psi-yearly-zip",
                    "import_profile_key": "psi-sales",
                    "scope_json": {"profile": "full-data", "all_records": True},
                }
            },
        )

    transport = httpx.MockTransport(database)
    app = create_backend_app(
        store_client=DataStoreClient(
            "http://database", "secret", client=httpx.Client(transport=transport)
        ),
        ai_mode_client=AiModeClient("http://ai", client=httpx.Client(transport=transport)),
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
    assert response.get_json()["network_required"] is True
    assert response.get_json()["source_cache_required"] is False
    assert capabilities.get_json()["cached_source_years"] == {"psi-sales": [2025]}
    assert capabilities.get_json()["cached_source_weeks"] == {"psi-sales": ["2026-08-10"]}


def test_job_plan_ignores_attempts_to_reduce_the_registered_complete_scope() -> None:
    job_id = "20000000-0000-0000-0000-000000000003"

    def database(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "job": {
                    "id": job_id,
                    "profile_key": "gnaf-nsw-address-registry",
                    "release_builder_key": "property-snapshot",
                    "import_profile_key": "gnaf-nsw",
                    "scope_json": {"profile": "full-data", "all_records": True},
                }
            },
        )

    transport = httpx.MockTransport(database)
    app = create_backend_app(
        store_client=DataStoreClient(
            "http://database", "secret", client=httpx.Client(transport=transport)
        ),
        ai_mode_client=AiModeClient("http://ai", client=httpx.Client(transport=transport)),
    )
    client = app.test_client()

    merged = client.post(
        f"/api/data-platform/v1/jobs/{job_id}/plans",
        json={"run_mode": "full_refresh", "scope": {"profile": "showcase"}},
    )
    overflow = client.post(
        f"/api/data-platform/v1/jobs/{job_id}/plans",
        json={
            "run_mode": "full_refresh",
            "scope": {"profile": "full-data", "maximum_records": 50_001},
        },
    )
    assert merged.status_code == 200
    assert merged.get_json()["scope"]["all_records"] is True
    assert "maximum_records" not in merged.get_json()["scope"]
    assert overflow.status_code == 200
    assert "maximum_records" not in overflow.get_json()["scope"]


def test_retry_of_legacy_partial_run_reacquires_the_complete_registered_source() -> None:
    run_id = "30000000-0000-0000-0000-000000000031"
    job_id = "20000000-0000-0000-0000-000000000004"
    created_body: dict[str, object] = {}

    def database(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith(f"/runs/{run_id}"):
            return httpx.Response(
                200,
                json={
                    "run": {
                        "job_definition_id": job_id,
                        "run_mode": "full_refresh",
                        "requested_scope_json": {"profile": "showcase", "maximum_records": 100},
                    }
                },
            )
        if request.method == "GET" and request.url.path.endswith(f"/jobs/{job_id}"):
            return httpx.Response(
                200,
                json={
                    "job": {
                        "id": job_id,
                        "profile_key": "nsw-government-schools-master",
                        "import_profile_key": "schools-master",
                        "release_builder_key": "school-points",
                    }
                },
            )
        if request.method == "POST" and request.url.path.endswith(f"/jobs/{job_id}/runs"):
            created_body.update(json.loads(request.content))
            return httpx.Response(201, json={"run": {"id": "new-complete-run"}})
        raise AssertionError(f"unexpected store request: {request.method} {request.url.path}")

    transport = httpx.MockTransport(database)
    app = create_backend_app(
        store_client=DataStoreClient(
            "http://database", "secret", client=httpx.Client(transport=transport)
        ),
        ai_mode_client=AiModeClient("http://ai", client=httpx.Client(transport=transport)),
    )

    response = app.test_client().post(
        f"/api/data-platform/v1/ingestion-runs/{run_id}/retry",
        headers={"Idempotency-Key": "retry-complete-001"},
    )

    assert response.status_code == 201
    assert created_body["scope"] == {
        "profile": "full-data",
        "all_records": True,
    }


@pytest.mark.parametrize("action", ["resume", "reprocess-cached"])
def test_legacy_partial_run_cannot_reuse_partial_work(action: str) -> None:
    run_id = "30000000-0000-0000-0000-000000000032"
    job_id = "20000000-0000-0000-0000-000000000004"

    def database(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith(f"/runs/{run_id}"):
            return httpx.Response(
                200,
                json={
                    "run": {
                        "job_definition_id": job_id,
                        "run_mode": "full_refresh",
                        "requested_scope_json": {"profile": "showcase", "maximum_records": 100},
                    }
                },
            )
        if request.method == "GET" and request.url.path.endswith(f"/jobs/{job_id}"):
            return httpx.Response(
                200,
                json={
                    "job": {
                        "id": job_id,
                        "profile_key": "nsw-government-schools-master",
                        "import_profile_key": "schools-master",
                        "release_builder_key": "school-points",
                    }
                },
            )
        raise AssertionError("partial lineage must not be continued in the data store")

    transport = httpx.MockTransport(database)
    app = create_backend_app(
        store_client=DataStoreClient(
            "http://database", "secret", client=httpx.Client(transport=transport)
        ),
        ai_mode_client=AiModeClient("http://ai", client=httpx.Client(transport=transport)),
    )

    response = app.test_client().post(
        f"/api/data-platform/v1/ingestion-runs/{run_id}/{action}",
        headers={"Idempotency-Key": "legacy-lineage-001"},
    )

    assert response.status_code == 409
    assert response.get_json()["code"] == "incomplete_legacy_run"


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
