from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from typing import Any, cast

import httpx
import pytest
from flask import Flask, jsonify
from flask.testing import FlaskClient

from propertyscope_data_platform.app import create_app as create_backend_app
from propertyscope_data_platform.clients import AiModeClient, DataStoreClient
from propertyscope_data_platform.http_support import (
    forward,
    forward_json_bytes,
    json_body,
    register_error_handlers,
    tool_envelope,
)
from propertyscope_data_store.api import create_blueprint as create_store_blueprint
from propertyscope_data_store.api import register_error_handlers as register_store_error_handlers
from propertyscope_data_store.repository import PropertyScopeStore


def _json_boundary_client() -> FlaskClient:
    app = Flask(__name__)

    @app.post("/required")
    def required() -> Any:
        return jsonify(json_body())

    @app.post("/optional")
    def optional() -> Any:
        return jsonify(json_body(optional=True))

    register_error_handlers(app)
    return app.test_client()


@pytest.mark.parametrize(
    ("path", "data", "content_type"),
    [
        ("/required", b"", "application/json"),
        ("/required", b"{not-json", "application/json"),
        ("/required", b"[]", "application/json"),
        ("/required", b'"text"', "application/json"),
        ("/required", b'{"valid":true}', "text/plain"),
        ("/optional", b"{not-json", "application/json"),
    ],
)
def test_json_body_rejects_absent_required_or_non_object_payloads(
    path: str, data: bytes, content_type: str
) -> None:
    response = _json_boundary_client().post(path, data=data, content_type=content_type)

    assert response.status_code == 422
    assert response.content_type == "application/problem+json"
    assert response.get_json()["detail"] == "request body must be a JSON object"


def test_json_body_allows_only_a_truly_absent_optional_payload() -> None:
    client = _json_boundary_client()

    assert client.post("/optional").get_json() == {}
    assert client.post("/required", json={"valid": True}).get_json() == {"valid": True}


@pytest.mark.parametrize("status", [200, 201, 502, 503])
@pytest.mark.parametrize("body", [b"<html>private upstream error</html>", b"", b"null", b"[]"])
def test_proxy_never_turns_broken_dependency_json_into_success_or_caller_error(
    status: int,
    body: bytes,
) -> None:
    app = Flask(__name__)
    app.add_url_rule("/proxy", view_func=lambda: forward(httpx.Response(status, content=body)))
    register_error_handlers(app)
    response = app.test_client().get("/proxy", headers={"X-Request-ID": "boundary-test"})
    assert response.status_code == 503
    assert response.content_type == "application/problem+json"
    assert response.get_json()["code"] == "dependency_unavailable"
    assert response.get_json()["request_id"] == "boundary-test"
    assert "private upstream error" not in response.get_data(as_text=True)


def test_proxy_preserves_problem_details_and_no_content_responses() -> None:
    app = Flask(__name__)
    with app.test_request_context():
        payload = {"code": "version_conflict", "detail": "Reload before saving"}
        result = forward(
            httpx.Response(
                409,
                json=payload,
                headers={
                    "Content-Type": "application/problem+json",
                    "X-Request-ID": "upstream-id",
                },
            )
        )
        assert result.status_code == 409
        assert result.get_json() == payload
        assert result.content_type == "application/problem+json"
        assert result.headers["X-Request-ID"] == "upstream-id"
        empty = forward(httpx.Response(204, headers={"X-Request-ID": "delete-id"}))
        assert empty.status_code == 204
        assert empty.get_data() == b""
        assert empty.headers["X-Request-ID"] == "delete-id"


@pytest.mark.parametrize("adapter", [forward, forward_json_bytes, tool_envelope])
def test_response_adapters_reject_html_dependency_failures(adapter: Any) -> None:
    app = Flask(__name__)
    app.add_url_rule(
        "/proxy",
        view_func=lambda: adapter(
            httpx.Response(
                200,
                content=b"<html>private</html>",
                headers={"Content-Type": "text/html"},
            )
        ),
    )
    register_error_handlers(app)
    response = app.test_client().get("/proxy")
    assert response.status_code == 503
    assert response.get_json()["code"] == "dependency_unavailable"


def test_proxy_rejects_redirects_and_preserves_large_json_page_bytes() -> None:
    app = Flask(__name__)
    app.add_url_rule(
        "/proxy",
        view_func=lambda: forward_json_bytes(
            httpx.Response(
                302,
                headers={"Location": "http://unexpected/private"},
            )
        ),
    )
    register_error_handlers(app)
    assert app.test_client().get("/proxy").status_code == 503
    with app.test_request_context():
        original = b'{ "items": [1,2,3] }'
        result = forward_json_bytes(
            httpx.Response(
                200,
                content=original,
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "X-Request-ID": "page-id",
                },
            )
        )
        assert result.get_data() == original
        assert result.headers["X-Request-ID"] == "page-id"


