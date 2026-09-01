"""Internal HTTP API for the Student 4 due-diligence database service.

This service owns the PostgreSQL credentials. Every internal route requires the
shared internal token; the feature backend calls these routes over HTTP and never
connects to PostgreSQL directly.
"""

from __future__ import annotations

from typing import Any

from flask import Blueprint, Flask, Response, jsonify, request

from shared_contracts import HealthStatus, ReadinessCheckProjection, project_readiness

_SERVICE = "propertyscope-due-diligence-store"
_VERSION = "0.1.0"
_API = "/internal/due-diligence/v1"
_STATUS_VALUES = frozenset({"draft", "in_review", "completed", "archived"})
_DISPOSITION_VALUES = frozenset({"undecided", "proceed", "hold", "do_not_proceed"})


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


def _bounded_limit(raw: str | None, *, default: int, maximum: int) -> int:
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(1, min(value, maximum))


def _validate_new_review(body: Any) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(body, dict):
        return None, "request body must be a JSON object"
    payload: dict[str, Any] = {}
    for field in ("property_ref", "address_display", "title"):
        value = body.get(field)
        if not isinstance(value, str) or not value.strip():
            return None, f"{field} is required"
        payload[field] = value.strip()
    status = body.get("status", "draft")
    if status not in _STATUS_VALUES:
        return None, "status is not a supported value"
    disposition = body.get("disposition", "undecided")
    if disposition not in _DISPOSITION_VALUES:
        return None, "disposition is not a supported value"
    checklist = body.get("checklist", [])
    questions = body.get("verification_questions", [])
    if not isinstance(checklist, list) or not isinstance(questions, list):
        return None, "checklist and verification_questions must be arrays"
    payload["status"] = status
    payload["disposition"] = disposition
    payload["checklist"] = checklist
    payload["verification_questions"] = questions
    payload["notes"] = body.get("notes") or ""
    if body.get("ai_run_ref") is not None:
        payload["ai_run_ref"] = str(body["ai_run_ref"])
    return payload, None


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
                    detail="Due-diligence database service is accepting requests",
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
                "database": ReadinessCheckProjection(
                    required=True,
                    status=HealthStatus.HEALTHY if healthy else HealthStatus.UNHEALTHY,
                    detail="PostgreSQL reachable" if healthy else "PostgreSQL unavailable",
                )
            },
        )
        return jsonify(projection.model_dump(mode="json")), projection.http_status


def create_blueprint(store: Any, *, internal_token: str) -> Blueprint:
    """Create the token-guarded internal data blueprint."""
    blueprint = Blueprint("due_diligence_store", __name__)

    @blueprint.before_request
    def _require_token() -> tuple[Response, int] | None:
        if request.headers.get("X-PropertyScope-Internal-Token") != internal_token:
            return _problem(401, "unauthorised", "A valid internal token is required")
        return None

    @blueprint.get(f"{_API}/site-reviews")
    def list_site_reviews() -> Response:
        limit = _bounded_limit(request.args.get("limit"), default=50, maximum=200)
        return jsonify({"items": store.list_site_reviews(limit=limit)})

    @blueprint.post(f"{_API}/site-reviews")
    def create_site_review() -> tuple[Response, int]:
        payload, error = _validate_new_review(request.get_json(silent=True))
        if error is not None:
            return _problem(422, "invalid_site_review", error)
        assert payload is not None
        return jsonify(store.create_site_review(payload)), 201

    @blueprint.get(f"{_API}/site-reviews/<review_id>")
    def get_site_review(review_id: str) -> Response | tuple[Response, int]:
        review = store.get_site_review(review_id)
        if review is None:
            return _problem(404, "site_review_not_found", "No site review with that id")
        return jsonify(review)

    @blueprint.put(f"{_API}/site-reviews/<review_id>")
    def update_site_review(review_id: str) -> Response | tuple[Response, int]:
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return _problem(422, "invalid_site_review", "request body must be a JSON object")
        if "status" in body and body["status"] not in _STATUS_VALUES:
            return _problem(422, "invalid_site_review", "status is not a supported value")
        if "disposition" in body and body["disposition"] not in _DISPOSITION_VALUES:
            return _problem(422, "invalid_site_review", "disposition is not a supported value")
        changes = {
            field: body[field]
            for field in (
                "title",
                "status",
                "disposition",
                "notes",
                "ai_run_ref",
                "checklist",
                "verification_questions",
            )
            if field in body
        }
        updated = store.update_site_review(review_id, changes)
        if updated is None:
            return _problem(404, "site_review_not_found", "No site review with that id")
        return jsonify(updated)

    @blueprint.delete(f"{_API}/site-reviews/<review_id>")
    def delete_site_review(review_id: str) -> Response | tuple[Response, int]:
        if store.delete_site_review(review_id):
            return jsonify({"deleted": review_id})
        return _problem(404, "site_review_not_found", "No site review with that id")

    @blueprint.get(f"{_API}/properties/<property_ref>/constraints")
    def list_constraints(property_ref: str) -> Response:
        return jsonify({"items": store.list_constraint_observations(property_ref)})

    @blueprint.get(f"{_API}/properties/<property_ref>/buildings")
    def list_buildings(property_ref: str) -> Response:
        return jsonify({"items": store.list_building_observations(property_ref)})

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
