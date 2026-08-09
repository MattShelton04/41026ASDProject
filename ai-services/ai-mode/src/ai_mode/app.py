"""Flask application factory for the shared AI-mode service."""

import logging
from importlib.metadata import PackageNotFoundError, version
from time import monotonic
from typing import cast
from uuid import uuid4

from flask import Flask, Response, g, jsonify, request
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

from agent_core import ConcurrentRunUpdateError
from ai_mode.api import api
from ai_mode.configuration import ConfigurationError, Settings
from ai_mode.evidence import create_evidence_blueprint
from ai_mode.http import problem_response as _problem_response
from ai_mode.observability import configure_structured_logging
from ai_mode.operations import OperationsService, RunReader
from ai_mode.operations_api import create_operations_blueprint
from ai_mode.persistence import PersistenceError
from ai_mode.services import AppServices, build_services
from shared_contracts import (
    AGENT_RUN_ID_HEADER,
    REQUEST_ID_HEADER,
    TRACEPARENT_HEADER,
    HealthCheck,
    HealthResponse,
    HealthStatus,
    is_valid_request_id,
    is_valid_traceparent,
    trace_id_from_traceparent,
)

PACKAGE_NAME = "ai-mode"
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
    if services is None:
        configure_structured_logging(
            service=PACKAGE_NAME,
            environment=runtime_settings.environment,
            level=runtime_settings.log_level,
        )
    app.config["MAX_CONTENT_LENGTH"] = runtime_settings.max_request_bytes
    app_services = services or build_services(runtime_settings)
    app.extensions["ai_mode_services"] = app_services
    app.register_blueprint(api)
    if runtime_settings.operations_enabled:
        assets_path = runtime_settings.operations_assets_path.resolve()
        if not (assets_path.is_dir() and (assets_path / "index.html").is_file()):
            raise ConfigurationError(f"AI-mode operations assets are unavailable: {assets_path}")
        reader = app_services.run_reader
        if reader is None and hasattr(app_services.store, "list_run_snapshots"):
            reader = cast(RunReader, app_services.store)
        if reader is None:
            raise ConfigurationError("AI-mode operations run reader is unavailable")
        app.extensions["ai_mode_operations"] = OperationsService(reader)
        app.register_blueprint(create_operations_blueprint(assets_path))
    if runtime_settings.evidence_access_token is not None:
        app.register_blueprint(create_evidence_blueprint(runtime_settings.evidence_access_token))

    @app.before_request
    def establish_request_id() -> None:
        g.request_started = monotonic()
        supplied = request.headers.get(REQUEST_ID_HEADER, "").strip()
        g.request_id = supplied if is_valid_request_id(supplied) else str(uuid4())
        traceparent = request.headers.get(TRACEPARENT_HEADER, "").strip().lower()
        g.traceparent = traceparent or None

    @app.before_request
    def validate_trace_context() -> tuple[Response, int] | None:
        if g.traceparent is None or is_valid_traceparent(g.traceparent):
            return None
        return _problem_response(
            400,
            "traceparent_invalid",
            "traceparent must use the supported W3C version 00 format",
        )

    @app.after_request
    def include_request_id(response: Response) -> Response:
        response.headers[REQUEST_ID_HEADER] = g.request_id
        status_code = response.status_code
        LOGGER.log(
            logging.ERROR if status_code >= 500 else logging.INFO,
            "HTTP request completed",
            extra={
                "event": "http.request.completed",
                "request_id": g.request_id,
                "run_id": response.headers.get(AGENT_RUN_ID_HEADER),
                "trace_id": trace_id_from_traceparent(g.traceparent),
                "outcome": "failure" if status_code >= 400 else "success",
                "duration_ms": max(0, int((monotonic() - g.request_started) * 1_000)),
                "status_code": status_code,
                "method": request.method,
                "path": request.url_rule.rule if request.url_rule is not None else request.path,
            },
        )
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
        LOGGER.exception(
            "Unhandled AI-mode request failure",
            extra={
                "event": "http.request.unhandled_error",
                "request_id": g.get("request_id"),
                "trace_id": trace_id_from_traceparent(g.get("traceparent")),
                "outcome": "failure",
                "error_code": "internal_error",
            },
        )
        return _problem_response(
            status=500,
            title="Internal server error",
            code="internal_error",
            detail="The request could not be completed",
        )

    return app
