"""Feature 1 database-service Flask application factory."""

from __future__ import annotations

from flask import Flask

from propertyscope_data_store.api import create_blueprint, register_error_handlers
from propertyscope_data_store.configuration import StoreSettings
from propertyscope_data_store.repository import PropertyScopeStore


def create_app(
    settings: StoreSettings | None = None,
    *,
    store: PropertyScopeStore | None = None,
) -> Flask:
    """Create the sole PostgreSQL credential-owning API process."""
    resolved = settings or StoreSettings.from_environment()
    repository = store or PropertyScopeStore(resolved.database_url)
    if resolved.auto_migrate:
        repository.initialize()
    app = Flask("feature-1-database-api")
    app.config["MAX_CONTENT_LENGTH"] = 256 * 1024
    app.extensions["propertyscope_store"] = repository
    app.register_blueprint(create_blueprint(repository, internal_token=resolved.internal_token))
    register_error_handlers(app)
    return app
