"""Flask factory for the Feature 2 public backend."""

from __future__ import annotations

import os
from typing import Any

from flask import Flask

from propertyscope_market_intelligence.api import (
    create_blueprint,
    register_error_handlers,
    register_health,
)
from propertyscope_market_intelligence.clients import AiModeClient, Feature1Client, StoreClient
from propertyscope_market_intelligence.import_worker import SalesImportWorker


def create_app(*, store: Any = None, feature1: Any = None, ai_mode: Any = None) -> Flask:
    start_worker = store is None
    if store is None:
        store = StoreClient(
            os.environ.get("PROPERTYSCOPE_DATABASE_API_URL", "http://f2-db-api:5302"),
            os.environ.get("PROPERTYSCOPE_INTERNAL_TOKEN", "propertyscope-local-development-only"),
        )
    if feature1 is None:
        feature1 = Feature1Client(
            os.environ.get("PROPERTYSCOPE_DATA_PLATFORM_URL", "http://f1-backend:5201")
        )
    if ai_mode is None:
        ai_mode = AiModeClient(os.environ.get("AI_MODE_BASE_URL", "http://shared-ai-mode:5005"))
    app = Flask("propertyscope-market-intelligence")
    app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024
    register_health(app, store)
    app.register_blueprint(create_blueprint(store, feature1, ai_mode))
    register_error_handlers(app)
    if start_worker:
        worker = SalesImportWorker(store, feature1)
        app.extensions["sales_import_worker"] = worker
        worker.start()
    return app
