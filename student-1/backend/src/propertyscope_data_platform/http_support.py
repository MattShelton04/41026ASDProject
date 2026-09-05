"""Small, reusable Flask adapters for Feature 1's HTTP boundary."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

import httpx
from flask import Response, jsonify, request

from propertyscope_data_platform.clients import DataStoreClient, DependencyUnavailableError


def proxy_collection(store: DataStoreClient, path: str) -> Response:
    return forward(
        store.request(
            request.method,
            path,
            headers=request.headers,
            params=request.args,
            json=json_body() if request.method == "POST" else None,
        )
    )


def proxy_item(store: DataStoreClient, path: str) -> Response:
    return forward(
        store.request(
            request.method,
            path,
            headers=request.headers,
            json=json_body() if request.method == "PUT" else None,
        )
    )


def json_body(*, optional: bool = False) -> dict[str, Any]:
    if optional and not request.data:
        return {}
    value: Any = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise ValueError("request body must be a JSON object")
    return value


def required_uuid(body: Mapping[str, Any], name: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(body.get(name, "")))
    except ValueError as exc:
        raise ValueError(f"{name} must be a UUID") from exc


def tool_envelope(upstream: httpx.Response) -> Response:
    """Strip internal pagination fields to match bounded tool output contracts."""
    if upstream.status_code >= 400:
        return forward(upstream)
    data = upstream_json_object(upstream)
    return jsonify({"items": data.get("items", []), "count": data.get("count", 0)})


def upstream_json_object(upstream: httpx.Response) -> dict[str, Any]:
    """Reject broken dependency payloads without blaming the caller or leaking bodies."""
    try:
        data = upstream.json()
    except ValueError as exc:
        raise DependencyUnavailableError(
            "A dependency returned an unreadable JSON response"
        ) from exc
    if not isinstance(data, dict):
        raise DependencyUnavailableError("A dependency returned an invalid JSON response")
    return data


def forward(upstream: httpx.Response) -> Response:
    """Project an upstream response and its correlation fields onto Flask."""
    if upstream.is_redirect:
        raise DependencyUnavailableError("A dependency returned an unexpected redirect")
    response = (
        Response(status=204)
        if upstream.status_code == 204
        else jsonify(upstream_json_object(upstream))
    )
    response.status_code = upstream.status_code
    if upstream.headers.get("content-type", "").split(";", 1)[0] == "application/problem+json":
        response.content_type = "application/problem+json"
    for name in ("Location", "X-Request-ID", "X-Agent-Run-ID", "traceparent"):
        if name in upstream.headers:
            response.headers[name] = upstream.headers[name]
    return response


def forward_json_bytes(upstream: httpx.Response) -> Response:
    """Relay a large private JSON page without parsing and serialising it a second time."""
    if upstream.status_code >= 400 or upstream.is_redirect or upstream.status_code == 204:
        return forward(upstream)
    media_type = upstream.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json" or not upstream.content:
        raise DependencyUnavailableError("A dependency returned an invalid JSON page")
    response = Response(
        upstream.content, status=upstream.status_code, content_type="application/json"
    )
    for name in ("X-Request-ID", "traceparent"):
        if name in upstream.headers:
            response.headers[name] = upstream.headers[name]
    return response


def problem(status: int, code: str, detail: str) -> Response:
    response = jsonify(
        {
            "type": f"https://propertyscope.local/problems/{code}",
            "title": code.replace("_", " ").title(),
            "status": status,
            "detail": detail,
            "code": code,
            "request_id": request.headers.get("X-Request-ID", "unknown"),
        }
    )
    response.status_code = status
    response.content_type = "application/problem+json"
    return response


def register_error_handlers(app: Any) -> None:
    app.register_error_handler(
        DependencyUnavailableError, lambda error: problem(503, "dependency_unavailable", str(error))
    )
    app.register_error_handler(
        ValueError, lambda error: problem(422, "invalid_request", str(error))
    )
    app.register_error_handler(
        404, lambda _: problem(404, "route_not_found", "Route does not exist")
    )
    app.register_error_handler(
        405, lambda _: problem(405, "method_not_allowed", "Method is not allowed")
    )
    app.register_error_handler(
        413,
        lambda _: problem(413, "request_too_large", "Request body exceeds the configured limit"),
    )
