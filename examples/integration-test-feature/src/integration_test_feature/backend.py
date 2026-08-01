"""Feature-owned API and AI tool boundary for the integration-test slice."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote

import httpx
from flask import Flask, Response, jsonify, request
from werkzeug.datastructures import Headers

from integration_test_feature.errors import problem_response
from shared_contracts import (
    AGENT_RUN_ID_HEADER,
    IDEMPOTENCY_KEY_HEADER,
    REQUEST_ID_HEADER,
    TRACEPARENT_HEADER,
)

PROPAGATED_HEADERS = (
    REQUEST_ID_HEADER,
    AGENT_RUN_ID_HEADER,
    TRACEPARENT_HEADER,
    IDEMPOTENCY_KEY_HEADER,
)


def create_backend_app(database_base_url: str, *, client: httpx.Client | None = None) -> Flask:
    """Create a backend that reaches persistence only through the database API."""
    app = Flask("integration-test-feature-backend")
    http_client = client or httpx.Client(timeout=2, follow_redirects=False)
    origin = database_base_url.rstrip("/")

    @app.get("/health/ready")
    def ready() -> tuple[Response, int]:
        try:
            response = http_client.get(f"{origin}/health/ready")
            healthy = response.status_code == 200
        except httpx.TransportError:
            healthy = False
        return jsonify({"status": "healthy" if healthy else "unhealthy"}), 200 if healthy else 503

    @app.post("/api/v1/tools/records.search.v1")
    def search_tool() -> Response:
        payload: Any = request.get_json(silent=True)
        query = payload.get("query", "").strip() if isinstance(payload, dict) else ""
        if not query or len(query) > 200:
            return problem_response(422, "invalid_arguments", "query must be 1 to 200 characters")
        response = http_client.get(
            f"{origin}/api/v1/records",
            params={"query": query},
            headers=_forwarded_headers(request.headers),
        )
        return _forward_json_response(response)

    @app.post("/api/v1/tools/records.create.v1")
    def create_tool() -> Response:
        payload: Any = request.get_json(silent=True)
        title = payload.get("title", "").strip() if isinstance(payload, dict) else ""
        key = request.headers.get(IDEMPOTENCY_KEY_HEADER, "").strip()
        if not title or not key:
            return problem_response(
                422,
                "invalid_arguments",
                "title and Idempotency-Key are required",
            )
        response = http_client.post(
            f"{origin}/api/v1/records",
            json={"title": title},
            headers=_forwarded_headers(request.headers),
        )
        return _forward_json_response(response)

    @app.post("/api/v1/tools/records.inspect.v1")
    def inspect_tool() -> Response:
        title = _required_title(request.get_json(silent=True))
        if title is None:
            return problem_response(422, "invalid_arguments", "title must be 1 to 200 characters")
        response = http_client.get(
            f"{origin}/api/v1/records/by-title/{quote(title, safe='')}",
            headers=_forwarded_headers(request.headers),
        )
        return _forward_json_response(response)

    @app.post("/api/v1/tools/records.dependencies.v1")
    def dependencies_tool() -> Response:
        title = _required_title(request.get_json(silent=True))
        if title is None:
            return problem_response(422, "invalid_arguments", "title must be 1 to 200 characters")
        response = http_client.get(
            f"{origin}/api/v1/records/by-title/{quote(title, safe='')}/dependencies",
            headers=_forwarded_headers(request.headers),
        )
        return _forward_json_response(response)

    @app.get("/api/v1/tool-operations/<path:idempotency_key>")
    def operation_status(idempotency_key: str) -> Response:
        response = http_client.get(
            f"{origin}/api/v1/operations/{quote(idempotency_key, safe='')}",
            headers=_forwarded_headers(request.headers),
        )
        return _forward_json_response(response)

    return app


def _forwarded_headers(headers: Headers) -> dict[str, str]:
    return {name: headers[name] for name in PROPAGATED_HEADERS if name in headers}


def _required_title(payload: Any) -> str | None:
    title = payload.get("title", "").strip() if isinstance(payload, dict) else ""
    return title if 1 <= len(title) <= 200 else None


def _forward_json_response(upstream: httpx.Response) -> Response:
    """Preserve safe JSON and Problem Details media types across the backend hop."""
    response = jsonify(upstream.json())
    response.status_code = upstream.status_code
    if upstream.headers.get("content-type", "").split(";", 1)[0] == "application/problem+json":
        response.content_type = "application/problem+json"
    return response


def create_app() -> Flask:
    """Environment-driven application factory used by the backend container."""
    return create_backend_app(
        os.environ.get(
            "INTEGRATION_TEST_DATABASE_URL",
            "http://integration-test-feature-database:5102",
        )
    )
