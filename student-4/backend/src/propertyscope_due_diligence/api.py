"""Public HTTP API for the Student 4 due-diligence backend.

Routes proxy the feature-owned database API and add Feature 1 property validation.
Direct CRUD and deterministic evidence continue to work when Feature 1 is
unavailable: an unreachable Feature 1 degrades to an ``unavailable`` state rather
than blocking the request.
"""

from __future__ import annotations

from typing import Any

from flask import Blueprint, Flask, Response, jsonify, request

from propertyscope_due_diligence.clients import DependencyUnavailableError
from propertyscope_due_diligence.map_layers import build_map
from shared_contracts import HealthStatus, ReadinessCheckProjection, project_readiness

_SERVICE = "propertyscope-due-diligence"
_VERSION = "0.1.0"
_API = "/api/due-diligence/v1"
_INTERNAL = "/internal/due-diligence/v1"
FEATURE_KEY = "student-4-due-diligence"
TOOL_ALLOWLIST = ("duediligence.review.inspect.v1", "duediligence.evidence.summary.v1")
_SUGGESTED_QUESTIONS = (
    "Generate professional-verification questions for this site review.",
    "What planning and environmental evidence still needs professional checking?",
    "Which strata or building matters should a buyer confirm before proceeding?",
)


def _problem(status: int, code: str, detail: str) -> tuple[Response, int]:
    response = jsonify(
        {
            "type": "about:blank",
            "title": code.replace("_", " ").title(),
            "status": status,
            "detail": detail,
            "code": code,
        }
    )
    response.mimetype = "application/problem+json"
    return response, status


def _relay(response: Any) -> Response:
    """Return a Flask response mirroring a downstream database-API response."""
    return Response(
        response.content,
        status=response.status_code,
        content_type=response.headers.get("content-type", "application/json"),
    )


def register_health(app: Flask, store: Any) -> None:
    """Register unauthenticated liveness and readiness endpoints."""

    @app.get("/health/live")
    def live() -> tuple[Response, int]:
        projection = project_readiness(
            service=_SERVICE,
            version=_VERSION,
            checks={
                "process": ReadinessCheckProjection(
                    required=True,
                    status=HealthStatus.HEALTHY,
                    detail="Due-diligence backend is accepting requests",
                )
            },
        )
        return jsonify(projection.model_dump(mode="json")), projection.http_status

    @app.get("/health/ready")
    def ready() -> tuple[Response, int]:
        healthy = store.ready()
        projection = project_readiness(
            service=_SERVICE,
            version=_VERSION,
            checks={
                "database_api": ReadinessCheckProjection(
                    required=True,
                    status=HealthStatus.HEALTHY if healthy else HealthStatus.UNHEALTHY,
                    detail="Database API reachable" if healthy else "Database API unavailable",
                )
            },
        )
        return jsonify(projection.model_dump(mode="json")), projection.http_status


