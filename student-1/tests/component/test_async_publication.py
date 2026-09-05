from __future__ import annotations

import json
import uuid
from pathlib import Path
from threading import Event
from typing import Any, cast

import httpx
import pytest
from flask import Flask

from propertyscope_data_platform.app import create_app
from propertyscope_data_platform.clients import (
    AiModeClient,
    ConsumerEndpoint,
    ConsumerImportClient,
    DataStoreClient,
)
from propertyscope_data_platform.domain import ConsumerPublicationRequest
from propertyscope_data_platform.release_projection import public_activation
from propertyscope_data_platform.release_publication import process_consumer_import, publish_release
from propertyscope_data_platform.runner import AcquisitionRunner, RunnerSettings

RELEASE_ID = "60000000-0000-0000-0000-000000000099"
OPERATION_ID = "72000000-0000-0000-0000-000000000099"
DIGEST = "a" * 64


def test_public_activation_reports_preparation_phase_without_worker_credentials() -> None:
    projected = public_activation(
        {
            "status": "running",
            "progress_phase_key": "materialisation",
            "progress_phase": "Materialising reviewed release",
            "progress_updated_at": "now",
            "lease_token": "private-token",
        }
    )
    assert projected["progress_phase"] == "Materialising reviewed release"
    assert projected["progress_updated_at"] == "now"
    assert "lease_token" not in projected


class _OversizedChunkedBody(httpx.SyncByteStream):
    def __iter__(self) -> Any:
        yield b"x" * (ConsumerImportClient.MAX_RESPONSE_BYTES // 2)
        yield b"x" * (ConsumerImportClient.MAX_RESPONSE_BYTES // 2 + 1)


class _CompressedBody(httpx.SyncByteStream):
    def __iter__(self) -> Any:
        yield b"compressed-control-plane-body"


def _publication() -> ConsumerPublicationRequest:
    return ConsumerPublicationRequest(
        release_id=RELEASE_ID,
        dataset_id="bocsar-crime",
        schema_version="crime-series.v1",
        content_sha256=DIGEST,
        record_count=3,
        manifest={"target_feature": "feature-3"},
        artifact_path=f"/api/data-platform/v1/dataset-releases/{RELEASE_ID}/artifact",
        idempotency_key="delivery-request-99",
    )


def _operation(phase: str, **overrides: Any) -> dict[str, Any]:
    operation = {
        "id": OPERATION_ID,
        "dataset_release_id": RELEASE_ID,
        "dataset_id": "bocsar-crime",
        "target_feature": "feature-3",
        "schema_version": "crime-series.v1",
        "content_sha256": DIGEST,
        "record_count": 3,
        "manifest_json": {"target_feature": "feature-3"},
        "artifact_path": f"/api/data-platform/v1/dataset-releases/{RELEASE_ID}/artifact",
        "idempotency_key": "delivery-request-99",
        "expected_release_version": 2,
        "review_comment": "Reviewed",
        "request_id": "request-99",
        "status": "claimed",
        "phase_key": phase,
        "lease_owner": "runner-1",
        "lease_token": "lease-99",
    }
    operation.update(overrides)
    return operation


def _async_ack(status: str = "queued") -> dict[str, Any]:
    return {
        "consumer_operation_id": "consumer-owned-42",
        "status": status,
        "release_id": RELEASE_ID,
        "dataset_id": "bocsar-crime",
        "target_feature": "feature-3",
        "schema_version": "crime-series.v1",
        "content_sha256": DIGEST,
        "record_count": 3,
    }


def test_tool_publication_uses_closed_catalog_for_async_queue_and_replay_failure() -> None:
    release = {
        "id": RELEASE_ID,
        "dataset_id": "bocsar-crime",
        "target_feature": "feature-3",
        "schema_version": "crime-series.v1",
        "content_sha256": DIGEST,
        "record_count": 3,
        "manifest_json": {"target_feature": "feature-3"},
        "status": "awaiting_review",
        "version": 2,
    }
    operation = _operation("connect", status="queued", publication_receipt_id=None)

    def queued_database(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200,
                json={"release": release, "receipts": [], "consumer_imports": []},
            )
        return httpx.Response(202, json={"operation": operation, "created": True})

    app = Flask("tool-publication-catalog-test")
    with app.test_request_context(headers={"X-Request-ID": "tool-request"}):
        queued = publish_release(
            DataStoreClient(
                "http://database",
                "secret",
                client=httpx.Client(transport=httpx.MockTransport(queued_database)),
            ),
            ConsumerImportClient({}),
            uuid.UUID(RELEASE_ID),
            {"comment": "Approved tool publication"},
            "tool-delivery-key",
            tool_output=True,
        )

    assert queued.status_code == 202
    assert queued.get_json() == {"status": "pending", "receipt_id": None, "replayed": False}

    failed = {
        **operation,
        "status": "failed",
        "phase_key": "complete",
        "publication_receipt_id": "71000000-0000-0000-0000-000000000099",
    }

    def failed_database(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200,
                json={"release": release, "receipts": [], "consumer_imports": [failed]},
            )
        return httpx.Response(200, json={"operation": failed, "created": False})

    with app.test_request_context(headers={"X-Request-ID": "tool-replay"}):
        replay = publish_release(
            DataStoreClient(
                "http://database",
                "secret",
                client=httpx.Client(transport=httpx.MockTransport(failed_database)),
            ),
            ConsumerImportClient({}),
            uuid.UUID(RELEASE_ID),
            {"comment": "Approved tool publication"},
            "fresh-tool-key",
            tool_output=True,
        )

    assert replay.status_code == 424
    assert replay.get_json() == {
        "status": "failed",
        "receipt_id": "71000000-0000-0000-0000-000000000099",
        "replayed": True,
    }


def test_web_accepted_receipt_replay_includes_completed_publication_status() -> None:
    receipt_id = "71000000-0000-0000-0000-000000000099"
    release = {
        "id": RELEASE_ID,
        "dataset_id": "bocsar-crime",
        "target_feature": "feature-3",
        "schema_version": "crime-series.v1",
        "content_sha256": DIGEST,
        "record_count": 3,
        "manifest_json": {"target_feature": "feature-3"},
        "status": "accepted",
        "version": 3,
    }
    receipt = {
        "id": receipt_id,
        "consumer_operation_id": "consumer-owned-42",
        "status": "accepted",
        "schema_version": "crime-series.v1",
        "content_sha256": DIGEST,
        "rows_received": 3,
        "rows_accepted": 3,
        "rows_rejected": 0,
    }
    store = DataStoreClient(
        "http://database",
        "secret",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    json={"release": release, "receipts": [receipt], "consumer_imports": []},
                )
            )
        ),
    )
    app = Flask("accepted-web-replay-test")
    with app.test_request_context():
        response = publish_release(
            store,
            ConsumerImportClient({}),
            uuid.UUID(RELEASE_ID),
            {},
            "fresh-web-key",
        )

    assert response.status_code == 200
    assert response.get_json()["publication_status"] == "completed"
    assert response.get_json()["receipt"]["consumer_operation_id"] == "consumer-owned-42"


