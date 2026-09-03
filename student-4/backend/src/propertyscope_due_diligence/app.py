"""Flask application factory for the Student 4 due-diligence backend."""

from __future__ import annotations

import os
from typing import Any

from flask import Flask

from propertyscope_due_diligence.api import (
    create_blueprint,
    register_error_handlers,
    register_health,
)
from propertyscope_due_diligence.clients import (
    AiModeClient,
    DueDiligenceStoreClient,
    Feature1Client,
)


def create_app(*, store: Any = None, feature1: Any = None, ai_mode: Any = None) -> Flask:
    """Create the credential-free due-diligence backend.

    Tests inject fake ``store``, ``feature1`` and ``ai_mode`` clients; the container
    constructs real HTTP clients from the environment.
    """
    if store is None:  # pragma: no cover - constructs a real network client
        store = DueDiligenceStoreClient(
            os.environ.get("PROPERTYSCOPE_DATABASE_API_URL", "http://f4-db-api:5402"),
            os.environ.get("PROPERTYSCOPE_INTERNAL_TOKEN", "local-development-only"),
        )
    if feature1 is None:  # pragma: no cover - constructs a real network client
        feature1 = Feature1Client(
            os.environ.get("PROPERTYSCOPE_DATA_PLATFORM_URL", "http://f1-backend:5201")
        )
    if ai_mode is None:  # pragma: no cover - constructs a real network client
        ai_mode = AiModeClient(os.environ.get("AI_MODE_BASE_URL", "http://shared-ai-mode:5005"))
    app = Flask("propertyscope-due-diligence")
    app.config["MAX_CONTENT_LENGTH"] = int(
        os.environ.get("PROPERTYSCOPE_MAX_REQUEST_BYTES", "262144")
    )
    register_health(app, store)
    app.register_blueprint(create_blueprint(store, feature1, ai_mode))
    register_error_handlers(app)
    return app
