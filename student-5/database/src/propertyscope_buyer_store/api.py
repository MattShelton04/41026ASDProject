"""Authenticated internal HTTP boundary for buyer workspace persistence."""

from __future__ import annotations

import hmac
import sqlite3
import uuid
from typing import Any

from flask import Flask, Response, g, jsonify, request
from werkzeug.exceptions import HTTPException

from propertyscope_buyer_store.configuration import StoreSettings
from propertyscope_buyer_store.domain import (
    InputValidationError,
    validate_case_create,
    validate_case_update,
    validate_note_create,
    validate_note_update,
    validate_property_create,
    validate_property_update,
    validate_task_create,
    validate_task_update,
)
from propertyscope_buyer_store.repository import (
    BuyerStore,
    ConcurrentUpdateError,
    RecordNotFoundError,
)
from shared_contracts import (
    PROBLEM_DETAIL_MEDIA_TYPE,
    REQUEST_ID_HEADER,
    HealthStatus,
    ProblemDetail,
    ReadinessCheckProjection,
    is_valid_request_id,
    project_readiness,
)

_SERVICE = "propertyscope-buyer-store"
_VERSION = "0.1.0"
_API = "/internal/buyer-workspaces/v1"
_TOKEN_HEADER = "X-PropertyScope-Internal-Token"


def _problem(status: int, code: str, detail: str) -> tuple[Response, int]:
    problem = ProblemDetail(
        title=code.replace("_", " ").title(),
        status=status,
        detail=detail,
        instance=request.path,
        code=code,
        request_id=getattr(g, "request_id", None),
    )
    response = jsonify(problem.model_dump(mode="json"))
    response.content_type = PROBLEM_DETAIL_MEDIA_TYPE
    return response, status


def _body() -> object:
    return request.get_json(silent=True)


def _pagination() -> tuple[int, int]:
    try:
        page = int(request.args.get("page", "1"))
        page_size = int(request.args.get("page_size", "50"))
    except ValueError as exc:
        raise InputValidationError("page and page_size must be integers") from exc
    if page < 1 or not 1 <= page_size <= 100:
        raise InputValidationError("page must be positive and page_size must be between 1 and 100")
    return page, page_size


def _created(value: dict[str, Any]) -> tuple[Response, int]:
    return jsonify(value), 201


def _item_or_404(value: dict[str, Any] | None, kind: str) -> dict[str, Any]:
    if value is None:
        raise RecordNotFoundError(f"{kind} does not exist")
    return value


def _deleted_or_404(deleted: bool, record_id: str, kind: str) -> Response:
    if not deleted:
        raise RecordNotFoundError(f"{kind} does not exist")
    return jsonify({"deleted": record_id})


def _integrity_problem(error: sqlite3.IntegrityError) -> tuple[Response, int]:
    message = str(error)
    if "case_property.buyer_case_id, case_property.property_ref" in message:
        return _problem(409, "duplicate_case_property", "That property is already in this case")
    if "case_property_case_mismatch" in message:
        return _problem(
            422,
            "property_case_mismatch",
            "The related property must belong to the same buyer case",
        )
    return _problem(422, "integrity_constraint_failed", "The submitted values violate a constraint")