def test_partial_psi_candidate_cannot_replace_the_complete_accepted_generation() -> None:
    release = {
        "id": RELEASE_ID,
        "dataset_id": "nsw-psi-sales",
        "target_feature": "feature-2",
        "schema_version": "propertyscope.property-sales.v3",
        "content_sha256": DIGEST,
        "record_count": 3,
        "coverage_json": {
            "profile": "psi-year-range",
            "start_year": 2023,
            "end_year": 2024,
            "complete": False,
        },
        "manifest_json": {"target_feature": "feature-2"},
        "status": "awaiting_review",
        "version": 2,
    }
    requested_methods: list[str] = []

    def database(request: httpx.Request) -> httpx.Response:
        requested_methods.append(request.method)
        return httpx.Response(
            200,
            json={"release": release, "receipts": [], "consumer_imports": []},
        )

    app = Flask("partial-publication-test")
    with app.test_request_context():
        response = publish_release(
            DataStoreClient(
                "http://database",
                "secret",
                client=httpx.Client(transport=httpx.MockTransport(database)),
            ),
            ConsumerImportClient({}),
            uuid.UUID(RELEASE_ID),
            {"comment": "Reviewed"},
            "partial-publication-key",
        )

    assert response.status_code == 409
    assert response.get_json()["code"] == "partial_release_not_publishable"
    assert requested_methods == ["GET"]


