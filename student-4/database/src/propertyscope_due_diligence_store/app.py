"""Flask application factory for the Student 4 due-diligence database service."""

from __future__ import annotations

from typing import Any

from flask import Flask

from propertyscope_due_diligence_store.api import (
    create_blueprint,
    register_error_handlers,
    register_health,
)
from propertyscope_due_diligence_store.configuration import StoreSettings


def create_app(settings: StoreSettings | None = None, *, store: Any = None) -> Flask:
    """Create the sole PostgreSQL credential-owning API process.

    Tests inject a fake ``store`` (and settings) so the deterministic gate needs no
    database; the container runs with real environment settings and a live store.
    """
    if settings is None:  # pragma: no cover - exercised via environment in the container
        settings = StoreSettings.from_environment()
    if store is None:  # pragma: no cover - requires PostgreSQL
        from propertyscope_due_diligence_store.repository import DueDiligenceStore

        store = DueDiligenceStore(settings.database_url)
        if settings.auto_migrate:
            store.initialize()
    app = Flask("f4-db-api")
    app.config["MAX_CONTENT_LENGTH"] = 256 * 1024
    register_health(app, store)
    app.register_blueprint(create_blueprint(store, internal_token=settings.internal_token))
    register_error_handlers(app)
    return app
