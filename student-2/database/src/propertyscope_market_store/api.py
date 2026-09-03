"""Token-guarded HTTP boundary for the Feature 2 SQLite database."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import date
from typing import Any

from flask import Blueprint, Flask, Response, jsonify, request

from propertyscope_market_store.repository import VersionConflictError
from shared_contracts import HealthStatus, ReadinessCheckProjection, project_readiness

_SERVICE = "propertyscope-market-store"
_VERSION = "0.1.0"
_API = "/internal/market-intelligence/v1"
_STATUSES = frozenset({"draft", "active", "complete", "archived"})


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


def _limit(raw: str | None, *, default: int, maximum: int) -> int:
    try:
        return max(1, min(int(raw or default), maximum))
    except ValueError:
        return default


def _valid_date(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _validate_create(body: object) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(body, dict):
        return None, "request body must be a JSON object"
    payload: dict[str, Any] = {}
    for field in ("name", "property_ref", "address_display", "date_from", "date_to"):
        value = body.get(field)
        if not isinstance(value, str) or not value.strip():
            return None, f"{field} is required"
        payload[field] = value.strip()
    if len(payload["name"]) > 120 or len(payload["address_display"]) > 500:
        return None, "name or address_display is too long"
    try:
        uuid.UUID(payload["property_ref"])
    except ValueError:
        return None, "the selected property is invalid"
    if not _valid_date(payload["date_from"]) or not _valid_date(payload["date_to"]):
        return None, "date_from and date_to must be ISO dates"
    if payload["date_from"] > payload["date_to"]:
        return None, "date_from must be on or before date_to"
    status = body.get("status", "draft")
    if status not in _STATUSES:
        return None, "status is not supported"
    filters = body.get("filters", {})
    if not isinstance(filters, dict):
        return None, "filters must be an object"
    notes = body.get("notes", "")
    if not isinstance(notes, str) or len(notes) > 4000:
        return None, "notes must be text no longer than 4000 characters"
    validation = body.get("property_validation_state", "unavailable")
    if not isinstance(validation, str) or not validation:
        return None, "property_validation_state is required"
    payload.update(
        status=status,
        filters=filters,
        notes=notes,
        ai_run_ref=body.get("ai_run_ref"),
        property_validation_state=validation,
    )
    return payload, None


def _validate_update(body: object) -> tuple[dict[str, Any] | None, int | None, str | None]:
    if not isinstance(body, dict):
        return None, None, "request body must be a JSON object"
    version = body.get("version")
    if not isinstance(version, int) or version < 1:
        return None, None, "version must be a positive integer"
    allowed = {
        "name",
        "address_display",
        "date_from",
        "date_to",
        "status",
        "notes",
        "filters",
        "ai_run_ref",
    }
    changes = {key: body[key] for key in allowed if key in body}
    for field in ("name", "address_display"):
        if field in changes and (not isinstance(changes[field], str) or not changes[field].strip()):
            return None, None, f"{field} must be non-empty text"
        if field in changes:
            changes[field] = changes[field].strip()
    if "status" in changes and changes["status"] not in _STATUSES:
        return None, None, "status is not supported"
    if "filters" in changes and not isinstance(changes["filters"], dict):
        return None, None, "filters must be an object"
    if "notes" in changes and (
        not isinstance(changes["notes"], str) or len(changes["notes"]) > 4000
    ):
        return None, None, "notes must be text no longer than 4000 characters"
    if any(
        field in changes and not _valid_date(changes[field]) for field in ("date_from", "date_to")
    ):
        return None, None, "dates must use YYYY-MM-DD"
    return changes, version, None


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
                    detail="Database API is accepting requests",
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
                "database": ReadinessCheckProjection(
                    required=True,
                    status=HealthStatus.HEALTHY if healthy else HealthStatus.UNHEALTHY,
                    detail="SQLite schema ready" if healthy else "SQLite schema unavailable",
                )
            },
        )
        return jsonify(projection.model_dump(mode="json")), projection.http_status


def create_blueprint(store: Any, *, internal_token: str) -> Blueprint:
    blueprint = Blueprint("market_store", __name__)

    @blueprint.before_request
    def require_token() -> tuple[Response, int] | None:
        if request.headers.get("X-PropertyScope-Internal-Token") != internal_token:
            return _problem(401, "unauthorised", "A valid internal token is required")
        return None

    @blueprint.get(f"{_API}/market-cases")
    def list_cases() -> Response:
        return jsonify(
            {
                "items": store.list_cases(
                    limit=_limit(request.args.get("limit"), default=100, maximum=200)
                )
            }
        )

    @blueprint.post(f"{_API}/market-cases")
    def create_case() -> Response | tuple[Response, int]:
        payload, error = _validate_create(request.get_json(silent=True))
        if error:
            return _problem(422, "invalid_market_case", error)
        assert payload is not None
        return jsonify(store.create_case(payload)), 201

    @blueprint.get(f"{_API}/market-cases/<uuid:case_id>")
    def get_case(case_id: uuid.UUID) -> Response | tuple[Response, int]:
        item = store.get_case(str(case_id))
        if item is None:
            return _problem(404, "market_case_not_found", "No market case with that id")
        return jsonify(item)

    @blueprint.put(f"{_API}/market-cases/<uuid:case_id>")
    def update_case(case_id: uuid.UUID) -> Response | tuple[Response, int]:
        changes, version, error = _validate_update(request.get_json(silent=True))
        if error:
            return _problem(422, "invalid_market_case", error)
        assert changes is not None and version is not None
        current = store.get_case(str(case_id))
        if current is None:
            return _problem(404, "market_case_not_found", "No market case with that id")
        date_from = changes.get("date_from", current["date_from"])
        date_to = changes.get("date_to", current["date_to"])
        if date_from > date_to:
            return _problem(422, "invalid_market_case", "date_from must be on or before date_to")
        try:
            updated = store.update_case(str(case_id), changes, expected_version=version)
        except VersionConflictError:
            return _problem(409, "version_conflict", "Refresh this case before saving again")
        assert updated is not None
        return jsonify(updated)

    @blueprint.delete(f"{_API}/market-cases/<uuid:case_id>")
    def delete_case(case_id: uuid.UUID) -> Response | tuple[Response, int]:
        if not store.delete_case(str(case_id)):
            return _problem(404, "market_case_not_found", "No market case with that id")
        return jsonify({"deleted": str(case_id)})

    @blueprint.get(f"{_API}/sales")
    def list_sales() -> Response | tuple[Response, int]:
        property_ref = request.args.get("property_ref", "")
        try:
            uuid.UUID(property_ref)
        except ValueError:
            return _problem(422, "invalid_property_ref", "the selected property is invalid")
        return jsonify(
            {
                "items": store.list_sales(
                    property_ref,
                    limit=_limit(request.args.get("limit"), default=5000, maximum=5000),
                )
            }
        )

    @blueprint.post(f"{_API}/sales/import")
    def import_sales() -> Response | tuple[Response, int]:
        body = request.get_json(silent=True)
        records = body.get("records") if isinstance(body, dict) else None
        if (
            not isinstance(records, list)
            or len(records) > 5000
            or not all(isinstance(item, dict) for item in records)
        ):
            return _problem(
                422, "invalid_sales_import", "records must be an array of at most 5000 objects"
            )
        return jsonify(store.import_sales(records))

    @blueprint.get(f"{_API}/seed-report")
    def seed_report() -> Response:
        return jsonify({"tables": store.table_counts(), "minimum_rows_per_domain_table": 10})

    return blueprint


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(404)
    def not_found(_error: Any) -> tuple[Response, int]:
        return _problem(404, "not_found", "The requested resource was not found")

    @app.errorhandler(405)
    def method_not_allowed(_error: Any) -> tuple[Response, int]:
        return _problem(405, "method_not_allowed", "The method is not allowed here")

    @app.errorhandler(413)
    def too_large(_error: Any) -> tuple[Response, int]:
        return _problem(413, "payload_too_large", "The request body is too large")

    @app.errorhandler(sqlite3.Error)
    def sqlite_error(_error: sqlite3.Error) -> tuple[Response, int]:
        return _problem(500, "database_error", "The database operation could not be completed")
