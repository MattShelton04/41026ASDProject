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
from propertyscope_data_platform.http_support import json_body, register_error_handlers
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