def test_connect_retains_genuine_async_operation_reference_with_short_timeout() -> None:
    def consumer(request: httpx.Request) -> httpx.Response:
        assert request.extensions["timeout"]["connect"] == 5.0
        assert request.headers["Idempotency-Key"] == "delivery-request-99"
        return httpx.Response(202, json={"operation": _async_ack()})

    client = ConsumerImportClient(
        {"feature-3": ConsumerEndpoint("http://feature-3", "/api/imports")},
        client=httpx.Client(transport=httpx.MockTransport(consumer)),
    )

    outcome = client.connect("feature-3", _publication(), {})

    assert outcome.status == "queued"
    assert outcome.consumer_operation_id == "consumer-owned-42"
    assert outcome.receipt is None


def test_legacy_final_receipt_preserves_consumer_id_instead_of_delivery_key() -> None:
    response = httpx.Response(
        200,
        json={
            "consumer_operation_id": "legacy-consumer-314",
            "status": "accepted",
            "schema_version": "crime-series.v1",
            "content_sha256": DIGEST,
            "rows_received": 3,
            "rows_accepted": 3,
            "rows_rejected": 0,
            "error": None,
        },
    )
    client = ConsumerImportClient(
        {"feature-3": ConsumerEndpoint("http://feature-3", "/api/imports")},
        client=httpx.Client(transport=httpx.MockTransport(lambda _: response)),
    )

    outcome = client.connect("feature-3", _publication(), {})

    assert outcome.consumer_operation_id == "legacy-consumer-314"
    assert outcome.consumer_operation_id != _publication().idempotency_key
    assert outcome.receipt is not None and outcome.receipt.status == "accepted"


def test_shared_helper_flattened_receipt_preserves_full_identity_validation() -> None:
    response = httpx.Response(
        200,
        json={
            "consumer_operation_id": "shared-helper-42",
            "status": "accepted",
            "release_id": RELEASE_ID,
            "dataset_id": "bocsar-crime",
            "target": "feature-3",
            "schema_version": "crime-series.v1",
            "content_sha256": DIGEST,
            "record_count": 3,
            "rows_received": 3,
            "rows_accepted": 3,
            "rows_rejected": 0,
            "error": None,
        },
    )
    client = ConsumerImportClient(
        {"feature-3": ConsumerEndpoint("http://feature-3", "/api/imports")},
        client=httpx.Client(transport=httpx.MockTransport(lambda _: response)),
    )

    outcome = client.connect("feature-3", _publication(), {})

    assert outcome.consumer_operation_id == "shared-helper-42"
    assert outcome.receipt is not None and outcome.receipt.rows_accepted == 3


def test_connect_and_poll_bound_chunked_responses_before_json_parsing() -> None:
    client = ConsumerImportClient(
        {"feature-3": ConsumerEndpoint("http://feature-3", "/api/imports")},
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    headers={"Transfer-Encoding": "chunked"},
                    stream=_OversizedChunkedBody(),
                )
            )
        ),
    )

    connect = client.connect("feature-3", _publication(), {})
    poll = client.poll("feature-3", "consumer-owned-42", _publication(), {})

    assert connect.consumer_operation_id is None
    assert connect.error is not None and connect.error.code == "consumer_response_too_large"
    assert poll.consumer_operation_id is None
    assert poll.error is not None and poll.error.code == "consumer_response_too_large"


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
@pytest.mark.parametrize("body", [b"upstream unavailable", b'{"error":"unavailable"}'])
def test_consumer_control_outage_is_retryable(status: int, body: bytes) -> None:
    client = ConsumerImportClient(
        {"feature-3": ConsumerEndpoint("http://feature-3", "/api/imports")},
        client=httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(status, content=body))
        ),
    )
    for outcome in (
        client.connect("feature-3", _publication(), {}),
        client.poll("feature-3", "consumer-owned-42", _publication(), {}),
    ):
        assert outcome.receipt is None
        assert outcome.error is not None and outcome.error.retryable


def test_connect_rejects_negative_content_length_before_body_read() -> None:
    client = ConsumerImportClient(
        {"feature-3": ConsumerEndpoint("http://feature-3", "/api/imports")},
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    headers={"Content-Length": "-1"},
                    stream=_OversizedChunkedBody(),
                )
            )
        ),
    )

    outcome = client.connect("feature-3", _publication(), {})

    assert outcome.consumer_operation_id is None
    assert outcome.error is not None and outcome.error.code == "consumer_response_invalid"


