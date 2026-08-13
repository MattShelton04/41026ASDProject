"""PropertyScope Data Platform control API application factory."""

from __future__ import annotations

import os

from flask import Flask, request

from propertyscope_data_platform.api import create_blueprint, register_error_handlers
from propertyscope_data_platform.clients import AiModeClient, DataStoreClient


def create_app(
    *,
    store_client: DataStoreClient | None = None,
    ai_mode_client: AiModeClient | None = None,
) -> Flask:
    """Create the credential-free Feature 1 backend."""
    store = store_client or DataStoreClient(
        os.environ.get("PROPERTYSCOPE_DATABASE_API_URL", "http://propertyscope-database-api:5202"),
        os.environ.get("PROPERTYSCOPE_INTERNAL_TOKEN", "local-development-only"),
    )
    ai_mode = ai_mode_client or AiModeClient(
        os.environ.get("AI_MODE_BASE_URL", "http://ai-mode:5005")
    )
    app = Flask("propertyscope-data-platform")
    app.config["MAX_CONTENT_LENGTH"] = int(
        os.environ.get("PROPERTYSCOPE_MAX_REQUEST_BYTES", "262144")
    )
    app.register_blueprint(create_blueprint(store, ai_mode))
    worker_token = os.environ.get("PROPERTYSCOPE_RUNNER_TOKEN", "local-runner-only")

    @app.before_request
    def protect_worker_api() -> tuple[dict[str, object], int] | None:
        if (
            request.path.startswith("/internal/data-platform/v1/worker/")
            and request.headers.get("X-PropertyScope-Runner-Token") != worker_token
        ):
            return {
                "status": 401,
                "code": "unauthorised",
                "detail": "Runner credential is required",
            }, 401
        return None

    register_error_handlers(app)
    return app
