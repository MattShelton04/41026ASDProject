"""Public/control, private worker, and AI tool HTTP surface."""

from __future__ import annotations

from pathlib import Path

from flask import Blueprint, Response, jsonify, request

from propertyscope_data_platform.artifacts import LocalArtifactStore
from propertyscope_data_platform.assistant import capability_guide
from propertyscope_data_platform.assistant_routes import (
    register_assistant_tool_routes,
)
from propertyscope_data_platform.clients import (
    AiModeClient,
    ConsumerImportClient,
    DataStoreClient,
)
from propertyscope_data_platform.configuration import load_job_profiles
from propertyscope_data_platform.data_product_routes import register_data_product_routes
from propertyscope_data_platform.http_support import (
    forward,
    json_body,
    problem,
)
from propertyscope_data_platform.ingestion_routes import register_ingestion_routes
from propertyscope_data_platform.property_routes import register_property_routes
from propertyscope_data_platform.release_builders import data_product_catalogue
from propertyscope_data_platform.release_projection import public_receipt as public_receipt
from propertyscope_data_platform.release_routes import (
    ensure_import_operation,
    finalize_candidate_release,
    publish_release,
    register_release_routes,
    release_inspection,
)
from propertyscope_data_platform.worker_routes import register_worker_routes

BASE = "/api/data-platform/v1"
INTERNAL = "/internal/data-platform/v1"


def create_blueprint(
    store: DataStoreClient,
    ai_mode: AiModeClient,
    consumers: ConsumerImportClient,
    *,
    artifact_root: Path,
    psi_cached_years: tuple[int, ...] = (),
    psi_cached_weeks: tuple[str, ...] = (),
    feature_root: Path | None = None,
) -> Blueprint:
    """Create Feature 1's public API without any persistence imports."""
    api = Blueprint("propertyscope-data-platform", __name__)
    resolved_feature_root = feature_root or Path(__file__).resolve().parents[3]
    product_catalogue = data_product_catalogue(resolved_feature_root)
    job_profiles = load_job_profiles(resolved_feature_root / "config" / "job-profiles")

    @api.get("/health/live")
    def live() -> tuple[Response, int]:
        return jsonify({"status": "healthy", "service": "propertyscope-data-platform"}), 200

    @api.get("/health/ready")
    def ready() -> tuple[Response, int]:
        healthy = store.ready()
        return jsonify(
            {"status": "healthy" if healthy else "unhealthy", "dependencies": {"database": healthy}}
        ), 200 if healthy else 503

    @api.get(f"{BASE}/overview")
    def overview() -> Response:
        return forward(store.request("GET", f"{INTERNAL}/overview", headers=request.headers))

    @api.route(f"{BASE}/artifact-retention", methods=["GET", "POST"])
    def artifact_retention() -> Response:
        inventory_response = store.request(
            "GET", f"{INTERNAL}/artifact-retention", headers=request.headers
        )
        if inventory_response.status_code >= 400 or request.method == "GET":
            return forward(inventory_response)
        inventory = inventory_response.json()
        body = json_body()
        grace_days = body.get("grace_days", 7)
        if (
            not isinstance(grace_days, int)
            or isinstance(grace_days, bool)
            or not 1 <= grace_days <= 3650
        ):
            return problem(422, "invalid_grace_period", "grace_days must be between 1 and 3650")
        referenced = {
            str(item["storage_key"])
            for item in inventory.get("items", [])
            if isinstance(item, dict) and item.get("storage_key")
        }
        cleanup = LocalArtifactStore(artifact_root).cleanup_unreferenced(
            referenced,
            grace_seconds=grace_days * 86_400,
            dry_run=body.get("dry_run", True) is not False,
        )
        return jsonify({"inventory": inventory, "cleanup": cleanup})

    @api.get(f"{BASE}/runtime-capabilities")
    def runtime_capabilities() -> Response:
        connected = ["schools-master", "bocsar-sparse", "gnaf-nsw", "psi-sales"]
        return jsonify(
            {
                "implemented_live_profiles": [
                    "schools-master",
                    "bocsar-sparse",
                    "gnaf-nsw",
                    "psi-sales",
                ],
                "host_verified_profiles": ["psi-sales"],
                "connected_live_profiles": connected,
                "cached_live_profiles": ["psi-sales"] if psi_cached_years else [],
                "cached_source_years": {"psi-sales": list(psi_cached_years)},
                "cached_source_weeks": {"psi-sales": list(psi_cached_weeks)},
                "catalogued_profiles": ["psi-sales"],
            }
        )

    @api.get(f"{BASE}/assistant/capabilities")
    def assistant_capabilities() -> Response:
        """Expose the same bounded guide used by the model-facing read tool."""
        if request.args:
            return problem(422, "invalid_query", "Assistant capabilities take no query fields")
        return jsonify(capability_guide())

    register_data_product_routes(
        api,
        store,
        product_catalogue,
        base=BASE,
        internal=INTERNAL,
    )

    register_ingestion_routes(
        api,
        store,
        base=BASE,
        internal=INTERNAL,
        job_profiles=job_profiles,
        psi_cached_years=psi_cached_years,
        psi_cached_weeks=psi_cached_weeks,
    )

    register_release_routes(api, store, consumers, artifact_root=artifact_root)

    register_property_routes(api, store, base=BASE, internal=INTERNAL)

    register_assistant_tool_routes(
        api,
        store,
        ai_mode,
        consumers,
        base=BASE,
        internal=INTERNAL,
        inspect_release=release_inspection,
        publish_release=publish_release,
    )

    register_worker_routes(
        api,
        store,
        internal=INTERNAL,
        ensure_import_operation=ensure_import_operation,
        finalize_candidate_release=finalize_candidate_release,
    )

    return api