def create_blueprint(store: Any, feature1: Any, ai_mode: Any) -> Blueprint:
    """Create the public due-diligence API blueprint."""
    blueprint = Blueprint("due_diligence", __name__)

    @blueprint.get(f"{_API}/site-reviews")
    def list_site_reviews() -> Response:
        return _relay(store.request("GET", f"{_INTERNAL}/site-reviews", params=request.args))

    @blueprint.post(f"{_API}/site-reviews")
    def create_site_review() -> Response | tuple[Response, int]:
        body = request.get_json(silent=True)
        if isinstance(body, dict):
            reference = body.get("property_ref")
            if (
                isinstance(reference, str)
                and reference.strip()
                and feature1.validate(reference.strip()) == "not_found"
            ):
                return _problem(
                    422,
                    "unknown_property",
                    "The property reference was not found in Feature 1",
                )
        return _relay(store.request("POST", f"{_INTERNAL}/site-reviews", json=body))

    @blueprint.get(f"{_API}/site-reviews/<review_id>")
    def get_site_review(review_id: str) -> Response:
        return _relay(store.request("GET", f"{_INTERNAL}/site-reviews/{review_id}"))

    @blueprint.put(f"{_API}/site-reviews/<review_id>")
    def update_site_review(review_id: str) -> Response:
        return _relay(
            store.request(
                "PUT", f"{_INTERNAL}/site-reviews/{review_id}", json=request.get_json(silent=True)
            )
        )

    @blueprint.delete(f"{_API}/site-reviews/<review_id>")
    def delete_site_review(review_id: str) -> Response:
        return _relay(store.request("DELETE", f"{_INTERNAL}/site-reviews/{review_id}"))

    @blueprint.get(f"{_API}/site-reviews/<review_id>/evidence")
    def site_review_evidence(review_id: str) -> Response | tuple[Response, int]:
        review_response = store.request("GET", f"{_INTERNAL}/site-reviews/{review_id}")
        if review_response.status_code != 200:
            return _relay(review_response)
        review = review_response.json()
        reference = review["property_ref"]
        constraints = store.request("GET", f"{_INTERNAL}/properties/{reference}/constraints").json()
        buildings = store.request("GET", f"{_INTERNAL}/properties/{reference}/buildings").json()
        return jsonify(
            {
                "site_review": review,
                "constraints": constraints.get("items", []),
                "buildings": buildings.get("items", []),
            }
        )

    @blueprint.get(f"{_API}/properties/<property_ref>/validate")
    def validate_property(property_ref: str) -> Response:
        return jsonify({"property_ref": property_ref, "state": feature1.validate(property_ref)})

    @blueprint.get(f"{_API}/properties/search")
    def search_properties() -> Response | tuple[Response, int]:
        query = (request.args.get("q") or "").strip()
        if len(query) < 3:
            return _problem(422, "invalid_query", "Enter at least three characters to search")
        try:
            limit = int(request.args.get("limit", "8"))
        except ValueError:
            limit = 8
        limit = min(max(limit, 1), 20)
        return jsonify(feature1.search(query, limit))

    @blueprint.get(f"{_API}/site-reviews/<review_id>/map")
    def site_review_map(review_id: str) -> Response:
        review_response = store.request("GET", f"{_INTERNAL}/site-reviews/{review_id}")
        if review_response.status_code != 200:
            return _relay(review_response)
        review = review_response.json()
        reference = review["property_ref"]
        coordinates = feature1.coordinates(reference)
        if coordinates is None:
            return jsonify(
                {
                    "available": False,
                    "detail": "No verified coordinate is available for this property.",
                }
            )
        longitude, latitude = coordinates
        constraints = (
            store.request("GET", f"{_INTERNAL}/properties/{reference}/constraints")
            .json()
            .get("items", [])
        )
        return jsonify(build_map(longitude, latitude, review, constraints))

    # --- Bounded AI-mode assistant: a Plan -> Act -> Observe -> Adapt question pack ---

    @blueprint.get(f"{_API}/assistant/capabilities")
    def assistant_capabilities() -> Response:
        return jsonify(
            {
                "feature_key": FEATURE_KEY,
                "tools": list(TOOL_ALLOWLIST),
                "suggested_questions": list(_SUGGESTED_QUESTIONS),
                "offline_safe": (
                    "Site-review CRUD, evidence and the map work without an AI credential."
                ),
            }
        )

    @blueprint.post(f"{_API}/assistant/turns")
    def assistant_turn() -> Response | tuple[Response, int]:
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return _problem(422, "invalid_assistant_turn", "Request body must be a JSON object")
        review_id = str(body.get("review_id", "")).strip()
        if not review_id:
            return _problem(422, "invalid_assistant_turn", "review_id is required")
        message = str(body.get("message") or "").strip()
        review_response = store.request("GET", f"{_INTERNAL}/site-reviews/{review_id}")
        if review_response.status_code >= 400:
            return _relay(review_response)
        objective = (
            f"Generate a bounded pack of professional-verification questions for site review "
            f"{review_id}, using only the two allowlisted Feature 4 tools. Inspect the review "
            "and its planning, environmental, strata and building evidence. In the findings, "
            "phrase each item as a specific question the buyer should ask a suitably qualified "
            "professional, grounded in the confirmed, partial-coverage, non-intersection and "
            "unavailable evidence states, and prioritise evidence that is unavailable or only "
            "partially covered. Do not certify compliance, safety or legal suitability, and do "
            "not give legal advice."
        )
        if message:
            objective = f"{objective} User request: {message}"
        try:
            upstream = ai_mode.create_run(
                {
                    "feature_key": FEATURE_KEY,
                    "objective": objective,
                    "trusted_identifiers": [{"kind": "site_review_id", "value": review_id}],
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
        except DependencyUnavailableError as exc:
            return _problem(503, "ai_mode_unavailable", str(exc))
        return _relay(upstream)

    def _owned_run(run_id: str) -> tuple[Any, bool]:
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

    @blueprint.get(f"{_API}/assistant/turns/<run_id>")
    def assistant_detail(run_id: str) -> Response:
        try:
            upstream, owned = _owned_run(run_id)
        except DependencyUnavailableError as exc:
            return _problem(503, "ai_mode_unavailable", str(exc))
        if upstream.status_code < 400 and not owned:
            return _problem(404, "assistant_turn_not_found", "Assistant turn does not exist")
        return _relay(upstream)

    @blueprint.get(f"{_API}/assistant/turns/<run_id>/events")
    def assistant_events(run_id: str) -> Response:
        try:
            detail, owned = _owned_run(run_id)
            if detail.status_code >= 400:
                return _relay(detail)
            if not owned:
                return _problem(404, "assistant_turn_not_found", "Assistant turn does not exist")
            params = {key: value for key in ("after", "limit") if (value := request.args.get(key))}
            return _relay(ai_mode.get(f"/api/v1/agent-runs/{run_id}/events", params=params))
        except DependencyUnavailableError as exc:
            return _problem(503, "ai_mode_unavailable", str(exc))

    @blueprint.post(f"{_API}/assistant/turns/<run_id>/cancel")
    def assistant_cancel(run_id: str) -> Response:
        try:
            detail, owned = _owned_run(run_id)
            if detail.status_code >= 400:
                return _relay(detail)
            if not owned:
                return _problem(404, "assistant_turn_not_found", "Assistant turn does not exist")
            return _relay(ai_mode.cancel(run_id))
        except DependencyUnavailableError as exc:
            return _problem(503, "ai_mode_unavailable", str(exc))

    # Read-only tools the shared AI-mode service calls back into this backend.

    @blueprint.post(f"{_API}/tools/duediligence.review.inspect.v1")
    def tool_review_inspect() -> Response:
        body = request.get_json(silent=True) or {}
        review_id = str(body.get("site_review_id", "")).strip()
        response = store.request("GET", f"{_INTERNAL}/site-reviews/{review_id}")
        if response.status_code >= 400:
            return _relay(response)
        return jsonify({"site_review": response.json()})

    @blueprint.post(f"{_API}/tools/duediligence.evidence.summary.v1")
    def tool_evidence_summary() -> Response:
        body = request.get_json(silent=True) or {}
        review_id = str(body.get("site_review_id", "")).strip()
        review_response = store.request("GET", f"{_INTERNAL}/site-reviews/{review_id}")
        if review_response.status_code >= 400:
            return _relay(review_response)
        reference = review_response.json()["property_ref"]
        constraints = (
            store.request("GET", f"{_INTERNAL}/properties/{reference}/constraints")
            .json()
            .get("items", [])
        )
        buildings = (
            store.request("GET", f"{_INTERNAL}/properties/{reference}/buildings")
            .json()
            .get("items", [])
        )
        return jsonify({"constraints": constraints, "buildings": buildings})

    return blueprint


def register_error_handlers(app: Flask) -> None:
    """Return Problem Details bodies for the common error statuses."""

    @app.errorhandler(404)
    def _not_found(_error: Any) -> tuple[Response, int]:
        return _problem(404, "not_found", "The requested resource was not found")

    @app.errorhandler(405)
    def _method_not_allowed(_error: Any) -> tuple[Response, int]:
        return _problem(405, "method_not_allowed", "The method is not allowed here")

    @app.errorhandler(413)
    def _too_large(_error: Any) -> tuple[Response, int]:
        return _problem(413, "payload_too_large", "The request body is too large")
