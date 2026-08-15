"""Flagged HTTP and static-asset surface for the AI-mode operations interface."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import cast
from uuid import UUID

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    jsonify,
    request,
    send_from_directory,
)
from pydantic import TypeAdapter, ValidationError

from ai_mode.http import problem_response as _problem
from ai_mode.operations import (
    InvalidRunCursorError,
    OperationsService,
    RunListQuery,
    decode_run_cursor,
)
from ai_mode.services import AppServices
from shared_contracts import (
    AGENT_RUN_ID_HEADER,
    DEFAULT_RUN_PAGE_SIZE,
    MAX_RUN_PAGE_SIZE,
    RunStatus,
)
from shared_contracts.agent import Identifier

ALLOWED_QUERY_PARAMETERS = frozenset({"status", "feature_key", "model_profile", "cursor", "limit"})
ALLOWED_ASSETS = frozenset({"app.js", "polling.js", "styles.css"})
ALLOWED_DESIGN_SYSTEM_ASSETS = frozenset({"tokens.css"})
IDENTIFIER_ADAPTER = TypeAdapter(Identifier)


def create_operations_blueprint(assets_path: Path) -> Blueprint:
    """Create the interface only after its feature flag and assets are validated."""
    blueprint = Blueprint("ai_mode_operations", __name__)
    design_system_path = assets_path.parent.parent / "design-system"

    @blueprint.get("/api/v1/agent-runs")
    def list_agent_runs() -> tuple[Response, int]:
        unexpected = set(request.args).difference(ALLOWED_QUERY_PARAMETERS)
        if unexpected:
            return _problem(
                400,
                "run_filter_invalid",
                f"Unsupported run filter: {sorted(unexpected)[0]}",
            )
        raw_statuses = request.args.getlist("status")
        if len(raw_statuses) > len(RunStatus):
            return _problem(400, "run_filter_invalid", "Too many status filters")
        try:
            statuses = tuple(RunStatus(value) for value in raw_statuses)
        except ValueError:
            return _problem(400, "run_filter_invalid", "Run status filter is invalid")
        try:
            limit = int(request.args.get("limit", str(DEFAULT_RUN_PAGE_SIZE)))
        except ValueError:
            return _problem(400, "run_filter_invalid", "Run page limit must be an integer")
        if not 1 <= limit <= MAX_RUN_PAGE_SIZE:
            return _problem(
                400,
                "run_filter_invalid",
                f"Run page limit must be between 1 and {MAX_RUN_PAGE_SIZE}",
            )
        try:
            feature_key = _optional_identifier("feature_key")
            model_profile = _optional_identifier("model_profile")
        except ValidationError:
            return _problem(400, "run_filter_invalid", "Run identifier filter is invalid")
        cursor_created_at = None
        cursor_id = None
        raw_cursor = request.args.get("cursor")
        if raw_cursor is not None:
            try:
                cursor_created_at, cursor_id = decode_run_cursor(raw_cursor)
            except InvalidRunCursorError:
                return _problem(400, "run_cursor_invalid", "Run cursor is invalid")
        page = _operations().list_runs(
            RunListQuery(
                statuses=statuses,
                feature_key=feature_key,
                model_profile=model_profile,
                cursor_created_at=cursor_created_at,
                cursor_id=cursor_id,
                limit=limit,
            ),
            as_of=_services_clock_now(),
        )
        return jsonify(page.model_dump(mode="json")), 200

    @blueprint.get("/api/v1/operations/agent-runs/<uuid:run_id>")
    def get_agent_run_evidence(run_id: UUID) -> tuple[Response, int] | Response:
        detail = _operations().get_evidence(run_id, as_of=_services_clock_now())
        if detail is None:
            return _problem(404, "agent_run_not_found", "Agent run does not exist")
        etag = f"{run_id}:{detail.run.version}"
        if request.if_none_match.contains_weak(etag):
            response = Response(status=304)
        else:
            response = jsonify(detail.model_dump(mode="json"))
            response.set_etag(etag, weak=True)
        response.headers[AGENT_RUN_ID_HEADER] = str(run_id)
        response.headers["Cache-Control"] = "private, no-cache"
        return response

    @blueprint.get("/operations/ai-mode/")
    def dashboard() -> Response:
        response = send_from_directory(assets_path, "index.html")
        response.headers["Cache-Control"] = "no-store"
        return _secure_static_response(response)

    @blueprint.get("/operations/ai-mode/assets/<path:filename>")
    def dashboard_asset(filename: str) -> Response:
        if filename not in ALLOWED_ASSETS:
            abort(404)
        response = send_from_directory(assets_path, filename)
        response.headers["Cache-Control"] = "public, max-age=300"
        return _secure_static_response(response)

    @blueprint.get("/operations/ai-mode/design-system/<path:filename>")
    def dashboard_design_system_asset(filename: str) -> Response:
        if filename not in ALLOWED_DESIGN_SYSTEM_ASSETS:
            abort(404)
        response = send_from_directory(design_system_path, filename)
        response.headers["Cache-Control"] = "public, max-age=300"
        return _secure_static_response(response)

    return blueprint


def _operations() -> OperationsService:
    return cast(OperationsService, current_app.extensions["ai_mode_operations"])


def _services_clock_now() -> datetime:
    services = cast(AppServices, current_app.extensions["ai_mode_services"])
    return services.clock.now()


def _optional_identifier(name: str) -> str | None:
    value = request.args.get(name)
    return IDENTIFIER_ADAPTER.validate_python(value) if value is not None else None


def _secure_static_response(response: Response) -> Response:
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; "
        "form-action 'none'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response