def test_oversized_request_has_a_structured_problem() -> None:
    client = _json_boundary_client()
    client.application.config["MAX_CONTENT_LENGTH"] = 8
    response = client.post("/required", json={"value": "too much input"})
    assert response.status_code == 413
    assert response.content_type == "application/problem+json"
    assert response.get_json()["code"] == "request_too_large"


def _source_payload() -> dict[str, Any]:
    return {
        "name": "NSW example source",
        "publisher": "Example publisher",
        "source_url": "https://example.com/source",
        "adapter_key": "fixture-snapshot",
        "cadence": "monthly",
        "licence_id": "example-licence",
        "licence_url": "https://example.com/licence",
        "redistribution_policy": "metadata-only",
        "target_features": ["feature-1"],
    }


def _source_client(requests: list[httpx.Request]) -> FlaskClient:
    def database(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = cast(dict[str, Any], json.loads(request.content))
        status = 201 if request.method == "POST" else 200
        return httpx.Response(status, json={"source": {"id": str(uuid.uuid4()), **body}})

    transport = httpx.MockTransport(database)
    app = create_backend_app(
        store_client=DataStoreClient(
            "http://database",
            "secret",
            client=httpx.Client(transport=transport),
        ),
        ai_mode_client=AiModeClient(
            "http://ai",
            client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503))),
        ),
    )
    return app.test_client()


def test_source_create_validates_and_normalises_before_forwarding() -> None:
    requests: list[httpx.Request] = []

    response = _source_client(requests).post(
        "/api/data-platform/v1/sources", json=_source_payload()
    )

    assert response.status_code == 201
    forwarded = cast(dict[str, Any], json.loads(requests[0].content))
    assert forwarded["status"] == "draft"
    assert forwarded["notes"] == ""


def test_source_update_validates_before_forwarding() -> None:
    requests: list[httpx.Request] = []
    source_id = uuid.uuid4()

    response = _source_client(requests).put(
        f"/api/data-platform/v1/sources/{source_id}",
        json={**_source_payload(), "version": 3},
    )

    assert response.status_code == 200
    assert requests[0].url.path.endswith(f"/sources/{source_id}")
    assert cast(dict[str, Any], json.loads(requests[0].content))["version"] == 3


@pytest.mark.parametrize("operation", ["create_extra", "create_missing", "update"])
def test_invalid_source_dto_is_not_forwarded(operation: str) -> None:
    requests: list[httpx.Request] = []
    client = _source_client(requests)
    body = _source_payload()
    if operation == "create_extra":
        body["unexpected"] = "not allowed"
        response = client.post("/api/data-platform/v1/sources", json=body)
    elif operation == "create_missing":
        del body["target_features"]
        response = client.post("/api/data-platform/v1/sources", json=body)
    else:
        response = client.put(
            f"/api/data-platform/v1/sources/{uuid.uuid4()}",
            json=body,
        )

    assert response.status_code == 422
    assert response.content_type == "application/problem+json"
    assert requests == []