def test_connect_requests_identity_encoding_and_rejects_compressed_control_body() -> None:
    def consumer(request: httpx.Request) -> httpx.Response:
        assert request.headers["Accept-Encoding"] == "identity"
        return httpx.Response(
            200,
            headers={"Content-Encoding": "gzip"},
            stream=_CompressedBody(),
        )

    client = ConsumerImportClient(
        {"feature-3": ConsumerEndpoint("http://feature-3", "/api/imports")},
        client=httpx.Client(transport=httpx.MockTransport(consumer)),
    )

    outcome = client.connect("feature-3", _publication(), {})

    assert outcome.consumer_operation_id is None
    assert outcome.error is not None
    assert outcome.error.code == "consumer_response_encoding_rejected"


def test_worker_persists_ack_before_any_poll_receipt_or_activation() -> None:
    events: list[str] = []

    def database(request: httpx.Request) -> httpx.Response:
        events.append(request.url.path.rsplit("/", maxsplit=1)[-1])
        assert request.url.path.endswith("/acknowledge")
        body = cast(dict[str, Any], json.loads(request.content))
        assert body["consumer_operation_id"] == "consumer-owned-42"
        assert body["remote_status"] == "queued"
        assert body["result"] is None
        return httpx.Response(
            200,
            json={
                "operation": _operation(
                    "poll", status="polling", consumer_operation_id="consumer-owned-42"
                )
            },
        )

    def consumer(_: httpx.Request) -> httpx.Response:
        events.append("consumer-connect")
        return httpx.Response(202, json={"operation": _async_ack()})

    store = DataStoreClient(
        "http://database",
        "secret",
        client=httpx.Client(transport=httpx.MockTransport(database)),
    )
    consumers = ConsumerImportClient(
        {"feature-3": ConsumerEndpoint("http://feature-3", "/api/imports")},
        client=httpx.Client(transport=httpx.MockTransport(consumer)),
    )
    app = Flask("async-publication-test")
    with app.test_request_context(headers={"X-Request-ID": "request-99"}):
        response = process_consumer_import(
            store,
            consumers,
            _operation("connect"),
            worker_id="runner-1",
            lease_token="lease-99",
        )

    assert response.status_code == 200
    assert events == ["consumer-connect", "acknowledge"]


