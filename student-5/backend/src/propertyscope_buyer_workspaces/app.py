"""Application factory for the public Buyer Case backend."""

from __future__ import annotations

import os

from flask import Flask

from propertyscope_buyer_workspaces.api import register_api
from propertyscope_buyer_workspaces.clients import BuyerStoreClient, BuyerStoreGateway
from propertyscope_buyer_workspaces.configuration import BackendSettings
from propertyscope_buyer_workspaces.integrations import (
    AiModeClient,
    AiModeGateway,
    EvidenceGateway,
    PublicEvidenceClient,
)


def create_app(
    settings: BackendSettings | None = None,
    *,
    store: BuyerStoreGateway | None = None,
    evidence: EvidenceGateway | None = None,
    ai_mode: AiModeGateway | None = None,
) -> Flask:
    """Create the backend with an injected database HTTP boundary."""

    runtime_settings = settings or BackendSettings.from_environment()
    runtime_store = store or BuyerStoreClient(
        runtime_settings.database_api_url,
        runtime_settings.internal_token,
    )
    runtime_evidence = evidence or PublicEvidenceClient(
        runtime_settings.data_platform_url,
        runtime_settings.market_intelligence_url,
        runtime_settings.due_diligence_url,
    )
    runtime_ai_mode = ai_mode or AiModeClient(
        runtime_settings.ai_mode_url, service_token=os.environ.get("AI_MODE_SERVICE_TOKEN", "")
    )
    app = Flask("propertyscope-buyer-workspaces")
    app.config["MAX_CONTENT_LENGTH"] = runtime_settings.max_request_bytes
    app.extensions["propertyscope_buyer_store_client"] = runtime_store
    app.extensions["propertyscope_buyer_evidence_client"] = runtime_evidence
    app.extensions["propertyscope_ai_mode_client"] = runtime_ai_mode
    register_api(
        app,
        runtime_store,
        settings=runtime_settings,
        evidence=runtime_evidence,
        ai_mode=runtime_ai_mode,
    )
    return app
