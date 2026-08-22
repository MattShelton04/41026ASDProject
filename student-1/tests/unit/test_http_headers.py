from __future__ import annotations

import uuid

import httpx
from flask import Flask, request

from propertyscope_data_platform.app import create_app
from propertyscope_data_platform.clients import AiModeClient, DataStoreClient
from propertyscope_data_platform.http_headers import forwarded_headers

TRACEPARENT = "00-11111111111111111111111111111111-2222222222222222-01"


def test_app_ingress_preserves_valid_correlation_and_replaces_invalid_values() -> None:
    app = create_app()
    client = app.test_client()

    valid = client.get(
        "/health/live",
        headers={"X-Request-ID": "request-123", "traceparent": TRACEPARENT.upper()},
    )
    invalid = client.get(
        "/health/live",
        headers={"X-Request-ID": "contains spaces", "traceparent": "invalid"},
    )

    assert valid.headers["X-Request-ID"] == "request-123"
    assert valid.headers["traceparent"] == TRACEPARENT
    uuid.UUID(invalid.headers["X-Request-ID"])
    assert "traceparent" not in invalid.headers


def test_forwarded_headers_are_case_insensitive_and_canonical() -> None:
    app = Flask(__name__)

    with app.test_request_context(
        headers={
            "X-Request-ID": "request-123",
            "X-Agent-Run-ID": "run-123",
            "Traceparent": TRACEPARENT.upper(),
            "Idempotency-Key": "operation-123",
            "Authorization": "must-not-cross-the-boundary",
        }
    ):
        result = forwarded_headers(request.headers)

    assert result == {
        "X-Request-ID": "request-123",
        "X-Agent-Run-ID": "run-123",
        "traceparent": TRACEPARENT,
        "Idempotency-Key": "operation-123",
    }


def test_invalid_correlation_values_are_not_forwarded() -> None:
    result = forwarded_headers(
        {
            "x-request-id": "contains spaces",
            "TRACEPARENT": "00-00000000000000000000000000000000-2222222222222222-01",
            "idempotency-key": "safe-operation",
        }
    )

    assert result == {"Idempotency-Key": "safe-operation"}


def test_real_flask_headers_survive_datastore_and_ai_mode_clients() -> None:
    observed: list[httpx.Request] = []

    def handler(outbound: httpx.Request) -> httpx.Response:
        observed.append(outbound)
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    app = Flask(__name__)
    with (
        httpx.Client(transport=transport) as client,
        app.test_request_context(
            headers={
                "X-Request-ID": "request-123",
                "X-Agent-Run-ID": "run-123",
                "traceparent": TRACEPARENT,
                "Idempotency-Key": "operation-123",
            }
        ),
    ):
        DataStoreClient("http://database", "internal", client=client).request(
            "GET", "/internal/data-platform/v1/overview", headers=request.headers
        )
        AiModeClient("http://ai-mode", client=client).get(
            "/api/v1/agent-runs/run-123", request.headers
        )

    assert len(observed) == 2
    for outbound in observed:
        assert outbound.headers["X-Request-ID"] == "request-123"
        assert outbound.headers["X-Agent-Run-ID"] == "run-123"
        assert outbound.headers["traceparent"] == TRACEPARENT
        assert outbound.headers["Idempotency-Key"] == "operation-123"
