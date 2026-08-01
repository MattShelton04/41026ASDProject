"""Flask application factory for the shared AI-mode service."""

import logging
import re
from importlib.metadata import PackageNotFoundError, version
from uuid import uuid4

from flask import Flask, Response, g, jsonify, request
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

from agent_core import ConcurrentRunUpdateError
from ai_mode.api import api
from ai_mode.configuration import Settings
from ai_mode.evidence import create_evidence_blueprint
from ai_mode.persistence import PersistenceError
from ai_mode.services import AppServices, build_services
from shared_contracts import (
    REQUEST_ID_HEADER,
    TRACEPARENT_HEADER,
    HealthCheck,
    HealthResponse,
    HealthStatus,
    ProblemDetail,
)

PACKAGE_NAME = "ai-mode"
TRACEPARENT_PATTERN = re.compile(r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
LOGGER = logging.getLogger(__name__)


def _get_package_version() -> str:
    """Return installed package metadata without breaking source-tree execution."""
    try:
        return version(PACKAGE_NAME)
    except PackageNotFoundError:
        return "0+unknown"


def create_app(
    settings: Settings | None = None,
    *,
    services: AppServices | None = None,
) -> Flask:
    """Create AI-mode with explicit, replaceable boundary dependencies."""
    app = Flask(__name__)
    service_version = _get_package_version()
    runtime_settings = settings or Settings.from_env()
    app.config["MAX_CONTENT_LENGTH"] = runtime_settings.max_request_bytes
    app_services = services or build_services(runtime_settings)
    app.extensions["ai_mode_services"] = app_services
    app.register_blueprint(api)
    if runtime_settings.evidence_access_token is not None:
        app.register_blueprint(create_evidence_blueprint(runtime_settings.evidence_access_token))

    @app.before_request
    def establish_request_id() -> None:
        supplied = request.headers.get(REQUEST_ID_HEADER, "").strip()
        g.request_id = supplied if REQUEST_ID_PATTERN.fullmatch(supplied) else str(uuid4())
        traceparent = request.headers.get(TRACEPARENT_HEADER, "").strip().lower()
        g.traceparent = traceparent or None

    @app.before_request
    def validate_trace_context() -> tuple[Response, int] | None:
        if g.traceparent is None or _valid_traceparent(g.traceparent):
            return None
        problem = ProblemDetail(
            title="Invalid request",
            status=400,
            detail="traceparent must use the supported W3C version 00 format",
            code="traceparent_invalid",
            instance=request.path,
            request_id=g.request_id,
        )
        response = jsonify(problem.model_dump(mode="json"))
        response.content_type = "application/problem+json"
        return response, 400

    @app.after_request
    def include_request_id(response: Response) -> Response:
        response.headers[REQUEST_ID_HEADER] = g.request_id
        return response

    @app.get("/health/live")
    def liveness() -> tuple[Response, int]:
        response = HealthResponse(
            service=PACKAGE_NAME,
            status=HealthStatus.HEALTHY,
            version=service_version,
        )
        return jsonify(response.model_dump(mode="json")), 200

    @app.get("/health/ready")
    def readiness() -> tuple[Response, int]:
        store_health = app_services.store.health()
        provider_health = app_services.provider.health()
        store_ready = store_health.ready
        overall = (
            HealthStatus.UNHEALTHY
            if not store_ready
            else HealthStatus.HEALTHY
            if provider_health.reachable
            else HealthStatus.DEGRADED
        )
        response = HealthResponse(
            service=PACKAGE_NAME,
            status=overall,
            version=service_version,
            checks={
                "application": HealthCheck(
                    status=HealthStatus.HEALTHY,
                    detail="Application factory initialised",
                ),
                "state_store": HealthCheck(
                    status=HealthStatus.HEALTHY if store_ready else HealthStatus.UNHEALTHY,
                    detail=store_health.detail,
                ),
                "ollama": HealthCheck(
                    status=(
                        HealthStatus.HEALTHY if provider_health.reachable else HealthStatus.DEGRADED
                    ),
                    detail=provider_health.detail,
                ),
            },
        )
        dependencies_ready = store_ready and (
            provider_health.reachable or not runtime_settings.require_ollama_ready
        )
        return jsonify(response.model_dump(mode="json")), 200 if dependencies_ready else 503

    @app.errorhandler(RequestEntityTooLarge)
    def request_too_large(_: RequestEntityTooLarge) -> tuple[Response, int]:
        return _problem_response(
            status=413,
            title="Request too large",
            code="request_too_large",
            detail="Request body exceeds the configured size limit",
        )

    @app.errorhandler(ConcurrentRunUpdateError)
    def concurrent_update(_: ConcurrentRunUpdateError) -> tuple[Response, int]:
        return _problem_response(
            status=409,
            title="Conflict",
            code="run_concurrently_updated",
            detail="Agent run was concurrently updated",
        )

    @app.errorhandler(PersistenceError)
    def persistence_failure(_: PersistenceError) -> tuple[Response, int]:
        return _problem_response(
            status=503,
            title="Service unavailable",
            code="state_store_unavailable",
            detail="Agent workflow state is temporarily unavailable",
        )

    @app.errorhandler(Exception)
    def unexpected_failure(exc: Exception) -> HTTPException | tuple[Response, int]:
        if isinstance(exc, HTTPException):
            return exc
        LOGGER.exception("unhandled AI-mode request failure")
        return _problem_response(
            status=500,
            title="Internal server error",
            code="internal_error",
            detail="The request could not be completed",
        )

    return app


def _valid_traceparent(value: str) -> bool:
    if TRACEPARENT_PATTERN.fullmatch(value) is None:
        return False
    _, trace_id, parent_id, _ = value.split("-")
    return trace_id != "0" * 32 and parent_id != "0" * 16


def _problem_response(*, status: int, title: str, code: str, detail: str) -> tuple[Response, int]:
    problem = ProblemDetail(
        title=title,
        status=status,
        detail=detail,
        code=code,
        instance=request.path,
        request_id=g.get("request_id"),
    )
    response = jsonify(problem.model_dump(mode="json"))
    response.content_type = "application/problem+json"
    return response, status
