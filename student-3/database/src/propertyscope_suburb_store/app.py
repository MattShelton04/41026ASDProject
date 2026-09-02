"""Dependency-free WSGI database API; this process is the sole SQLite owner."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable
from http import HTTPStatus
from typing import Any
from urllib.parse import parse_qs, unquote

from .repository import Repository

StartResponse = Callable[[str, list[tuple[str, str]]], None]


def _json(start: StartResponse, status: int, payload: object) -> Iterable[bytes]:
    body = json.dumps(payload, separators=(",", ":")).encode()
    start(
        f"{status} {HTTPStatus(status).phrase}",
        [("Content-Type", "application/json"), ("Content-Length", str(len(body)))],
    )
    return [body]


def _body(environ: dict[str, Any]) -> dict[str, Any]:
    length = min(int(environ.get("CONTENT_LENGTH") or 0), 65_536)
    if length <= 0:
        return {}
    value = json.loads(environ["wsgi.input"].read(length))
    if not isinstance(value, dict):
        raise ValueError("JSON body must be an object")
    return value


def create_app(repository: Repository | None = None) -> Callable[..., Iterable[bytes]]:
    """Create the internal data API with an injectable repository for tests."""
    store = repository or Repository(
        os.getenv("SUBURB_DB_PATH", "/var/lib/propertyscope-suburbs/suburbs.sqlite3")
    )
    store.initialise()

    def app(environ: dict[str, Any], start: StartResponse) -> Iterable[bytes]:
        method = environ.get("REQUEST_METHOD", "GET")
        path = environ.get("PATH_INFO", "/").rstrip("/") or "/"
        query = {
            key: values[-1] for key, values in parse_qs(environ.get("QUERY_STRING", "")).items()
        }
        try:
            if path in {"/health/live", "/health/ready"}:
                return _json(
                    start,
                    200,
                    {
                        "status": "ready",
                        "service": "suburb-analytics-store",
                        "tables": store.table_counts(),
                    },
                )
            if path == "/internal/v1/suburbs" and method == "GET":
                cursor = max(int(query.get("cursor", "0")), 0)
                limit = min(max(int(query.get("limit", "50")), 1), 100)
                items, total = store.list_suburbs(
                    query.get("q", ""),
                    query.get("lga", ""),
                    query.get("amenity", ""),
                    query.get("sort", "locality"),
                    limit,
                    cursor,
                )
                next_cursor = cursor + len(items) if cursor + len(items) < total else None
                return _json(
                    start,
                    200,
                    {
                        "items": items,
                        "page": {
                            "limit": limit,
                            "next_cursor": next_cursor,
                            "has_more": next_cursor is not None,
                            "total": total,
                        },
                        "count": len(items),
                    },
                )
            if path == "/internal/v1/places/nearby" and method == "GET":
                latitude = float(query["latitude"])
                longitude = float(query["longitude"])
                radius_m = min(max(int(query.get("radius_m", "2000")), 100), 10_000)
                items = store.nearby_places(latitude, longitude, radius_m)
                return _json(
                    start,
                    200,
                    {
                        "items": items,
                        "count": len(items),
                        "method": "haversine_straight_line",
                        "radius_m": radius_m,
                    },
                )
            if path.startswith("/internal/v1/suburbs/"):
                parts = path.split("/")
                if len(parts) >= 6:
                    state, locality = unquote(parts[4]), unquote(parts[5])
                    if len(parts) == 6 and method == "GET":
                        item = store.suburb(state, locality)
                        return (
                            _json(start, 200, {"suburb": item})
                            if item
                            else _json(start, 404, {"code": "suburb_not_found"})
                        )
                    if len(parts) == 7 and parts[6] == "places" and method == "GET":
                        items = store.places(
                            state, locality, query.get("type", ""), int(query.get("limit", "50"))
                        )
                        return _json(start, 200, {"items": items, "count": len(items)})
                    if len(parts) == 7 and parts[6] == "crime-series" and method == "GET":
                        items = store.series(
                            state,
                            locality,
                            query.get("measure", "count"),
                            query.get("from", "2026-01"),
                            query.get("to", "2026-06"),
                            query.get("offence", "all_recorded"),
                        )
                        return _json(start, 200, {"items": items, "count": len(items)})
                    if len(parts) == 7 and parts[6] == "area-series" and method == "GET":
                        items = store.area_series(
                            state, locality, query.get("metric", "population_density")
                        )
                        return _json(start, 200, {"items": items, "count": len(items)})
            if path == "/internal/v1/suburb-comparisons":
                if method == "GET":
                    items = store.comparisons()
                    return _json(start, 200, {"items": items, "count": len(items)})
                if method == "POST":
                    return _json(
                        start, 201, {"comparison": store.create_comparison(_body(environ))}
                    )
            if path.startswith("/internal/v1/suburb-comparisons/"):
                comparison_id = unquote(path.rsplit("/", 1)[-1])
                if method == "GET":
                    item = store.comparison(comparison_id)
                    return (
                        _json(start, 200, {"comparison": item})
                        if item
                        else _json(start, 404, {"code": "comparison_not_found"})
                    )
                if method == "PUT":
                    item = store.update_comparison(comparison_id, _body(environ))
                    return (
                        _json(start, 200, {"comparison": item})
                        if item
                        else _json(start, 404, {"code": "comparison_not_found"})
                    )
                if method == "DELETE":
                    return (
                        _json(start, 200, {"deleted": True})
                        if store.delete_comparison(comparison_id)
                        else _json(start, 404, {"code": "comparison_not_found"})
                    )
        except (ValueError, json.JSONDecodeError) as exc:
            status = 409 if str(exc) == "version_conflict" else 422
            return _json(
                start, status, {"code": str(exc), "detail": "The request could not be applied."}
            )
        return _json(start, 404, {"code": "route_not_found"})

    return app


def main() -> None:
    from wsgiref.simple_server import make_server

    port = int(os.getenv("PORT", "5302"))
    with make_server("0.0.0.0", port, create_app()) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
