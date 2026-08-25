"""PropertyScope Data Platform control API application factory."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from flask import Flask, Response, g, request

from propertyscope_data_platform.api import create_blueprint
from propertyscope_data_platform.clients import (
    AiModeClient,
    ConsumerEndpoint,
    ConsumerImportClient,
    DataStoreClient,
)
from propertyscope_data_platform.http_support import register_error_handlers
from propertyscope_data_platform.release_builders import validate_feature_registration
from shared_contracts import is_valid_request_id, is_valid_traceparent


def create_app(
    *,
    store_client: DataStoreClient | None = None,
    ai_mode_client: AiModeClient | None = None,
    consumer_client: ConsumerImportClient | None = None,
    psi_cached_years: tuple[int, ...] | None = None,
    psi_cached_weeks: tuple[str, ...] | None = None,
    feature_root: Path | None = None,
    artifact_root: Path | None = None,
) -> Flask:
    """Create the credential-free Feature 1 backend."""
    resolved_feature_root = feature_root or Path(__file__).resolve().parents[3]
    validate_feature_registration(resolved_feature_root)
    store = store_client or DataStoreClient(
        os.environ.get("PROPERTYSCOPE_DATABASE_API_URL", "http://f1-db-api:5202"),
        os.environ.get("PROPERTYSCOPE_INTERNAL_TOKEN", "local-development-only"),
    )
    ai_mode = ai_mode_client or AiModeClient(
        os.environ.get("AI_MODE_BASE_URL", "http://shared-ai-mode:5005")
    )
    consumers = consumer_client or ConsumerImportClient(
        {
            feature: ConsumerEndpoint(
                os.environ.get(
                    f"PROPERTYSCOPE_{feature.replace('-', '_').upper()}_URL",
                    f"http://{feature}-backend:5000",
                ),
                "/api/data-import/v1/propertyscope-releases",
            )
            for feature in ("feature-2", "feature-3", "feature-4")
        }
    )
    app = Flask("propertyscope-data-platform")
    app.config["MAX_CONTENT_LENGTH"] = int(
        os.environ.get("PROPERTYSCOPE_MAX_REQUEST_BYTES", "262144")
    )
    cached_years = (
        tuple(
            sorted(
                {
                    int(value)
                    for value in os.environ.get("PROPERTYSCOPE_PSI_CACHED_YEARS", "").split(",")
                    if value.strip().isdigit()
                }
            )
        )
        if psi_cached_years is None
        else psi_cached_years
    )
    cached_weeks = (
        tuple(
            sorted(
                {
                    value.strip()
                    for value in os.environ.get("PROPERTYSCOPE_PSI_CACHED_WEEKS", "").split(",")
                    if value.strip()
                }
            )
        )
        if psi_cached_weeks is None
        else psi_cached_weeks
    )
    app.register_blueprint(
        create_blueprint(
            store,
            ai_mode,
            consumers,
            artifact_root=artifact_root
            or Path(
                os.environ.get("PROPERTYSCOPE_ARTIFACT_ROOT", "/var/lib/propertyscope/artifacts")
            ),
            psi_cached_years=cached_years,
            psi_cached_weeks=cached_weeks,
            feature_root=resolved_feature_root,
        )
    )
    worker_token = os.environ.get("PROPERTYSCOPE_RUNNER_TOKEN", "local-runner-only")

    @app.before_request
    def establish_correlation() -> None:
        supplied = request.headers.get("X-Request-ID", "").strip()
        request_id = supplied if is_valid_request_id(supplied) else str(uuid.uuid4())
        request.environ["HTTP_X_REQUEST_ID"] = request_id
        g.request_id = request_id
        supplied_traceparent = request.headers.get("traceparent", "").strip().lower()
        g.traceparent = supplied_traceparent if is_valid_traceparent(supplied_traceparent) else None

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

    @app.after_request
    def return_correlation(response: Response) -> Response:
        response.headers.setdefault("X-Request-ID", g.request_id)
        if g.traceparent is not None:
            response.headers.setdefault("traceparent", g.traceparent)
        return response

    register_error_handlers(app)
    return app