def test_receipt_phase_is_durable_before_activation_phase() -> None:
    events: list[str] = []
    result = {
        "consumer_operation_id": "consumer-owned-42",
        "status": "accepted",
        "schema_version": "crime-series.v1",
        "content_sha256": DIGEST,
        "rows_received": 3,
        "rows_accepted": 3,
        "rows_rejected": 0,
        "error": None,
    }

    def database(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/receipts"):
            events.append("receipt-commit")
            return httpx.Response(
                201,
                json={
                    "receipt": {
                        "id": "71000000-0000-0000-0000-000000000099",
                        "target_feature": "feature-3",
                        **result,
                    },
                    "created": True,
                },
            )
        assert request.url.path.endswith("/receipt")
        events.append("operation-link")
        return httpx.Response(
            200,
            json={"operation": _operation("queue_activation", status="activation_pending")},
        )

    store = DataStoreClient(
        "http://database",
        "secret",
        client=httpx.Client(transport=httpx.MockTransport(database)),
    )
    app = Flask("receipt-phase-test")
    with app.test_request_context():
        response = process_consumer_import(
            store,
            ConsumerImportClient({}),
            _operation("record_receipt", result_json=result),
            worker_id="runner-1",
            lease_token="lease-99",
        )

    assert response.status_code == 200
    assert events == ["receipt-commit", "operation-link"]


def test_activation_retry_uses_durable_attempt_identity() -> None:
    activation_id = "70000000-0000-0000-0000-000000000099"
    requests: list[str] = []

    def database(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path.endswith("/activations"):
            body = cast(dict[str, Any], json.loads(request.content))
            assert body["idempotency_key"] == (f"consumer-import:{OPERATION_ID}:activation:2")
            return httpx.Response(
                202,
                json={"activation": {"id": activation_id, "status": "queued"}},
            )
        assert request.url.path.endswith("/activation")
        return httpx.Response(
            200,
            json={"operation": _operation("wait_activation", status="activation_queued")},
        )

    store = DataStoreClient(
        "http://database",
        "secret",
        client=httpx.Client(transport=httpx.MockTransport(database)),
    )
    app = Flask("activation-attempt-test")
    with app.test_request_context():
        response = process_consumer_import(
            store,
            ConsumerImportClient({}),
            _operation(
                "queue_activation",
                activation_attempt=2,
                publication_receipt_id="71000000-0000-0000-0000-000000000099",
            ),
            worker_id="runner-1",
            lease_token="lease-99",
        )

    assert response.status_code == 200
    assert requests == [
        f"/internal/data-platform/v1/releases/{RELEASE_ID}/activations",
        f"/internal/data-platform/v1/consumer-imports/{OPERATION_ID}/activation",
    ]


def test_public_status_distinguishes_activation_queue_from_pointer_completion() -> None:
    operation = _operation(
        "complete",
        status="activation_queued",
        release_activation_id="70000000-0000-0000-0000-000000000099",
        lease_owner=None,
        lease_token=None,
    )

    def database(request: httpx.Request) -> httpx.Response:
        if "/consumer-imports/" in request.url.path:
            return httpx.Response(200, json={"operation": operation})
        return httpx.Response(
            200,
            json={
                "activation": {
                    "id": operation["release_activation_id"],
                    "status": "succeeded",
                    "attempt_number": 1,
                }
            },
        )

    transport = httpx.MockTransport(database)
    app = create_app(
        store_client=DataStoreClient(
            "http://database", "secret", client=httpx.Client(transport=transport)
        ),
        ai_mode_client=AiModeClient(
            "http://ai",
            client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503))),
        ),
    )
    response = app.test_client().get(
        f"/api/data-platform/v1/dataset-releases/{RELEASE_ID}/consumer-imports/{OPERATION_ID}"
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["consumer_import"]["status"] == "activation_queued"
    assert body["publication_status"] == "completed"
    assert body["activation"]["status"] == "succeeded"
    assert "lease_token" not in body["consumer_import"]


def test_public_status_reports_terminal_consumer_rejection_without_activation() -> None:
    operation = _operation(
        "complete",
        status="rejected",
        release_activation_id=None,
        lease_owner=None,
        lease_token=None,
    )
    app = create_app(
        store_client=DataStoreClient(
            "http://database",
            "secret",
            client=httpx.Client(
                transport=httpx.MockTransport(
                    lambda _: httpx.Response(200, json={"operation": operation})
                )
            ),
        ),
        ai_mode_client=AiModeClient(
            "http://ai",
            client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503))),
        ),
    )

    response = app.test_client().get(
        f"/api/data-platform/v1/dataset-releases/{RELEASE_ID}/consumer-imports/{OPERATION_ID}"
    )

    assert response.status_code == 200
    assert response.get_json()["publication_status"] == "failed"
    assert response.get_json()["activation"] is None


