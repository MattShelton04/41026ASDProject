"""Flask application factory for the shared AI-mode service."""

from importlib.metadata import PackageNotFoundError, version
from uuid import uuid4

from flask import Flask, Response, g, jsonify, request

from ai_mode.api import api
from ai_mode.configuration import Settings
from ai_mode.services import AppServices, build_services
from shared_contracts import REQUEST_ID_HEADER, HealthCheck, HealthResponse, HealthStatus

PACKAGE_NAME = "ai-mode"


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
    app_services = services or build_services(runtime_settings)
    app.extensions["ai_mode_services"] = app_services
    app.register_blueprint(api)

    @app.before_request
    def establish_request_id() -> None:
        supplied = request.headers.get(REQUEST_ID_HEADER, "").strip()
        g.request_id = supplied[:200] if supplied else str(uuid4())

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

    return app