class StrictScalarStore:
    def __init__(self) -> None:
        self.failures: list[dict[str, Any]] = []
        self.finishes: list[dict[str, Any]] = []

    def fail_task(
        self,
        task_id: uuid.UUID,
        *,
        worker_id: str,
        lease_token: str,
        error: Mapping[str, Any],
        retryable: bool,
    ) -> dict[str, Any]:
        values = {
            "task_id": str(task_id),
            "worker_id": worker_id,
            "lease_token": lease_token,
            "error": dict(error),
            "retryable": retryable,
        }
        self.failures.append(values)
        return {"status": "failed", **values}

    def finish_import(
        self,
        operation_id: uuid.UUID,
        *,
        worker_id: str,
        lease_token: str,
        status: str,
        counts: Mapping[str, int],
        result: Mapping[str, Any] | None,
        error: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        values = {
            "operation_id": str(operation_id),
            "worker_id": worker_id,
            "lease_token": lease_token,
            "status": status,
            "counts": dict(counts),
            "result": dict(result) if result is not None else None,
            "error": dict(error) if error is not None else None,
        }
        self.finishes.append(values)
        return values


def _store_client(store: StrictScalarStore) -> FlaskClient:
    app = Flask(__name__)
    app.register_blueprint(
        create_store_blueprint(cast(PropertyScopeStore, store), internal_token="secret")
    )
    register_store_error_handlers(app)
    return app.test_client()


def _internal_headers() -> dict[str, str]:
    return {"X-PropertyScope-Internal-Token": "secret"}


def test_private_export_negotiates_compact_pages_without_changing_legacy_clients() -> None:
    class ExportStore(StrictScalarStore):
        def release_product_records(self, release_id: uuid.UUID, **kwargs: Any) -> dict[str, Any]:
            assert kwargs == {"limit": 20000, "cursor": None}
            return {
                "release_id": str(release_id),
                "candidate_generation_id": str(release_id),
                "items": [{"id": "one", "value": None}],
                "total": 1,
                "next_cursor": None,
            }

    client = _store_client(ExportStore())
    path = f"/internal/data-platform/v1/releases/{uuid.uuid4()}/product-records"
    original = client.get(path, headers=_internal_headers())
    packed = client.get(path + "?layout=columns", headers=_internal_headers())
    invalid = client.get(path + "?layout=unknown", headers=_internal_headers())
    assert original.status_code == packed.status_code == 200
    assert original.get_json()["items"] == [{"id": "one", "value": None}]
    assert packed.get_json()["columns"] == ["id", "value"]
    assert packed.get_json()["rows"] == [["one", None]]
    assert "items" not in packed.get_json()
    assert invalid.status_code == 422


def test_history_job_filter_rejects_invalid_uuid_before_querying() -> None:
    class HistoryStore(StrictScalarStore):
        def list_runs(self, **kwargs: Any) -> list[dict[str, Any]]:
            raise AssertionError("invalid filters must not reach persistence")

    response = _store_client(HistoryStore()).get(
        "/internal/data-platform/v1/runs?job_definition_id=not-a-uuid", headers=_internal_headers()
    )
    assert response.status_code == 422


@pytest.mark.parametrize("retryable", ["false", 0, 1, None])
def test_task_failure_rejects_non_boolean_retryable(retryable: object) -> None:
    store = StrictScalarStore()

    response = _store_client(store).post(
        f"/internal/data-platform/v1/worker/tasks/{uuid.uuid4()}/fail",
        headers=_internal_headers(),
        json={
            "worker_id": "runner-1",
            "lease_token": "lease-1",
            "error": {},
            "retryable": retryable,
        },
    )

    assert response.status_code == 422
    assert response.get_json()["detail"] == "retryable must be a boolean"
    assert store.failures == []


def test_task_failure_preserves_a_false_retryable_value() -> None:
    store = StrictScalarStore()

    response = _store_client(store).post(
        f"/internal/data-platform/v1/worker/tasks/{uuid.uuid4()}/fail",
        headers=_internal_headers(),
        json={
            "worker_id": "runner-1",
            "lease_token": "lease-1",
            "error": {},
            "retryable": False,
        },
    )

    assert response.status_code == 200
    assert store.failures[0]["retryable"] is False


@pytest.mark.parametrize("invalid_count", ["1", True, -1, 1.5])
def test_import_finish_rejects_non_integer_or_negative_counts(invalid_count: object) -> None:
    store = StrictScalarStore()

    response = _store_client(store).post(
        f"/internal/data-platform/v1/loader/imports/{uuid.uuid4()}/finish",
        headers=_internal_headers(),
        json={
            "worker_id": "loader-1",
            "lease_token": "lease-1",
            "status": "succeeded",
            "rows_in": invalid_count,
        },
    )

    assert response.status_code == 422
    assert response.get_json()["detail"] == "rows_in must be a non-negative integer"
    assert store.finishes == []


def test_import_finish_applies_zero_defaults_to_missing_counts() -> None:
    store = StrictScalarStore()

    response = _store_client(store).post(
        f"/internal/data-platform/v1/loader/imports/{uuid.uuid4()}/finish",
        headers=_internal_headers(),
        json={
            "worker_id": "loader-1",
            "lease_token": "lease-1",
            "status": "succeeded",
            "rows_in": 4,
        },
    )

    assert response.status_code == 200
    assert store.finishes[0]["counts"] == {
        "rows_in": 4,
        "rows_staged": 0,
        "rows_accepted": 0,
        "rows_rejected": 0,
    }


class UuidBodyStore(StrictScalarStore):
    def create_run(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("malformed UUIDs must not reach persistence")

    attach_consumer_import_receipt = create_run
    attach_consumer_import_activation = create_run


@pytest.mark.parametrize(
    ("path", "body", "field"),
    [
        (
            f"/internal/data-platform/v1/jobs/{uuid.uuid4()}/runs",
            {"idempotency_key": "key-1", "request_id": "req-1", "parent_run_id": "nope"},
            "parent_run_id",
        ),
        (
            f"/internal/data-platform/v1/consumer-imports/{uuid.uuid4()}/receipt",
            {
                "worker_id": "worker-1",
                "lease_token": "lease-1",
                "publication_receipt_id": "nope",
                "receipt_status": "accepted",
            },
            "publication_receipt_id",
        ),
        (
            f"/internal/data-platform/v1/consumer-imports/{uuid.uuid4()}/activation",
            {"worker_id": "worker-1", "lease_token": "lease-1", "release_activation_id": "nope"},
            "release_activation_id",
        ),
    ],
)
def test_malformed_body_uuids_are_validation_problems(
    path: str, body: dict[str, Any], field: str
) -> None:
    response = _store_client(UuidBodyStore()).post(path, headers=_internal_headers(), json=body)

    assert response.status_code == 422
    assert response.content_type == "application/problem+json"
    assert response.get_json()["detail"] == f"{field} must be a UUID"