def register_api(app: Flask, store: BuyerStore, *, settings: StoreSettings) -> None:
    """Register health, correlation, authentication, errors, and CRUD routes."""

    owner_ref = settings.demo_owner_ref

    @app.before_request
    def establish_request_id() -> None:
        supplied = request.headers.get(REQUEST_ID_HEADER, "").strip()
        g.request_id = supplied if is_valid_request_id(supplied) else str(uuid.uuid4())

    @app.before_request
    def require_internal_token() -> tuple[Response, int] | None:
        if not request.path.startswith(_API):
            return None
        supplied = request.headers.get(_TOKEN_HEADER, "")
        if not hmac.compare_digest(supplied.encode(), settings.internal_token.encode()):
            return _problem(401, "unauthorised", "A valid internal token is required")
        return None

    @app.after_request
    def include_request_id(response: Response) -> Response:
        response.headers[REQUEST_ID_HEADER] = g.request_id
        return response

    @app.errorhandler(InputValidationError)
    def invalid_input(error: InputValidationError) -> tuple[Response, int]:
        return _problem(422, "validation_failed", str(error))

    @app.errorhandler(RecordNotFoundError)
    def not_found(error: RecordNotFoundError) -> tuple[Response, int]:
        return _problem(404, "resource_not_found", str(error))

    @app.errorhandler(ConcurrentUpdateError)
    def version_conflict(_error: ConcurrentUpdateError) -> tuple[Response, int]:
        return _problem(409, "version_conflict", "Refresh the resource before saving again")

    @app.errorhandler(sqlite3.IntegrityError)
    def integrity_error(error: sqlite3.IntegrityError) -> tuple[Response, int]:
        return _integrity_problem(error)

    @app.errorhandler(HTTPException)
    def http_error(error: HTTPException) -> tuple[Response, int]:
        status = error.code or 500
        return _problem(status, "http_error", "The requested operation could not be completed")

    @app.errorhandler(Exception)
    def unexpected_error(error: Exception) -> tuple[Response, int]:
        app.logger.exception("Unexpected buyer store request failure", exc_info=error)
        return _problem(500, "internal_error", "The service could not complete the request")

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
        healthy = store.ready()
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

    @app.get(f"{_API}/seed-report")
    def seed_report() -> Response:
        return jsonify(store.seed_report())

    @app.get(f"{_API}/schema/fingerprint")
    def schema_fingerprint() -> Response:
        return jsonify(store.schema_fingerprint())

    @app.get(f"{_API}/buyer-cases")
    def list_cases() -> Response:
        page, page_size = _pagination()
        return jsonify(store.list_cases(owner_ref, page=page, page_size=page_size))

    @app.post(f"{_API}/buyer-cases")
    def create_case() -> tuple[Response, int]:
        return _created(store.create_case(owner_ref, validate_case_create(_body())))

    @app.get(f"{_API}/buyer-cases/<uuid:case_id>")
    def get_case(case_id: uuid.UUID) -> Response:
        return jsonify(_item_or_404(store.get_case(owner_ref, str(case_id)), "buyer case"))

    @app.put(f"{_API}/buyer-cases/<uuid:case_id>")
    def update_case(case_id: uuid.UUID) -> Response:
        version, changes = validate_case_update(_body())
        return jsonify(
            store.update_case(owner_ref, str(case_id), changes, expected_version=version)
        )

    @app.delete(f"{_API}/buyer-cases/<uuid:case_id>")
    def delete_case(case_id: uuid.UUID) -> Response:
        return _deleted_or_404(
            store.delete_case(owner_ref, str(case_id)), str(case_id), "buyer case"
        )

    @app.get(f"{_API}/buyer-cases/<uuid:case_id>/properties")
    def list_properties(case_id: uuid.UUID) -> Response:
        page, page_size = _pagination()
        return jsonify(
            store.list_properties(owner_ref, str(case_id), page=page, page_size=page_size)
        )

    @app.post(f"{_API}/buyer-cases/<uuid:case_id>/properties")
    def create_property(case_id: uuid.UUID) -> tuple[Response, int]:
        return _created(
            store.create_property(owner_ref, str(case_id), validate_property_create(_body()))
        )

    @app.get(f"{_API}/buyer-cases/<uuid:case_id>/properties/<uuid:property_id>")
    def get_property(case_id: uuid.UUID, property_id: uuid.UUID) -> Response:
        item = store.get_property(owner_ref, str(case_id), str(property_id))
        return jsonify(_item_or_404(item, "case property"))

    @app.put(f"{_API}/buyer-cases/<uuid:case_id>/properties/<uuid:property_id>")
    def update_property(case_id: uuid.UUID, property_id: uuid.UUID) -> Response:
        version, changes = validate_property_update(_body())
        return jsonify(
            store.update_property(
                owner_ref,
                str(case_id),
                str(property_id),
                changes,
                expected_version=version,
            )
        )

    @app.delete(f"{_API}/buyer-cases/<uuid:case_id>/properties/<uuid:property_id>")
    def delete_property(case_id: uuid.UUID, property_id: uuid.UUID) -> Response:
        deleted = store.delete_property(owner_ref, str(case_id), str(property_id))
        return _deleted_or_404(deleted, str(property_id), "case property")

    @app.get(f"{_API}/buyer-cases/<uuid:case_id>/notes")
    def list_notes(case_id: uuid.UUID) -> Response:
        page, page_size = _pagination()
        return jsonify(store.list_notes(owner_ref, str(case_id), page=page, page_size=page_size))

    @app.post(f"{_API}/buyer-cases/<uuid:case_id>/notes")
    def create_note(case_id: uuid.UUID) -> tuple[Response, int]:
        return _created(store.create_note(owner_ref, str(case_id), validate_note_create(_body())))

    @app.get(f"{_API}/buyer-cases/<uuid:case_id>/notes/<uuid:note_id>")
    def get_note(case_id: uuid.UUID, note_id: uuid.UUID) -> Response:
        item = store.get_note(owner_ref, str(case_id), str(note_id))
        return jsonify(_item_or_404(item, "case note"))

    @app.put(f"{_API}/buyer-cases/<uuid:case_id>/notes/<uuid:note_id>")
    def update_note(case_id: uuid.UUID, note_id: uuid.UUID) -> Response:
        version, changes = validate_note_update(_body())
        return jsonify(
            store.update_note(
                owner_ref,
                str(case_id),
                str(note_id),
                changes,
                expected_version=version,
            )
        )

    @app.delete(f"{_API}/buyer-cases/<uuid:case_id>/notes/<uuid:note_id>")
    def delete_note(case_id: uuid.UUID, note_id: uuid.UUID) -> Response:
        deleted = store.delete_note(owner_ref, str(case_id), str(note_id))
        return _deleted_or_404(deleted, str(note_id), "case note")

    @app.get(f"{_API}/buyer-cases/<uuid:case_id>/tasks")
    def list_tasks(case_id: uuid.UUID) -> Response:
        page, page_size = _pagination()
        return jsonify(store.list_tasks(owner_ref, str(case_id), page=page, page_size=page_size))

    @app.post(f"{_API}/buyer-cases/<uuid:case_id>/tasks")
    def create_task(case_id: uuid.UUID) -> tuple[Response, int]:
        return _created(store.create_task(owner_ref, str(case_id), validate_task_create(_body())))

    @app.get(f"{_API}/buyer-cases/<uuid:case_id>/tasks/<uuid:task_id>")
    def get_task(case_id: uuid.UUID, task_id: uuid.UUID) -> Response:
        item = store.get_task(owner_ref, str(case_id), str(task_id))
        return jsonify(_item_or_404(item, "case task"))

    @app.put(f"{_API}/buyer-cases/<uuid:case_id>/tasks/<uuid:task_id>")
    def update_task(case_id: uuid.UUID, task_id: uuid.UUID) -> Response:
        version, changes = validate_task_update(_body())
        return jsonify(
            store.update_task(
                owner_ref,
                str(case_id),
                str(task_id),
                changes,
                expected_version=version,
            )
        )

    @app.delete(f"{_API}/buyer-cases/<uuid:case_id>/tasks/<uuid:task_id>")
    def delete_task(case_id: uuid.UUID, task_id: uuid.UUID) -> Response:
        deleted = store.delete_task(owner_ref, str(case_id), str(task_id))
        return _deleted_or_404(deleted, str(task_id), "case task")
