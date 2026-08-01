"""Flask application factory for the shared AI-mode service."""

from importlib.metadata import version

from flask import Flask, Response, jsonify

from shared_contracts import HealthCheck, HealthResponse, HealthStatus

PACKAGE_NAME = "ai-mode"


def create_app() -> Flask:
    """Create an AI-mode application without performing external I/O."""
    app = Flask(__name__)

    @app.get("/health/live")
    def liveness() -> tuple[Response, int]:
        response = HealthResponse(
            service=PACKAGE_NAME,
            status=HealthStatus.HEALTHY,
            version=version(PACKAGE_NAME),
        )
        return jsonify(response.model_dump(mode="json")), 200

    @app.get("/health/ready")
    def readiness() -> tuple[Response, int]:
        response = HealthResponse(
            service=PACKAGE_NAME,
            status=HealthStatus.HEALTHY,
            version=version(PACKAGE_NAME),
            checks={
                "application": HealthCheck(
                    status=HealthStatus.HEALTHY,
                    detail="Application factory initialised",
                )
            },
        )
        return jsonify(response.model_dump(mode="json")), 200

    return app
