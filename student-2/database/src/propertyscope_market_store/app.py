"""Flask factory for the Feature 2 database API."""

from __future__ import annotations

from typing import Any

from flask import Flask

from propertyscope_market_store.api import (
    create_blueprint,
    register_error_handlers,
    register_health,
)
from propertyscope_market_store.configuration import StoreSettings
from propertyscope_market_store.repository import MarketStore


def create_app(settings: StoreSettings | None = None, *, store: Any = None) -> Flask:
    resolved = settings or StoreSettings.from_environment()
    if store is None:
        store = MarketStore(resolved.database_path)
        if resolved.auto_migrate:
            store.initialize()
    app = Flask("propertyscope-market-store")
    app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024
    register_health(app, store)
    app.register_blueprint(create_blueprint(store, internal_token=resolved.internal_token))
    register_error_handlers(app)
    return app
