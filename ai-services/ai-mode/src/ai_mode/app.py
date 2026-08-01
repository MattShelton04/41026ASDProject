"""Flask application factory for the shared AI-mode service."""

from importlib.metadata import PackageNotFoundError, version

from flask import Flask, Response, jsonify

from shared_contracts import HealthCheck, HealthResponse, HealthStatus

PACKAGE_NAME = "ai-mode"


def _get_package_version() -> str:
    """Return installed package metadata without breaking source-tree execution."""
    try:
        return version(PACKAGE_NAME)
    except PackageNotFoundError:
        return "0+unknown"


def create_app() -> Flask:
    """Create an AI-mode application without performing external I/O."""
    app = Flask(__name__)
    service_version = _get_package_version()

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
        response = HealthResponse(
            service=PACKAGE_NAME,
            status=HealthStatus.HEALTHY,
            version=service_version,
            checks={
                "application": HealthCheck(
                    status=HealthStatus.HEALTHY,
                    detail="Application factory initialised",
                )
            },
        )
        return jsonify(response.model_dump(mode="json")), 200

    return app
