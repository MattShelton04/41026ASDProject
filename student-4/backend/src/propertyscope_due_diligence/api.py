"""Public HTTP API for the Student 4 due-diligence backend.

Routes proxy the feature-owned database API and add Feature 1 property validation.
Direct CRUD and deterministic evidence continue to work when Feature 1 is
unavailable: an unreachable Feature 1 degrades to an ``unavailable`` state rather
than blocking the request.
"""

from __future__ import annotations

from typing import Any

from flask import Blueprint, Flask, Response, jsonify, request

from shared_contracts import HealthStatus, ReadinessCheckProjection, project_readiness

_SERVICE = "propertyscope-due-diligence"
_VERSION = "0.1.0"
_API = "/api/due-diligence/v1"
_INTERNAL = "/internal/due-diligence/v1"


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


def create_blueprint(store: Any, feature1: Any) -> Blueprint:
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
