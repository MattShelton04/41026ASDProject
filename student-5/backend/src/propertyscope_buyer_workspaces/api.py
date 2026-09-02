"""Public Buyer Case API backed exclusively by the Student 5 database HTTP API."""

from __future__ import annotations

import uuid
from typing import Any

from flask import Flask, Response, g, jsonify, request
from werkzeug.exceptions import HTTPException

from propertyscope_buyer_workspaces.clients import (
    BuyerStoreGateway,
    ClientResponse,
    DatabaseProtocolError,
    DatabaseUnavailableError,
)
from propertyscope_buyer_workspaces.configuration import BackendSettings
from propertyscope_buyer_workspaces.domain import (
    CASE_STATUSES,
    PREFERENCE_ARRAY_FIELDS,
    PublicInputError,
    normalize_preferences,
    validate_case_create,
    validate_case_update,
    validate_pagination,
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

_SERVICE = "propertyscope-buyer-workspaces"
_VERSION = "0.1.0"
_API = "/api/buyer-workspaces/v1"
_PUBLIC_CASE_FIELDS = {
    "id",
    "name",
    "preferences",
    "budget_min_aud",
    "budget_max_aud",
    "target_suburbs",
    "status",
    "created_at",
    "updated_at",
    "version",
}


def _problem(status: int, code: str, detail: str) -> tuple[Response, int]:
    value = ProblemDetail(
        type=f"https://propertyscope.local/problems/{code}",
        title=code.replace("_", " ").title(),
        status=status,
        detail=detail,
        instance=request.path,
        code=code,
        request_id=getattr(g, "request_id", None),
    )
    response = jsonify(value.model_dump(mode="json"))
    response.content_type = PROBLEM_DETAIL_MEDIA_TYPE
    return response, status


def _mapping(response: ClientResponse) -> dict[str, Any]:
    payload = response.json()
    if not isinstance(payload, dict):
        raise DatabaseProtocolError("Database API returned a non-object representation")
    return dict(payload)


def _upstream_problem(response: ClientResponse) -> tuple[Response, int]:
    try:
        payload = _mapping(response)
    except DatabaseProtocolError:
        return _problem(
            502, "database_protocol_error", "The database API returned an invalid error response"
        )
    code = payload.get("code")
    safe_code = code if isinstance(code, str) and code else "database_request_failed"
    safe_detail = {
        "resource_not_found": "Buyer case does not exist",
        "version_conflict": "Refresh the buyer case before saving again",
        "validation_failed": "The submitted buyer case is invalid",
        "integrity_constraint_failed": "The submitted buyer case violates a constraint",
    }.get(safe_code, "The database API could not complete the request")
    return _problem(response.status_code, safe_code, safe_detail)


def _public_case(value: object, expected_owner: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DatabaseProtocolError("Database API returned an invalid buyer case")
    required = _PUBLIC_CASE_FIELDS | {"owner_ref"}
    if not required.issubset(value):
        raise DatabaseProtocolError("Database API returned an incomplete buyer case")
    if value.get("owner_ref") != expected_owner:
        raise DatabaseProtocolError("Database API returned a buyer case outside the owner scope")
    case_id = value["id"]
    name = value["name"]
    minimum = value["budget_min_aud"]
    maximum = value["budget_max_aud"]
    status = value["status"]
    created_at = value["created_at"]
    updated_at = value["updated_at"]
    version = value["version"]
    if not isinstance(case_id, str):
        raise DatabaseProtocolError("Database API returned an invalid buyer case id")
    try:
        uuid.UUID(case_id)
    except ValueError as exc:
        raise DatabaseProtocolError("Database API returned an invalid buyer case id") from exc
    if not isinstance(name, str) or not name.strip():
        raise DatabaseProtocolError("Database API returned an invalid buyer case name")
    if any(
        candidate is not None
        and (isinstance(candidate, bool) or not isinstance(candidate, int) or candidate < 0)
        for candidate in (minimum, maximum)
    ):
        raise DatabaseProtocolError("Database API returned an invalid buyer case budget")
    if minimum is not None and maximum is not None and maximum < minimum:
        raise DatabaseProtocolError("Database API returned an invalid buyer case budget range")
    if status not in CASE_STATUSES:
        raise DatabaseProtocolError("Database API returned an invalid buyer case status")
    if not isinstance(created_at, str) or not isinstance(updated_at, str):
        raise DatabaseProtocolError("Database API returned invalid buyer case timestamps")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise DatabaseProtocolError("Database API returned an invalid buyer case version")
    raw_preferences = value["preferences"]
    if not isinstance(raw_preferences, dict):
        raise DatabaseProtocolError("Database API returned invalid buyer preferences")
    try:
        preferences = normalize_preferences(raw_preferences)
    except PublicInputError as exc:
        raise DatabaseProtocolError("Database API returned invalid buyer preferences") from exc
    if any(
        field in preferences and preferences[field] != raw_preferences.get(field)
        for field in PREFERENCE_ARRAY_FIELDS
    ):
        raise DatabaseProtocolError("Database API returned non-canonical buyer preferences")
    target_suburbs = value["target_suburbs"]
    if not isinstance(target_suburbs, list):
        raise DatabaseProtocolError("Database API returned invalid target suburbs")
    projected_suburbs: list[dict[str, str]] = []
    for suburb in target_suburbs:
        if not isinstance(suburb, dict) or set(suburb) != {"state", "locality"}:
            raise DatabaseProtocolError("Database API returned invalid target suburbs")
        state = suburb.get("state")
        locality = suburb.get("locality")
        if (
            state != "NSW"
            or not isinstance(locality, str)
            or not locality.strip()
            or len(locality.strip()) > 100
        ):
            raise DatabaseProtocolError("Database API returned invalid target suburbs")
        projected_suburbs.append({"state": state, "locality": locality})
    return {
        "id": case_id,
        "name": name,
        "preferences": preferences,
        "budget_min_aud": minimum,
        "budget_max_aud": maximum,
        "target_suburbs": projected_suburbs,
        "status": status,
        "created_at": created_at,
        "updated_at": updated_at,
        "version": version,
    }


def _positive_integer(value: object, field: str, *, allow_zero: bool = False) -> int:
    minimum = 0 if allow_zero else 1
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise DatabaseProtocolError(f"Database API returned an invalid {field}")
    return value


def _request_body() -> object:
    return request.get_json(silent=True)


def register_api(
    app: Flask,
    store: BuyerStoreGateway,
    *,
    settings: BackendSettings,
) -> None:
    """Register public CRUD, health, correlation, and safe error handling."""

    @app.before_request
    def establish_request_id() -> None:
        supplied = request.headers.get(REQUEST_ID_HEADER, "").strip()
        g.request_id = supplied if is_valid_request_id(supplied) else str(uuid.uuid4())

    @app.after_request
    def include_request_id(response: Response) -> Response:
        response.headers[REQUEST_ID_HEADER] = g.request_id
        return response

    @app.errorhandler(PublicInputError)
    def invalid_input(error: PublicInputError) -> tuple[Response, int]:
        return _problem(422, "validation_failed", str(error))

    @app.errorhandler(DatabaseUnavailableError)
    def database_unavailable(_error: DatabaseUnavailableError) -> tuple[Response, int]:
        return _problem(
            503,
            "database_unavailable",
            "Buyer cases are temporarily unavailable; please try again",
        )

    @app.errorhandler(DatabaseProtocolError)
    def database_protocol_error(_error: DatabaseProtocolError) -> tuple[Response, int]:
        return _problem(
            502,
            "database_protocol_error",
            "The buyer case service received an invalid dependency response",
        )

    @app.errorhandler(HTTPException)
    def http_error(error: HTTPException) -> tuple[Response, int]:
        return _problem(
            error.code or 500,
            "http_error",
            "The requested operation could not be completed",
        )

    @app.errorhandler(Exception)
    def unexpected_error(error: Exception) -> tuple[Response, int]:
        app.logger.exception("Unexpected public buyer workspace failure", exc_info=error)
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
                    detail="Buyer workspace backend is accepting requests",
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
                    detail=(
                        "Buyer workspace database API reachable"
                        if healthy
                        else "Buyer workspace database API unavailable"
                    ),
                )
            },
        )
        return jsonify(projection.model_dump(mode="json")), projection.http_status

    @app.get(f"{_API}/buyer-cases")
    def list_cases() -> Response | tuple[Response, int]:
        pagination = validate_pagination(request.args.get("page"), request.args.get("page_size"))
        upstream = store.list_cases(**pagination, request_id=g.request_id)
        if upstream.status_code >= 400:
            return _upstream_problem(upstream)
        payload = _mapping(upstream)
        items = payload.get("items")
        if not isinstance(items, list):
            raise DatabaseProtocolError("Database API list is missing items")
        page = _positive_integer(payload.get("page"), "page")
        page_size = _positive_integer(payload.get("page_size"), "page_size")
        if page_size > 100:
            raise DatabaseProtocolError("Database API returned an invalid page_size")
        total = _positive_integer(payload.get("total"), "total", allow_zero=True)
        if len(items) > page_size or total < len(items):
            raise DatabaseProtocolError("Database API returned an inconsistent list envelope")
        return jsonify(
            {
                "items": [_public_case(item, settings.demo_owner_ref) for item in items],
                "page": page,
                "page_size": page_size,
                "total": total,
            }
        )

    @app.post(f"{_API}/buyer-cases")
    def create_case() -> Response | tuple[Response, int]:
        command = validate_case_create(_request_body())
        upstream = store.create_case(command, request_id=g.request_id)
        if upstream.status_code >= 400:
            return _upstream_problem(upstream)
        return jsonify(_public_case(_mapping(upstream), settings.demo_owner_ref)), 201

    @app.get(f"{_API}/buyer-cases/<uuid:case_id>")
    def get_case(case_id: uuid.UUID) -> Response | tuple[Response, int]:
        upstream = store.get_case(str(case_id), request_id=g.request_id)
        if upstream.status_code >= 400:
            return _upstream_problem(upstream)
        return jsonify(_public_case(_mapping(upstream), settings.demo_owner_ref))

    @app.put(f"{_API}/buyer-cases/<uuid:case_id>")
    def update_case(case_id: uuid.UUID) -> Response | tuple[Response, int]:
        command = validate_case_update(_request_body())
        upstream = store.update_case(str(case_id), command, request_id=g.request_id)
        if upstream.status_code >= 400:
            return _upstream_problem(upstream)
        return jsonify(_public_case(_mapping(upstream), settings.demo_owner_ref))

    @app.delete(f"{_API}/buyer-cases/<uuid:case_id>")
    def delete_case(case_id: uuid.UUID) -> Response | tuple[Response, int]:
        upstream = store.delete_case(str(case_id), request_id=g.request_id)
        if upstream.status_code >= 400:
            return _upstream_problem(upstream)
        payload = _mapping(upstream)
        if payload.get("deleted") != str(case_id) or set(payload) != {"deleted"}:
            raise DatabaseProtocolError("Database API returned an invalid deletion confirmation")
        return jsonify({"deleted": str(case_id)})
