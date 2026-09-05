"""Public WSGI API for Student 3's suburb analytics feature."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Iterable
from datetime import date
from http import HTTPStatus
from typing import Any
from urllib.parse import parse_qs, quote, unquote

import httpx

from shared_contracts import read_json_object

from .clients import HttpClient, ServiceError
from .ingestion import IMPORT_PATH, Ingestion, correlation

StartResponse = Callable[[str, list[tuple[str, str]]], None]
BASE = "/api/suburb-analytics/v1"
ALLOWED_MEASURES = {"count", "rate"}
ALLOWED_OFFENCES = {"all_recorded", "property", "person"}


def _response(
    start: StartResponse, status: int, payload: object, content_type: str = "application/json"
) -> Iterable[bytes]:
    body = json.dumps(payload, separators=(",", ":")).encode()
    headers = [
        ("Content-Type", content_type),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-store"),
    ]
    start(f"{status} {HTTPStatus(status).phrase}", headers)
    return [body]


def _problem(start: StartResponse, status: int, code: str, detail: str) -> Iterable[bytes]:
    return _response(
        start,
        status,
        {
            "type": f"https://propertyscope.invalid/problems/{code}",
            "title": code.replace("_", " ").title(),
            "status": status,
            "detail": detail,
            "code": code,
        },
        "application/problem+json",
    )


def _body(environ: dict[str, Any]) -> dict[str, Any]:
    return read_json_object(environ, max_bytes=2_000_000)


def _validate_comparison(payload: dict[str, Any], *, require_version: bool = False) -> None:
    if not str(payload.get("name", "")).strip():
        raise ValueError("name is required")
    localities = payload.get("localities")
    if (
        not isinstance(localities, list)
        or not 1 <= len(localities) <= 5
        or not all(isinstance(item, str) and item.strip() for item in localities)
    ):
        raise ValueError("localities must contain one to five suburb names")
    if payload.get("measure") not in ALLOWED_MEASURES:
        raise ValueError("measure must be count or rate")
    for field in ("from_month", "to_month"):
        value = payload.get(field)
        if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}", value):
            raise ValueError(f"{field} must be a YYYY-MM month")
        try:
            date.fromisoformat(value + "-01")
        except ValueError as exc:
            raise ValueError(f"{field} must be a valid calendar month") from exc
    if payload["from_month"] > payload["to_month"]:
        raise ValueError("from_month must not be after to_month")
    if require_version and (type(payload.get("version")) is not int or payload["version"] < 1):
        raise ValueError("version is required for an update")


def create_app(
    store: HttpClient | None = None,
    ai_mode: HttpClient | None = None,
    property_data: HttpClient | None = None,
) -> Callable[..., Iterable[bytes]]:
    data = store or HttpClient(os.getenv("SUBURB_STORE_URL", "http://f3-database:5302"))
    ai = ai_mode or HttpClient(os.getenv("AI_MODE_URL", "http://ai-mode:5005"), timeout=8.0)
    properties = property_data or HttpClient(
        os.getenv("PROPERTY_DATA_URL", "http://f1-backend:5201"), timeout=4.0
    )
    ingestion = Ingestion(data, properties.base_url)
    if os.getenv("SUBURB_IMPORT_WORKER") == "1":
        ingestion.start()

    def app(environ: dict[str, Any], start: StartResponse) -> Iterable[bytes]:
        method = environ.get("REQUEST_METHOD", "GET")
        path = environ.get("PATH_INFO", "/").rstrip("/") or "/"
        raw_query = environ.get("QUERY_STRING", "")
        query = {key: values[-1] for key, values in parse_qs(raw_query).items()}
        try:
            if path == IMPORT_PATH and method == "POST":
                return _response(
                    start,
                    202,
                    ingestion.enqueue(
                        _body(environ),
                        correlation(environ),
                        environ.get("HTTP_IDEMPOTENCY_KEY", ""),
                    ),
                )
            if path.startswith(IMPORT_PATH + "/") and method == "GET":
                return _response(
                    start,
                    200,
                    data.request(
                        "GET",
                        "/internal/v1/imports/"
                        + quote(path.removeprefix(IMPORT_PATH + "/"), safe=""),
                    ),
                )
            if (
                path.startswith(f"{BASE}/data-imports/")
                and path.endswith("/retry")
                and method == "POST"
            ):
                operation = quote(
                    path.removeprefix(f"{BASE}/data-imports/").removesuffix("/retry"), safe=""
                )
                return _response(
                    start, 202, data.request("POST", f"/internal/v1/imports/{operation}/retry", {})
                )
            if (
                path.startswith(f"{BASE}/data-imports/")
                and path.endswith("/sync")
                and method == "POST"
            ):
                dataset = path.removeprefix(f"{BASE}/data-imports/").removesuffix("/sync")
                return _response(start, 202, ingestion.sync(dataset, correlation(environ)))
            if (
                path
                in {
                    f"{BASE}/published/sources",
                    f"{BASE}/published/suburbs",
                    f"{BASE}/published/context",
                }
                and method == "GET"
            ):
                return _response(
                    start,
                    200,
                    data.request(
                        "GET", "/internal/v1/" + path.removeprefix(BASE + "/") + "?" + raw_query
                    ),
                )
            if path in {"/health/live", "/health/ready"}:
                health = data.request("GET", "/health/ready")
                return _response(
                    start,
                    200,
                    {
                        "status": "ready",
                        "service": "suburb-analytics",
                        "checks": {"database": health["status"], "ai_mode": "optional"},
                    },
                )
            if path == f"{BASE}/suburbs" and method == "GET":
                return _response(
                    start, 200, data.request("GET", f"/internal/v1/suburbs?{raw_query}")
                )
            if path.startswith(f"{BASE}/properties/") and path.endswith("/nearby-places"):
                property_ref = unquote(
                    path.removeprefix(f"{BASE}/properties/").removesuffix("/nearby-places")
                ).strip("/")
                if not property_ref:
                    raise ValueError("property_ref is required")
                context = properties.request(
                    "GET", f"/api/data-platform/v1/properties/{quote(property_ref)}/map-context"
                )
                latitude = context.get("latitude")
                longitude = context.get("longitude")
                if not isinstance(latitude, (int, float)) or not isinstance(
                    longitude, (int, float)
                ):
                    raise ServiceError(502, {"code": "invalid_property_map_context"})
                radius = min(max(int(query.get("radius_m", "2000")), 100), 10_000)
                nearby = data.request(
                    "GET",
                    "/internal/v1/places/nearby"
                    f"?latitude={latitude}&longitude={longitude}&radius_m={radius}",
                )
                return _response(
                    start,
                    200,
                    nearby
                    | {
                        "property_ref": property_ref,
                        "distance_label": "straight-line",
                        "catchment_status": "not_assessed",
                    },
                )
            if path.startswith(f"{BASE}/suburbs/"):
                suffix = path.removeprefix(f"{BASE}/suburbs/").split("/")
                if len(suffix) >= 2:
                    state, locality = unquote(suffix[0]), unquote(suffix[1])
                    internal = f"/internal/v1/suburbs/{quote(state)}/{quote(locality)}"
                    if len(suffix) == 2 and method == "GET":
                        return _response(start, 200, data.request("GET", internal))
                    if len(suffix) == 3 and suffix[2] == "places" and method == "GET":
                        return _response(
                            start, 200, data.request("GET", f"{internal}/places?{raw_query}")
                        )
                    if len(suffix) == 3 and suffix[2] == "crime-series" and method == "GET":
                        measure = query.get("measure", "count")
                        offence = query.get("offence", "all_recorded")
                        if measure not in ALLOWED_MEASURES:
                            return _problem(
                                start,
                                422,
                                "incomparable_measure",
                                "Use one measure: count or rate.",
                            )
                        if offence not in ALLOWED_OFFENCES:
                            return _problem(
                                start,
                                422,
                                "unsupported_offence",
                                "Choose a supported offence category.",
                            )
                        return _response(
                            start, 200, data.request("GET", f"{internal}/crime-series?{raw_query}")
                        )
                    if len(suffix) == 3 and suffix[2] == "area-series" and method == "GET":
                        metric = query.get("metric", "population_density")
                        allowed_metrics = {
                            "population_density",
                            "amenity_observations",
                            "school_observations",
                            "transport_observations",
                        }
                        if metric not in allowed_metrics:
                            return _problem(
                                start,
                                422,
                                "unsupported_indicator",
                                "Choose a supported factual context indicator.",
                            )
                        return _response(
                            start,
                            200,
                            data.request("GET", f"{internal}/area-series?metric={metric}"),
                        )
            if path == f"{BASE}/crime/compare" and method == "GET":
                localities = [
                    item.strip() for item in query.get("localities", "").split(",") if item.strip()
                ]
                measure = query.get("measure", "count")
                offence = query.get("offence", "all_recorded")
                if (
                    not 2 <= len(localities) <= 5
                    or measure not in ALLOWED_MEASURES
                    or offence not in ALLOWED_OFFENCES
                ):
                    return _problem(
                        start,
                        422,
                        "incomparable_selection",
                        "Choose two to five suburbs and one common measure.",
                    )
                series = []
                for locality in localities:
                    from_month = quote(query.get("from", "2026-01"))
                    to_month = quote(query.get("to", "2026-06"))
                    series_path = (
                        f"/internal/v1/suburbs/NSW/{quote(locality)}/crime-series"
                        f"?from={from_month}&to={to_month}&measure={measure}&offence={offence}"
                    )
                    selected = data.request(
                        "GET",
                        series_path,
                    )
                    series.append({"locality": locality, "items": selected["items"]})
                return _response(
                    start,
                    200,
                    {
                        "series": series,
                        "measure": measure,
                        "offence": offence,
                        "from_month": query.get("from", "2026-01"),
                        "to_month": query.get("to", "2026-06"),
                        "limitations": [
                            "Demonstration fixtures are partial and are not a safety ranking.",
                            "Rate values are calculated fixture rates per 100,000.",
                        ],
                    },
                )
            if path == f"{BASE}/crime/methodology" and method == "GET":
                return _response(
                    start,
                    200,
                    {
                        "geography": "NSW suburb fixture",
                        "measures": ["count", "rate"],
                        "offence_categories": ["all_recorded", "property", "person"],
                        "zero_missing_rule": (
                            "Recorded zero is 0; missing is null and is never plotted as zero."
                        ),
                        "responsible_use": (
                            "Do not infer causes, predict crime, or label places safe or unsafe."
                        ),
                        "source_release": "demo-2026.1",
                    },
                )
            if path == f"{BASE}/assistant/capabilities" and method == "GET":
                return _response(
                    start,
                    200,
                    {
                        "feature_key": "student-3-suburb-analytics",
                        "status": "available",
                        "tools": [
                            "suburb.snapshot.v1",
                            "crime.compare.v1",
                            "crime.methodology.v1",
                        ],
                        "limitations": [
                            "Answers are limited to supported fixture evidence.",
                            "The assistant does not rank safety, desirability or social worth.",
                        ],
                    },
                )
            if path == f"{BASE}/assistant/turns" and method == "POST":
                payload = _body(environ)
                message = str(payload.get("message", "")).strip()
                if not 2 <= len(message) <= 2000:
                    raise ValueError("message must contain between 2 and 2000 characters")
                history = payload.get("history", [])
                if not isinstance(history, list) or len(history) > 8:
                    raise ValueError("history must contain at most eight messages")
                context = payload.get("context", {})
                if not isinstance(context, dict):
                    raise ValueError("context must be an object")
                locality = str(context.get("locality", "")).strip()
                if locality:
                    data.request("GET", f"/internal/v1/suburbs/NSW/{quote(locality)}")
                objective = (
                    "Suburb analytics assistant turn. Current user question: "
                    f"{json.dumps(message, ensure_ascii=False)}. "
                    + (f"Validated selected locality: {locality}. " if locality else "")
                    + "Use only allowlisted recorded evidence. Clearly distinguish counts from "
                    "rates and recorded zero from missing. Cite periods and source releases. "
                    "You may suggest practical research questions or amenities to verify, but do "
                    "not infer crime causes, predict crime, rank safety/desirability, or make a "
                    "buy/no-buy recommendation. State that nearby schools do not prove catchment."
                )
                run = ai.request(
                    "POST",
                    "/api/v1/agent-runs",
                    {
                        "feature_key": "student-3-suburb-analytics",
                        "objective": objective,
                        "prompt_set": "default.v7",
                        "tool_allowlist": [
                            "suburb.snapshot.v1",
                            "crime.compare.v1",
                            "crime.methodology.v1",
                        ],
                        "limits": {
                            "max_iterations": 4,
                            "max_tool_calls": 8,
                            "time_budget_ms": 120000,
                            "max_model_repairs": 2,
                        },
                    },
                )
                return _response(start, 202, run)
            if path.startswith(f"{BASE}/assistant/turns/"):
                turn_suffix = path.removeprefix(f"{BASE}/assistant/turns/").split("/")
                run_id = quote(unquote(turn_suffix[0]))
                if len(turn_suffix) == 1 and method == "GET":
                    return _response(start, 200, ai.request("GET", f"/api/v1/agent-runs/{run_id}"))
                if len(turn_suffix) == 2 and turn_suffix[1] == "events" and method == "GET":
                    return _response(
                        start,
                        200,
                        ai.request("GET", f"/api/v1/agent-runs/{run_id}/events?{raw_query}"),
                    )
                if len(turn_suffix) == 2 and turn_suffix[1] == "cancel" and method == "POST":
                    return _response(
                        start,
                        200,
                        ai.request("POST", f"/api/v1/agent-runs/{run_id}/cancel", {}),
                    )
            if path == f"{BASE}/tools/suburb.snapshot.v1" and method == "POST":
                payload = _body(environ)
                locality = str(payload.get("locality", "")).strip()
                if not locality:
                    raise ValueError("locality is required")
                suburb = data.request("GET", f"/internal/v1/suburbs/NSW/{quote(locality)}")[
                    "suburb"
                ]
                places = data.request(
                    "GET", f"/internal/v1/suburbs/NSW/{quote(locality)}/places?limit=20"
                )
                return _response(
                    start,
                    200,
                    {
                        "suburb": suburb,
                        "places": places["items"],
                        "limitations": [
                            "Partial demonstration fixture",
                            "Nearby schools do not establish catchment eligibility",
                        ],
                    },
                )
            if path == f"{BASE}/tools/crime.compare.v1" and method == "POST":
                payload = _body(environ)
                localities = payload.get("localities", [])
                measure = payload.get("measure", "count")
                offence = payload.get("offence", "all_recorded")
                if (
                    not isinstance(localities, list)
                    or not 2 <= len(localities) <= 5
                    or measure not in ALLOWED_MEASURES
                    or offence not in ALLOWED_OFFENCES
                ):
                    raise ValueError("Choose two to five localities and count or rate")
                series = []
                for locality in localities:
                    from_month = quote(str(payload.get("from_month", "2026-01")))
                    to_month = quote(str(payload.get("to_month", "2026-06")))
                    series_path = (
                        f"/internal/v1/suburbs/NSW/{quote(str(locality))}/crime-series"
                        f"?from={from_month}&to={to_month}&measure={measure}&offence={offence}"
                    )
                    selected = data.request(
                        "GET",
                        series_path,
                    )
                    series.append({"locality": locality, "items": selected["items"]})
                return _response(
                    start,
                    200,
                    {
                        "series": series,
                        "measure": measure,
                        "offence": offence,
                        "source_release": "demo-2026.1",
                        "limitations": ["Do not infer causes, predict crime or rank suburb safety"],
                    },
                )
            if path == f"{BASE}/tools/crime.methodology.v1" and method == "POST":
                return _response(
                    start,
                    200,
                    {
                        "geography": "NSW suburb fixture",
                        "measures": ["count", "rate"],
                        "offence_categories": ["all_recorded", "property", "person"],
                        "zero_missing_rule": "Recorded zero is 0; missing is null.",
                        "rate_method": (
                            "Fixture count divided by fixture population, multiplied by 100,000."
                        ),
                        "responsible_use": "No causal claims, predictions or safety ranking.",
                        "source_release": "demo-2026.1",
                    },
                )
            if path == f"{BASE}/suburb-comparisons":
                if method == "GET":
                    return _response(
                        start, 200, data.request("GET", "/internal/v1/suburb-comparisons")
                    )
                if method == "POST":
                    payload = _body(environ)
                    _validate_comparison(payload)
                    return _response(
                        start, 201, data.request("POST", "/internal/v1/suburb-comparisons", payload)
                    )
            if path.startswith(f"{BASE}/suburb-comparisons/"):
                suffix = path.removeprefix(f"{BASE}/suburb-comparisons/").split("/")
                comparison_id = quote(unquote(suffix[0]))
                internal = f"/internal/v1/suburb-comparisons/{comparison_id}"
                if len(suffix) == 1:
                    if method == "GET":
                        return _response(start, 200, data.request("GET", internal))
                    if method == "PUT":
                        payload = _body(environ)
                        _validate_comparison(payload, require_version=True)
                        return _response(start, 200, data.request("PUT", internal, payload))
                    if method == "DELETE":
                        return _response(start, 200, data.request("DELETE", internal))
                if len(suffix) == 2 and suffix[1] == "agent-runs" and method == "POST":
                    comparison = data.request("GET", internal)["comparison"]
                    objective = (
                        "Describe the selected recorded offence trends neutrally for "
                        + ", ".join(comparison["localities"])
                        + f" from {comparison['from_month']} to {comparison['to_month']} using "
                        + f"{comparison['measure']}. Distinguish zero from missing, cite evidence, "
                        + "do not infer causes, predict crime, or rank safety."
                    )
                    run = ai.request(
                        "POST",
                        "/api/v1/agent-runs",
                        {
                            "feature_key": "student-3-suburb-analytics",
                            "objective": objective,
                            "trusted_identifiers": [
                                {"kind": "suburb_comparison_id", "value": comparison["id"]}
                            ],
                            "prompt_set": "default.v7",
                            "tool_allowlist": [
                                "suburb.snapshot.v1",
                                "crime.compare.v1",
                                "crime.methodology.v1",
                            ],
                            "limits": {
                                "max_iterations": 4,
                                "max_tool_calls": 6,
                                "time_budget_ms": 120000,
                                "max_model_repairs": 2,
                            },
                        },
                    )
                    return _response(start, 202, run)
        except httpx.HTTPStatusError as exc:
            return _problem(
                start,
                503 if exc.response.status_code >= 500 else 409,
                "published_source_unavailable",
                "An accepted downloadable source release is not available. "
                "Review it in Feature 1 first.",
            )
        except httpx.HTTPError:
            return _problem(
                start, 503, "producer_unavailable", "The data platform could not be reached."
            )
        except ValueError as exc:
            return _problem(start, 422, "invalid_request", str(exc))
        except ServiceError as exc:
            detail = (
                "The optional AI service is unavailable; saved comparisons and charts still work."
                if exc.status == 503 and (path.endswith("agent-runs") or "/assistant/turns" in path)
                else "A required feature dependency could not complete the request."
            )
            return _problem(
                start, exc.status, str(exc.payload.get("code", "dependency_error")), detail
            )
        return _problem(
            start, 404, "route_not_found", "The requested suburb analytics route does not exist."
        )

    return app


def main() -> None:
    from wsgiref.simple_server import make_server

    with make_server("0.0.0.0", int(os.getenv("PORT", "5301")), create_app()) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
