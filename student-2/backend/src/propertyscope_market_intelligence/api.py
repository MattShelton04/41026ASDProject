"""Public API, release import and bounded AI workflow for Feature 2."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

import httpx
from flask import Blueprint, Flask, Response, jsonify, request
from pydantic import ValidationError

from propertyscope_market_intelligence.clients import DependencyUnavailableError
from propertyscope_market_intelligence.domain import (
    FEATURE_KEY,
    TOOL_ALLOWLIST,
    AssistantTurn,
    MarketCaseCreate,
    MarketCaseUpdate,
    PublicationRequest,
    decode_sales_artifact,
    summarize_sales,
)
from shared_contracts import HealthStatus, ReadinessCheckProjection, project_readiness

_SERVICE = "propertyscope-market-intelligence"
_VERSION = "0.1.0"
_API = "/api/market-intelligence/v1"
_INTERNAL = "/internal/market-intelligence/v1"


def _problem(status: int, code: str, detail: str) -> Response:
    response = jsonify(
        {
            "type": f"https://propertyscope.local/problems/{code}",
            "title": code.replace("_", " ").title(),
            "status": status,
            "detail": detail,
            "code": code,
        }
    )
    response.status_code = status
    response.content_type = "application/problem+json"
    return response


def _relay(upstream: httpx.Response) -> Response:
    try:
        payload = upstream.json()
    except ValueError:
        payload = {"status": upstream.status_code}
    response = jsonify(payload)
    response.status_code = upstream.status_code
    if upstream.headers.get("content-type", "").split(";", 1)[0] == "application/problem+json":
        response.content_type = "application/problem+json"
    return response


def _json_body() -> dict[str, Any]:
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise ValueError("request body must be a JSON object")
    return value


def _validation_problem(code: str, exc: ValidationError) -> Response:
    issue = exc.errors(include_url=False)[0]
    location = ".".join(str(item) for item in issue.get("loc", ())) or "request"
    return _problem(422, code, f"{location}: {issue['msg']}")


def _case_evidence(store: Any, case_id: str) -> tuple[dict[str, Any] | None, Response | None]:
    case_response = store.request("GET", f"{_INTERNAL}/market-cases/{case_id}")
    if case_response.status_code >= 400:
        return None, _relay(case_response)
    market_case = case_response.json()
    sales_response = store.request(
        "GET",
        f"{_INTERNAL}/sales",
        params={"property_ref": market_case["property_ref"], "limit": 5000},
    )
    if sales_response.status_code >= 400:
        return None, _relay(sales_response)
    sales = sales_response.json().get("items", [])
    return {
        "market_case": market_case,
        "summary": summarize_sales(market_case, sales),
        "sales": sales[:100],
    }, None


def register_health(app: Flask, store: Any) -> None:
    @app.get("/health/live")
    def live() -> tuple[Response, int]:
        projection = project_readiness(
            service=_SERVICE,
            version=_VERSION,
            checks={
                "process": ReadinessCheckProjection(
                    required=True,
                    status=HealthStatus.HEALTHY,
                    detail="Market intelligence backend is accepting requests",
                )
            },
        )
        return jsonify(projection.model_dump(mode="json")), projection.http_status

    @app.get("/health/ready")
    def ready() -> tuple[Response, int]:
        healthy = bool(store.ready())
        projection = project_readiness(
            service=_SERVICE,
            version=_VERSION,
            checks={
                "database_api": ReadinessCheckProjection(
                    required=True,
                    status=HealthStatus.HEALTHY if healthy else HealthStatus.UNHEALTHY,
                    detail="Feature database API reachable"
                    if healthy
                    else "Feature database API unavailable",
                )
            },
        )
        return jsonify(projection.model_dump(mode="json")), projection.http_status


def create_blueprint(store: Any, feature1: Any, ai_mode: Any) -> Blueprint:
    blueprint = Blueprint("market_intelligence", __name__)

    @blueprint.get(f"{_API}/market-cases")
    def list_cases() -> Response:
        return _relay(store.request("GET", f"{_INTERNAL}/market-cases", params=request.args))

    @blueprint.post(f"{_API}/market-cases")
    def create_case() -> Response:
        try:
            command = MarketCaseCreate.model_validate(_json_body())
        except ValidationError as exc:
            return _validation_problem("invalid_market_case", exc)
        validation_state = feature1.validate_property(str(command.property_ref))
        if validation_state == "not_found":
            return _problem(
                422, "unknown_property", "Feature 1 does not contain that property reference"
            )
        payload = command.model_dump(mode="json")
        payload["property_validation_state"] = validation_state
        return _relay(store.request("POST", f"{_INTERNAL}/market-cases", json=payload))

    @blueprint.get(f"{_API}/market-cases/<uuid:case_id>")
    def get_case(case_id: uuid.UUID) -> Response:
        return _relay(store.request("GET", f"{_INTERNAL}/market-cases/{case_id}"))

    @blueprint.put(f"{_API}/market-cases/<uuid:case_id>")
    def update_case(case_id: uuid.UUID) -> Response:
        try:
            command = MarketCaseUpdate.model_validate(_json_body())
        except ValidationError as exc:
            return _validation_problem("invalid_market_case", exc)
        payload = command.model_dump(mode="json", exclude_none=True)
        return _relay(store.request("PUT", f"{_INTERNAL}/market-cases/{case_id}", json=payload))

    @blueprint.delete(f"{_API}/market-cases/<uuid:case_id>")
    def delete_case(case_id: uuid.UUID) -> Response:
        return _relay(store.request("DELETE", f"{_INTERNAL}/market-cases/{case_id}"))

    @blueprint.get(f"{_API}/market-cases/<uuid:case_id>/evidence")
    def evidence(case_id: uuid.UUID) -> Response:
        value, error = _case_evidence(store, str(case_id))
        return error or jsonify(value)

    @blueprint.get(f"{_API}/properties/<uuid:property_ref>/validate")
    def validate_property(property_ref: uuid.UUID) -> Response:
        return jsonify(
            {
                "property_ref": str(property_ref),
                "state": feature1.validate_property(str(property_ref)),
            }
        )

    @blueprint.get(f"{_API}/assistant/capabilities")
    def assistant_capabilities() -> Response:
        return jsonify(
            {
                "feature_key": FEATURE_KEY,
                "tools": list(TOOL_ALLOWLIST),
                "suggested_questions": [
                    "Explain the recorded sales and exclusions in this case.",
                    "What limitations should I consider when reading this median?",
                    "Summarise transaction volume by year without estimating value.",
                ],
                "offline_safe": "Case CRUD and deterministic summaries work without an AI key.",
            }
        )

    @blueprint.post(f"{_API}/assistant/turns")
    def assistant_turn() -> Response:
        try:
            command = AssistantTurn.model_validate(_json_body())
        except ValidationError as exc:
            return _validation_problem("invalid_assistant_turn", exc)
        case_response = store.request("GET", f"{_INTERNAL}/market-cases/{command.case_id}")
        if case_response.status_code >= 400:
            return _relay(case_response)
        objective = (
            f"Explain market case {command.case_id} using only the two allowlisted "
            "Feature 2 tools. Use the deterministic count, median, transaction-volume, "
            "source and exclusion evidence. State missing data and limitations. Never "
            "estimate a property value and never recommend "
            f"whether to buy. User question: {command.message}"
        )
        upstream = ai_mode.create_run(
            {
                "feature_key": FEATURE_KEY,
                "objective": objective,
                "trusted_identifiers": [{"kind": "market_case_id", "value": str(command.case_id)}],
                "prompt_set": "default.v7",
                "tool_allowlist": list(TOOL_ALLOWLIST),
                "limits": {
                    "max_iterations": 4,
                    "max_tool_calls": 6,
                    "time_budget_ms": 120000,
                    "max_model_repairs": 1,
                },
            }
        )
        return _relay(upstream)

    def owned_run(run_id: uuid.UUID) -> tuple[httpx.Response, bool]:
        response = ai_mode.get(f"/api/v1/agent-runs/{run_id}")
        if response.status_code >= 400:
            return response, False
        payload = response.json()
        run = payload.get("run") if isinstance(payload, dict) else None
        owned = (
            isinstance(run, dict)
            and run.get("feature_key") == FEATURE_KEY
            and run.get("tool_allowlist") == list(TOOL_ALLOWLIST)
        )
        return response, owned

    @blueprint.get(f"{_API}/assistant/turns/<uuid:run_id>")
    def assistant_detail(run_id: uuid.UUID) -> Response:
        upstream, owned = owned_run(run_id)
        if upstream.status_code < 400 and not owned:
            return _problem(404, "assistant_turn_not_found", "Assistant turn does not exist")
        return _relay(upstream)

    @blueprint.get(f"{_API}/assistant/turns/<uuid:run_id>/events")
    def assistant_events(run_id: uuid.UUID) -> Response:
        detail, owned = owned_run(run_id)
        if detail.status_code >= 400:
            return _relay(detail)
        if not owned:
            return _problem(404, "assistant_turn_not_found", "Assistant turn does not exist")
        params = {key: value for key in ("after", "limit") if (value := request.args.get(key))}
        return _relay(ai_mode.get(f"/api/v1/agent-runs/{run_id}/events", params=params))

    @blueprint.post(f"{_API}/assistant/turns/<uuid:run_id>/cancel")
    def assistant_cancel(run_id: uuid.UUID) -> Response:
        detail, owned = owned_run(run_id)
        if detail.status_code >= 400:
            return _relay(detail)
        if not owned:
            return _problem(404, "assistant_turn_not_found", "Assistant turn does not exist")
        return _relay(ai_mode.cancel(str(run_id)))

    @blueprint.post(f"{_API}/tools/market.cases.inspect.v1")
    def tool_case() -> Response:
        body = _json_body()
        try:
            case_id = uuid.UUID(str(body.get("market_case_id", "")))
        except ValueError:
            return _problem(422, "invalid_tool_input", "market_case_id must be a UUID")
        response = store.request("GET", f"{_INTERNAL}/market-cases/{case_id}")
        if response.status_code >= 400:
            return _relay(response)
        return jsonify({"market_case": response.json()})

    @blueprint.post(f"{_API}/tools/market.sales.summary.v1")
    def tool_summary() -> Response:
        body = _json_body()
        try:
            case_id = uuid.UUID(str(body.get("market_case_id", "")))
        except ValueError:
            return _problem(422, "invalid_tool_input", "market_case_id must be a UUID")
        value, error = _case_evidence(store, str(case_id))
        if error is not None:
            return error
        assert value is not None
        return jsonify({"summary": value["summary"], "sales": value["sales"]})

    @blueprint.post("/api/data-import/v1/propertyscope-releases")
    def import_release() -> Response | tuple[Response, int]:
        try:
            publication = PublicationRequest.model_validate(_json_body())
        except ValidationError as exc:
            return _validation_problem("invalid_sales_publication", exc)
        compressed = feature1.artifact(publication.artifact_path)
        if hashlib.sha256(compressed).hexdigest() != publication.content_sha256:
            return _problem(
                422, "artifact_checksum_mismatch", "The sales artifact checksum does not match"
            )
        try:
            records = decode_sales_artifact(publication, compressed)
        except ValueError as exc:
            return jsonify(
                {
                    "consumer_operation_id": publication.idempotency_key,
                    "status": "rejected",
                    "schema_version": publication.schema_version,
                    "content_sha256": publication.content_sha256,
                    "rows_received": 0,
                    "rows_accepted": 0,
                    "rows_rejected": 0,
                    "error": {
                        "code": "invalid_sales_artifact",
                        "message": str(exc),
                        "retryable": False,
                        "details": {},
                    },
                }
            ), 422
        imported = store.request("POST", f"{_INTERNAL}/sales/import", json={"records": records})
        if imported.status_code >= 400:
            return _relay(imported)
        return jsonify(
            {
                "consumer_operation_id": publication.idempotency_key,
                "status": "accepted",
                "schema_version": publication.schema_version,
                "content_sha256": publication.content_sha256,
                "rows_received": len(records),
                "rows_accepted": len(records),
                "rows_rejected": 0,
                "error": None,
            }
        )

    return blueprint


def register_error_handlers(app: Flask) -> None:
    app.register_error_handler(
        DependencyUnavailableError,
        lambda error: _problem(503, "dependency_unavailable", str(error)),
    )
    app.register_error_handler(
        ValueError, lambda error: _problem(422, "invalid_request", str(error))
    )
    app.register_error_handler(
        404, lambda _error: _problem(404, "not_found", "Route does not exist")
    )
    app.register_error_handler(
        405, lambda _error: _problem(405, "method_not_allowed", "Method is not allowed")
    )
    app.register_error_handler(
        413, lambda _error: _problem(413, "payload_too_large", "The request body is too large")
    )
