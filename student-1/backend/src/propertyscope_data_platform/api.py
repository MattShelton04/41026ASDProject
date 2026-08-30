"""Public/control, private worker, and AI tool HTTP surface."""

from __future__ import annotations

import uuid
from pathlib import Path

from flask import Blueprint, Response, jsonify, request
from pydantic import ValidationError

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
from propertyscope_data_platform.http_support import (
    forward,
    json_body,
    problem,
)
from propertyscope_data_platform.ingestion_routes import register_ingestion_routes
from propertyscope_data_platform.property_routes import register_property_routes
from propertyscope_data_platform.release_builders import data_product_catalogue
from propertyscope_data_platform.release_routes import (
    ensure_import_operation,
    finalize_candidate_release,
    publish_release,
    public_receipt as public_receipt,
    register_release_routes,
    release_detail_contract,
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

    @api.get(f"{BASE}/data-products")
    def data_products() -> Response:
        if request.args:
            return problem(422, "invalid_query", "Data product catalogue takes no query fields")
        accepted_response = store.request(
            "GET",
            f"{INTERNAL}/releases",
            headers=request.headers,
            params={"status": "accepted", "limit": 100, "offset": 0},
        )
        if accepted_response.status_code >= 400:
            return forward(accepted_response)
        accepted = accepted_response.json().get("items", [])
        items = []
        for entry in product_catalogue:
            matching = next(
                (
                    item
                    for item in accepted
                    if item.get("dataset_id") == entry.dataset_id
                    and item.get("target_feature") == entry.target_feature
                ),
                None,
            )
            if matching is not None:
                try:
                    release_detail_contract(matching)
                except ValidationError:
                    matching = None
            payload = entry.model_dump(mode="json")
            payload["latest_accepted_release"] = (
                {
                    key: matching.get(key)
                    for key in (
                        "id",
                        "release_version",
                        "schema_version",
                        "content_sha256",
                        "record_count",
                        "accepted_at",
                    )
                }
                if matching
                else None
            )
            items.append(payload)
        return jsonify({"items": items, "count": len(items), "next_cursor": None})

    @api.get(f"{BASE}/data-products/<dataset_id>")
    def data_product(dataset_id: str) -> Response:
        if request.args:
            return problem(422, "invalid_query", "Data product detail takes no query fields")
        entry = next((item for item in product_catalogue if item.dataset_id == dataset_id), None)
        if entry is None:
            return problem(404, "data_product_not_found", "Data product is not registered")
        accepted_response = store.request(
            "GET",
            f"{INTERNAL}/releases",
            headers=request.headers,
            params={
                "status": "accepted",
                "dataset_id": dataset_id,
                "target_feature": entry.target_feature,
                "limit": 1,
                "offset": 0,
            },
        )
        if accepted_response.status_code >= 400:
            return forward(accepted_response)
        matching = next(iter(accepted_response.json().get("items", [])), None)
        if matching is not None:
            try:
                release_detail_contract(matching)
            except ValidationError:
                matching = None
        payload = entry.model_dump(mode="json")
        payload["latest_accepted_release"] = matching
        return jsonify(payload)

    @api.get(f"{BASE}/data-products/<dataset_id>/accepted")
    def accepted_data_product(dataset_id: str) -> Response:
        entry = next((item for item in product_catalogue if item.dataset_id == dataset_id), None)
        if entry is None:
            return problem(404, "data_product_not_found", "Data product is not registered")
        target = request.args.get("target_feature", entry.target_feature)
        if target != entry.target_feature or set(request.args) - {"target_feature"}:
            return problem(422, "invalid_query", "Accepted product query is invalid")
        upstream = store.request(
            "GET",
            f"{INTERNAL}/releases",
            headers=request.headers,
            params={
                "status": "accepted",
                "dataset_id": dataset_id,
                "target_feature": target,
                "limit": 1,
                "offset": 0,
            },
        )
        if upstream.status_code >= 400:
            return forward(upstream)
        items = upstream.json().get("items", [])
        if not items:
            return problem(404, "accepted_release_not_found", "No accepted release is available")
        try:
            release_contract = release_detail_contract(items[0])
        except ValidationError:
            return problem(
                409, "release_contract_invalid", "Accepted release is not contract-valid"
            )
        return jsonify({"release": release_contract})

    @api.get(f"{BASE}/data-products/<dataset_id>/source-records")
    def data_product_source_records(dataset_id: str) -> Response:
        """Expose complete accepted PSI facts through stable, year-bounded pages."""
        entry = next((item for item in product_catalogue if item.dataset_id == dataset_id), None)
        if entry is None:
            return problem(404, "data_product_not_found", "Data product is not registered")
        if dataset_id != "nsw-psi-sales":
            return problem(
                409,
                "source_records_unsupported",
                "This data product does not expose a separate source-record feed",
            )
        allowed = {"year", "limit", "offset", "release_id"}
        if set(request.args) - allowed:
            return problem(422, "invalid_query", "Source-record query contains unknown fields")
        try:
            year = int(request.args["year"])
            limit = int(request.args.get("limit", "1000"))
            offset = int(request.args.get("offset", "0"))
            release_id = (
                uuid.UUID(request.args["release_id"]) if request.args.get("release_id") else None
            )
        except (KeyError, TypeError, ValueError):
            return problem(422, "invalid_query", "year and pagination fields must be integers")
        if not 1990 <= year <= 9999 or not 1 <= limit <= 5_000 or not 0 <= offset <= 1_000_000:
            return problem(422, "invalid_query", "Source-record query is outside its bounds")
        if release_id is None:
            accepted_response = store.request(
                "GET",
                f"{INTERNAL}/releases",
                headers=request.headers,
                params={
                    "status": "accepted",
                    "dataset_id": dataset_id,
                    "target_feature": entry.target_feature,
                    "limit": 1,
                    "offset": 0,
                },
            )
            if accepted_response.status_code >= 400:
                return forward(accepted_response)
            accepted = next(
                (
                    item
                    for item in accepted_response.json().get("items", [])
                    if item.get("schema_version") == entry.product_schema_version
                ),
                None,
            )
            if accepted is None:
                return problem(
                    404, "accepted_release_not_found", "No accepted release is available"
                )
            release_id = uuid.UUID(str(accepted["id"]))
        upstream = store.request(
            "GET",
            f"{INTERNAL}/releases/{release_id}/sales-source-records",
            headers=request.headers,
            params={"year": year, "limit": limit, "offset": offset},
        )
        return forward(upstream)

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