def test_worker_marks_delivery_published_only_after_activation_succeeds() -> None:
    events: list[str] = []
    activation_id = "70000000-0000-0000-0000-000000000099"

    def database(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            events.append("activation-status-read")
            return httpx.Response(
                200,
                json={"activation": {"id": activation_id, "status": "succeeded"}},
            )
        assert request.url.path.endswith("/activation-status")
        events.append("delivery-outcome-commit")
        body = cast(dict[str, Any], json.loads(request.content))
        assert body["activation_status"] == "succeeded"
        return httpx.Response(
            200,
            json={"operation": _operation("complete", status="published")},
        )

    store = DataStoreClient(
        "http://database",
        "secret",
        client=httpx.Client(transport=httpx.MockTransport(database)),
    )
    app = Flask("activation-monitor-test")
    with app.test_request_context():
        response = process_consumer_import(
            store,
            ConsumerImportClient({}),
            _operation(
                "wait_activation",
                status="claimed",
                release_activation_id=activation_id,
            ),
            worker_id="runner-1",
            lease_token="lease-99",
        )

    assert response.status_code == 200
    assert events == ["activation-status-read", "delivery-outcome-commit"]


def test_runner_advances_one_delivery_phase_when_no_ingestion_task(tmp_path: Path) -> None:
    paths: list[str] = []

    def backend(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("/worker/tasks/claim"):
            return httpx.Response(200, json={"task": None})
        if request.url.path.endswith("/worker/consumer-imports/claim"):
            return httpx.Response(
                200,
                json={
                    "operation": {
                        "id": OPERATION_ID,
                        "lease_token": "lease-99",
                        "status": "claimed",
                    }
                },
            )
        assert request.url.path.endswith(f"/worker/consumer-imports/{OPERATION_ID}/step")
        return httpx.Response(200, json={"operation": {"id": OPERATION_ID, "status": "polling"}})

    runner = AcquisitionRunner(
        RunnerSettings(
            backend_url="http://backend",
            token="runner-token",
            artifact_root=tmp_path,
            worker_id="runner-1",
            poll_seconds=0.01,
            lease_seconds=30,
        ),
        client=httpx.Client(transport=httpx.MockTransport(backend)),
    )

    assert runner.run_once() is True
    assert paths == [
        "/internal/data-platform/v1/worker/tasks/claim",
        "/internal/data-platform/v1/worker/consumer-imports/claim",
        f"/internal/data-platform/v1/worker/consumer-imports/{OPERATION_ID}/step",
    ]


def test_publication_advances_while_acquisition_is_blocked(tmp_path: Path) -> None:
    acquiring, delivered = Event(), Event()

    def backend(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/worker/tasks/claim"):
            return httpx.Response(200, json={"task": {"id": "task", "lease_token": "lease"}})
        if request.url.path.endswith("/worker/consumer-imports/claim"):
            assert acquiring.wait(2)
            return httpx.Response(
                200, json={"operation": {"id": OPERATION_ID, "lease_token": "lease"}}
            )
        if request.url.path.endswith("/step"):
            delivered.set()
        return httpx.Response(200, json={})

    runner = AcquisitionRunner(
        RunnerSettings(
            backend_url="http://backend",
            token="token",
            artifact_root=tmp_path,
            worker_id="runner",
            poll_seconds=0.01,
            lease_seconds=30,
        ),
        client=httpx.Client(transport=httpx.MockTransport(backend)),
    )

    def acquire(task: dict[str, Any]) -> tuple[int, int]:
        acquiring.set()
        progressed = delivered.wait(2)
        runner.stop()
        assert progressed, "publication starved behind ingestion"
        return 1, 1

    runner._execute = acquire  # type: ignore[method-assign]
    runner.run_forever()
    assert delivered.is_set()


def test_failed_delivery_projects_retained_receipt_error() -> None:
    from propertyscope_data_platform.release_projection import public_consumer_import

    error = {
        "code": "artifact_transport_failed",
        "message": "Download interrupted",
        "retryable": True,
    }
    projected = public_consumer_import(
        _operation("complete", status="failed", result_json={"error": error})
    )
    assert projected["error_json"] == error
    assert "lease_token" not in projected


@pytest.mark.parametrize(
    ("activation_status", "expected_status"), [("queued", 202), ("failed", 424)]
)
def test_local_activation_retry_uses_browser_attempt_key(
    activation_status: str, expected_status: int
) -> None:
    release = {
        "id": RELEASE_ID,
        "dataset_id": "gnaf-nsw",
        "target_feature": "feature-1",
        "schema_version": "property.v2",
        "content_sha256": DIGEST,
        "record_count": 5190134,
        "status": "awaiting_review",
        "version": 2,
    }
    receipt = {
        "id": "receipt",
        "consumer_operation_id": "stable-local-verification",
        "status": "accepted",
        "schema_version": "property.v2",
        "content_sha256": DIGEST,
        "rows_received": 5190134,
        "rows_accepted": 5190134,
        "rows_rejected": 0,
    }

    def database(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"release": release, "receipts": [receipt]})
        assert request.url.path.endswith("/activations")
        assert json.loads(request.content)["idempotency_key"] == "new-browser-attempt"
        return httpx.Response(
            202, json={"activation": {"id": "activation", "status": activation_status}}
        )

    store = DataStoreClient(
        "http://database", "token", client=httpx.Client(transport=httpx.MockTransport(database))
    )
    with Flask("local-retry").test_request_context():
        response = publish_release(
            store,
            ConsumerImportClient({}),
            uuid.UUID(RELEASE_ID),
            {"version": 2, "comment": "Retry activation"},
            "new-browser-attempt",
        )
    assert response.status_code == expected_status
    assert response.get_json()["publication_status"] == (
        "pending" if expected_status == 202 else "failed"
    )
