"""Application factory for the Student 5 feature-owned database service."""

from __future__ import annotations

from flask import Flask

from propertyscope_buyer_store.api import register_api
from propertyscope_buyer_store.configuration import StoreSettings
from propertyscope_buyer_store.repository import BuyerStore


def create_app(
    settings: StoreSettings | None = None,
    *,
    store: BuyerStore | None = None,
) -> Flask:
    """Build the internal-only buyer workspace persistence API."""

    runtime_settings = settings or StoreSettings.from_environment()
    runtime_store = store or BuyerStore(runtime_settings.database_path)
    if runtime_settings.auto_migrate:
        runtime_store.initialize()

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 1_048_576
    app.extensions["propertyscope_buyer_store"] = runtime_store
    register_api(app, runtime_store, settings=runtime_settings)
    return app


__all__ = ["create_app"]
