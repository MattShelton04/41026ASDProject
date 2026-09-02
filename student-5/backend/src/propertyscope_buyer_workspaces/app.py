"""Application factory for the public Buyer Case backend."""

from __future__ import annotations

from flask import Flask

from propertyscope_buyer_workspaces.api import register_api
from propertyscope_buyer_workspaces.clients import BuyerStoreClient, BuyerStoreGateway
from propertyscope_buyer_workspaces.configuration import BackendSettings


def create_app(
    settings: BackendSettings | None = None,
    *,
    store: BuyerStoreGateway | None = None,
) -> Flask:
    """Create the backend with an injected database HTTP boundary."""

    runtime_settings = settings or BackendSettings.from_environment()
    runtime_store = store or BuyerStoreClient(
        runtime_settings.database_api_url,
        runtime_settings.internal_token,
    )
    app = Flask("propertyscope-buyer-workspaces")
    app.config["MAX_CONTENT_LENGTH"] = runtime_settings.max_request_bytes
    app.extensions["propertyscope_buyer_store_client"] = runtime_store
    register_api(app, runtime_store, settings=runtime_settings)
    return app
