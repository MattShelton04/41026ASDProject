"""Public/control, private worker, and AI tool HTTP surface."""

from __future__ import annotations

import base64
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx
from flask import Blueprint, Response, jsonify, request, send_file
from pydantic import ValidationError

from propertyscope_data_platform.artifacts import ArtifactError, LocalArtifactStore
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
from propertyscope_data_platform.domain import (
    ConsumerPublicationRequest,
    PublicationReceiptResult,
    SourceDefinitionCreate,
    SourceDefinitionUpdate,
)
from propertyscope_data_platform.http_support import (
    forward,
    forward_json_bytes,
    json_body,
    problem,
    proxy_collection,
    proxy_item,
    required_uuid,
)
from propertyscope_data_platform.release_builders import (
    BuildContext,
    ReleaseDetailContract,
    ReleaseManifestV1,
    data_product_catalogue,
    resolve_release_builder,
)
from propertyscope_data_platform.scope_policy import (
    psi_scope_is_cached,
    resolve_registered_scope,
    validate_job_scope,
)

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

    def complete_lineage_scope(
        run_data: Mapping[str, Any], *, run_mode: str
    ) -> tuple[dict[str, Any] | None, Response | None]:
        """Resolve the current complete scope before continuing a historical run lineage."""
        job_id = run_data["job_definition_id"]
        job_response = store.request("GET", f"{INTERNAL}/jobs/{job_id}", headers=request.headers)
        if job_response.status_code >= 400:
            return None, forward(job_response)
        job_data = job_response.json()["job"]
        scope, scope_error = validate_job_scope(
            job_data,
            resolve_registered_scope(job_data, {}, job_profiles),
            run_mode=run_mode,
        )
        if scope_error is not None:
            return None, problem(scope_error.status, scope_error.code, scope_error.detail)
        assert scope is not None
        return scope, None

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

    @api.route(f"{BASE}/sources", methods=["GET", "POST"])
    def sources() -> Response:
        if request.method == "POST":
            body = SourceDefinitionCreate.model_validate(json_body()).model_dump(mode="json")
            return forward(
                store.request(
                    "POST",
                    f"{INTERNAL}/sources",
                    headers=request.headers,
                    params=request.args,
                    json=body,
                )
            )
        return proxy_collection(store, f"{INTERNAL}/sources")

    @api.route(f"{BASE}/sources/<uuid:source_id>", methods=["GET", "PUT", "DELETE"])
    def source(source_id: uuid.UUID) -> Response:
        if request.method == "PUT":
            body = SourceDefinitionUpdate.model_validate(json_body()).model_dump(mode="json")
            return forward(
                store.request(
                    "PUT",
                    f"{INTERNAL}/sources/{source_id}",
                    headers=request.headers,
                    json=body,
                )
            )
        return proxy_item(store, f"{INTERNAL}/sources/{source_id}")

    @api.route(f"{BASE}/jobs", methods=["GET", "POST"])
    def jobs() -> Response:
        return proxy_collection(store, f"{INTERNAL}/jobs")

    @api.route(f"{BASE}/jobs/<uuid:job_id>", methods=["GET", "PUT", "DELETE"])
    def job(job_id: uuid.UUID) -> Response:
        return proxy_item(store, f"{INTERNAL}/jobs/{job_id}")

    @api.get(f"{BASE}/jobs/<uuid:job_id>/capabilities")
    def job_capabilities(job_id: uuid.UUID) -> Response:
        response = store.request("GET", f"{INTERNAL}/jobs/{job_id}", headers=request.headers)
        if response.status_code >= 400:
            return forward(response)
        job_data = response.json()["job"]
        return jsonify(
            {
                "job_id": str(job_id),
                "profile_key": job_data["profile_key"],
                "refresh_strategy": job_data["refresh_strategy"],
                "supported_modes": ["full_refresh", "reprocess_cached"],
                "registered": {
                    "adapter": job_data["adapter_key"],
                    "release_builder": job_data["release_builder_key"],
                    "import_profile": job_data["import_profile_key"],
                    "quality_policy": job_data["quality_policy_key"],
                },
            }
        )

    @api.post(f"{BASE}/jobs/<uuid:job_id>/plans")
    def job_plan(job_id: uuid.UUID) -> Response:
        body = json_body()
        response = store.request("GET", f"{INTERNAL}/jobs/{job_id}", headers=request.headers)
        if response.status_code >= 400:
            return forward(response)
        job_data = response.json()["job"]
        mode = str(body.get("run_mode", "full_refresh"))
        if mode not in {"full_refresh", "reprocess_cached"}:
            return problem(
                422,
                "capability_unsupported",
                "Only full_refresh and reprocess_cached are supported",
            )
        scope, scope_error = validate_job_scope(
            job_data,
            resolve_registered_scope(job_data, body.get("scope"), job_profiles),
            run_mode=mode,
        )
        if scope_error is not None:
            return problem(scope_error.status, scope_error.code, scope_error.detail)
        assert scope is not None
        cached_psi = psi_scope_is_cached(
            job_data,
            scope,
            cached_years=psi_cached_years,
            cached_weeks=psi_cached_weeks,
        )
        return jsonify(
            {
                "valid": True,
                "job_id": str(job_id),
                "run_mode": mode,
                "scope": scope,
                "network_required": mode == "full_refresh"
                and scope.get("profile") == "full-data"
                and job_data.get("import_profile_key") != "property-fixture"
                and not cached_psi,
                "source_cache_required": cached_psi,
                "tasks": [
                    {"sequence": index + 1, "stage": stage, "logical_key": f"{index:02d}/{stage}"}
                    for index, stage in enumerate(
                        (
                            "discover",
                            "acquire",
                            "validate_artifact",
                            "import",
                            "normalise",
                            "quality",
                            "build_release",
                        )
                    )
                ],
                "accepted_watermark_unchanged_until_publication": True,
            }
        )

    @api.post(f"{BASE}/jobs/<uuid:job_id>/runs")
    def run_create(job_id: uuid.UUID) -> Response:
        body = json_body()
        key = request.headers.get("Idempotency-Key", "").strip()
        if not key:
            return problem(422, "idempotency_key_required", "Idempotency-Key is required")
        job_response = store.request("GET", f"{INTERNAL}/jobs/{job_id}", headers=request.headers)
        if job_response.status_code >= 400:
            return forward(job_response)
        mode = str(body.get("run_mode", "full_refresh"))
        if mode not in {"full_refresh", "reprocess_cached"}:
            return problem(
                422,
                "capability_unsupported",
                "Only full_refresh and reprocess_cached are supported",
            )
        scope, scope_error = validate_job_scope(
            job_response.json()["job"],
            resolve_registered_scope(job_response.json()["job"], body.get("scope"), job_profiles),
            run_mode=mode,
        )
        if scope_error is not None:
            return problem(scope_error.status, scope_error.code, scope_error.detail)
        body["scope"] = scope
        body["idempotency_key"] = key
        body["request_id"] = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        return forward(
            store.request(
                "POST", f"{INTERNAL}/jobs/{job_id}/runs", headers=request.headers, json=body
            )
        )

    @api.get(f"{BASE}/ingestion-runs")
    def runs() -> Response:
        return forward(
            store.request("GET", f"{INTERNAL}/runs", headers=request.headers, params=request.args)
        )

    @api.get(f"{BASE}/ingestion-runs/<uuid:run_id>")
    def run(run_id: uuid.UUID) -> Response:
        return forward(store.request("GET", f"{INTERNAL}/runs/{run_id}", headers=request.headers))

    for child in ("tasks", "artifacts", "quality-results"):
        endpoint = child.replace("-", "_")

        def run_child(run_id: uuid.UUID, child: str = child) -> Response:
            return forward(
                store.request(
                    "GET",
                    f"{INTERNAL}/runs/{run_id}/{child}",
                    headers=request.headers,
                    params=request.args,
                )
            )

        api.add_url_rule(
            f"{BASE}/ingestion-runs/<uuid:run_id>/{child}", endpoint, run_child, methods=["GET"]
        )

    @api.post(f"{BASE}/ingestion-runs/<uuid:run_id>/cancel")
    def run_cancel(run_id: uuid.UUID) -> Response:
        return forward(
            store.request(
                "POST",
                f"{INTERNAL}/runs/{run_id}/cancel",
                headers=request.headers,
                json=json_body(optional=True),
            )
        )

    @api.post(f"{BASE}/ingestion-runs/<uuid:run_id>/resume")
    def run_resume(run_id: uuid.UUID) -> Response:
        original = store.request("GET", f"{INTERNAL}/runs/{run_id}", headers=request.headers)
        if original.status_code >= 400:
            return forward(original)
        run_data = original.json()["run"]
        scope, scope_response = complete_lineage_scope(run_data, run_mode=str(run_data["run_mode"]))
        if scope_response is not None:
            return scope_response
        if run_data.get("requested_scope_json") != scope:
            return problem(
                409,
                "incomplete_legacy_run",
                "This historical partial run cannot resume; start a new complete update",
            )
        return forward(
            store.request(
                "POST",
                f"{INTERNAL}/runs/{run_id}/resume",
                headers=request.headers,
                json=json_body(optional=True),
            )
        )

    @api.post(f"{BASE}/ingestion-runs/<uuid:run_id>/retry")
    def run_retry(run_id: uuid.UUID) -> Response:
        original = store.request("GET", f"{INTERNAL}/runs/{run_id}", headers=request.headers)
        if original.status_code >= 400:
            return forward(original)
        run_data = original.json()["run"]
        key = request.headers.get("Idempotency-Key", "").strip()
        if not key:
            return problem(422, "idempotency_key_required", "Idempotency-Key is required")
        scope, scope_response = complete_lineage_scope(run_data, run_mode="full_refresh")
        if scope_response is not None:
            return scope_response
        body = {
            "run_mode": "full_refresh",
            "scope": scope,
            "parent_run_id": str(run_id),
            "idempotency_key": key,
            "request_id": request.headers.get("X-Request-ID", str(uuid.uuid4())),
        }
        return forward(
            store.request(
                "POST",
                f"{INTERNAL}/jobs/{run_data['job_definition_id']}/runs",
                headers=request.headers,
                json=body,
            )
        )

    @api.post(f"{BASE}/ingestion-runs/<uuid:run_id>/reprocess-cached")
    def run_reprocess(run_id: uuid.UUID) -> Response:
        original = store.request("GET", f"{INTERNAL}/runs/{run_id}", headers=request.headers)
        if original.status_code >= 400:
            return forward(original)
        run_data = original.json()["run"]
        key = request.headers.get("Idempotency-Key", "").strip()
        if not key:
            return problem(422, "idempotency_key_required", "Idempotency-Key is required")
        scope, scope_response = complete_lineage_scope(run_data, run_mode="reprocess_cached")
        if scope_response is not None:
            return scope_response
        if run_data.get("requested_scope_json") != scope:
            return problem(
                409,
                "incomplete_legacy_run",
                "Cached artifacts from a historical partial run cannot be reprocessed; "
                "start a new complete update",
            )
        body = {
            "run_mode": "reprocess_cached",
            "scope": scope,
            "parent_run_id": str(run_id),
            "idempotency_key": key,
            "request_id": request.headers.get("X-Request-ID", str(uuid.uuid4())),
        }
        return forward(
            store.request(
                "POST",
                f"{INTERNAL}/jobs/{run_data['job_definition_id']}/runs",
                headers=request.headers,
                json=body,
            )
        )

    @api.route(f"{BASE}/dataset-releases", methods=["GET", "POST"])
    def releases() -> Response:
        return proxy_collection(store, f"{INTERNAL}/releases")

    @api.route(f"{BASE}/dataset-releases/<uuid:release_id>", methods=["GET", "PUT", "DELETE"])
    def release(release_id: uuid.UUID) -> Response:
        if request.method != "GET":
            return proxy_item(store, f"{INTERNAL}/releases/{release_id}")
        return release_inspection(store, release_id)

    @api.get(f"{BASE}/dataset-releases/<uuid:release_id>/manifest")
    def release_manifest(release_id: uuid.UUID) -> Response:
        upstream = store.request(
            "GET", f"{INTERNAL}/releases/{release_id}", headers=request.headers
        )
        if upstream.status_code >= 400:
            return forward(upstream)
        try:
            manifest = ReleaseManifestV1.model_validate(upstream.json()["release"]["manifest_json"])
        except ValidationError:
            return problem(409, "manifest_invalid", "Release manifest is not contract-valid")
        return jsonify(manifest.model_dump(mode="json"))

    @api.get(f"{BASE}/dataset-releases/<uuid:release_id>/artifact")
    def release_artifact(release_id: uuid.UUID) -> Response:
        upstream = store.request(
            "GET", f"{INTERNAL}/releases/{release_id}/artifact", headers=request.headers
        )
        if upstream.status_code >= 400:
            return forward(upstream)
        artifact = upstream.json()["artifact"]
        if artifact["release_status"] not in {"awaiting_review", "accepted", "superseded"}:
            return problem(409, "artifact_not_publishable", "Release artifact is not publishable")
        if artifact["redistribution_policy"] not in {
            "fixture-redistributable",
            "committed-synthetic-fixture",
            "bounded-derived-release",
            "approved-bounded-extract",
        }:
            return problem(
                403,
                "redistribution_not_permitted",
                "This source licence permits metadata evidence only",
            )
        if artifact["artifact_kind"] != "release_export":
            return problem(409, "artifact_invalid", "Release artifact is not a registered export")
        try:
            path = LocalArtifactStore(artifact_root).verified_path(
                artifact["storage_key"],
                artifact["content_sha256"],
                expected_bytes=int(artifact["bytes"]),
            )
        except ArtifactError:
            return problem(503, "artifact_unavailable", "Verified release artifact is unavailable")
        suffix = ".ndjson.gz" if artifact.get("content_encoding") == "gzip" else ".json"
        response = send_file(
            path,
            mimetype="application/gzip"
            if artifact.get("content_encoding") == "gzip"
            else artifact["media_type"],
            as_attachment=True,
            download_name=f"{release_id}{suffix}",
            conditional=True,
        )
        digest_bytes = bytes.fromhex(artifact["content_sha256"])
        response.headers["Digest"] = f"sha-256=:{base64.b64encode(digest_bytes).decode()}:"
        response.headers["ETag"] = f'"sha256-{artifact["content_sha256"]}"'
        response.headers["Cache-Control"] = (
            "public, max-age=31536000, immutable"
            if artifact["release_status"] in {"accepted", "superseded"}
            else "private, no-store"
        )
        return response

    @api.get(f"{BASE}/dataset-releases/<uuid:release_id>/records")
    def release_records(release_id: uuid.UUID) -> Response:
        """Expose only the database service's bounded, registered release projection."""
        return forward(
            store.request(
                "GET",
                f"{INTERNAL}/releases/{release_id}/records",
                headers=request.headers,
                params=request.args,
            )
        )

    @api.post(f"{BASE}/dataset-releases/<uuid:release_id>/submit-review")
    def release_review(release_id: uuid.UUID) -> Response:
        body = json_body()
        return transition(store, release_id, "awaiting_review", body)

    @api.post(f"{BASE}/dataset-releases/<uuid:release_id>/publish")
    def release_publish(release_id: uuid.UUID) -> Response:
        body = json_body()
        if not bool(body.get("approved", False)):
            return problem(
                422, "human_approval_required", "Publication requires explicit human approval"
            )
        key = request.headers.get("Idempotency-Key", "").strip()
        if not key:
            return problem(422, "idempotency_key_required", "Idempotency-Key is required")
        return publish_release(store, consumers, release_id, body, key)

    @api.post(f"{BASE}/dataset-releases/<uuid:release_id>/reject")
    def release_reject(release_id: uuid.UUID) -> Response:
        return transition(store, release_id, "rejected", json_body())

    @api.get(f"{BASE}/properties/search")
    def properties_search() -> Response:
        return forward(
            store.request(
                "GET", f"{INTERNAL}/properties/search", headers=request.headers, params=request.args
            )
        )

    @api.get(f"{BASE}/properties/<uuid:property_ref>")
    def property_detail(property_ref: uuid.UUID) -> Response:
        return forward(
            store.request("GET", f"{INTERNAL}/properties/{property_ref}", headers=request.headers)
        )

    @api.get(f"{BASE}/properties/<uuid:property_ref>/map-context")
    def property_map(property_ref: uuid.UUID) -> Response:
        upstream = store.request(
            "GET", f"{INTERNAL}/properties/{property_ref}", headers=request.headers
        )
        if upstream.status_code >= 400:
            return forward(upstream)
        item = upstream.json()["property"]
        return jsonify(
            {
                "property_ref": str(property_ref),
                "address_display": item["address_display"],
                "longitude": item["longitude"],
                "latitude": item["latitude"],
                "geometry": item["geometry"],
            }
        )

    @api.get(f"{BASE}/properties/<uuid:property_ref>/coverage")
    def property_coverage(property_ref: uuid.UUID) -> Response:
        return forward(
            store.request(
                "GET", f"{INTERNAL}/properties/{property_ref}/coverage", headers=request.headers
            )
        )

    @api.get(f"{BASE}/properties/<uuid:property_ref>/report-section")
    def property_report_section(property_ref: uuid.UUID) -> Response:
        """Return bounded canonical evidence for the Feature 5 report composer."""
        upstream = store.request(
            "GET", f"{INTERNAL}/properties/{property_ref}", headers=request.headers
        )
        if upstream.status_code >= 400:
            return forward(upstream)
        snapshot = upstream.json()
        property_item = snapshot["property"]
        identifiers = snapshot.get("identifiers", [])
        gnaf_identifier = next(
            (
                item
                for item in identifiers
                if str(item.get("scheme", "")).lower() in {"gnaf_pid", "gnaf"}
            ),
            None,
        )
        release_evidence = [
            {
                "dataset_id": item["dataset_id"],
                "target_feature": item["target_feature"],
                "dataset_release_id": item.get("dataset_release_id"),
                "release_version": item.get("release_version"),
                "schema_version": item.get("schema_version"),
                "coverage_status": item["coverage_status"],
                "coverage_scope": item["coverage_scope"],
                "accepted_at": item.get("accepted_at"),
                "checked_at": item["checked_at"],
            }
            for item in snapshot.get("coverage", [])[:25]
        ]
        return jsonify(
            {
                "schema_version": "propertyscope.report-section.v1",
                "property_ref": str(property_ref),
                "address_display": property_item["address_display"],
                "identity": {
                    "gnaf_pid": gnaf_identifier.get("identifier_value")
                    if gnaf_identifier
                    else None,
                    "resolution_status": property_item["resolution_status"],
                    "locality": property_item["locality"],
                    "postcode": property_item["postcode"],
                    "state": property_item["state"],
                    "longitude": property_item.get("longitude"),
                    "latitude": property_item.get("latitude"),
                    "geometry": property_item.get("geometry"),
                },
                "release_evidence": release_evidence,
                "evidence_count": len(release_evidence),
            }
        )

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

    # Private runner boundary simply brokers the same atomic store operations.
    @api.post(f"{INTERNAL}/worker/tasks/claim")
    def worker_claim() -> Response:
        return forward(
            store.request(
                "POST", f"{INTERNAL}/worker/tasks/claim", headers=request.headers, json=json_body()
            )
        )

    for action in ("heartbeat", "complete", "fail", "artifacts"):

        def worker_action(task_id: uuid.UUID, action: str = action) -> Response:
            return forward(
                store.request(
                    "POST",
                    f"{INTERNAL}/worker/tasks/{task_id}/{action}",
                    headers=request.headers,
                    json=json_body(),
                )
            )

        api.add_url_rule(
            f"{INTERNAL}/worker/tasks/<uuid:task_id>/{action}",
            f"worker_{action}",
            worker_action,
            methods=["POST"],
        )

    @api.post(f"{INTERNAL}/worker/runs/<uuid:run_id>/imports")
    def worker_import(run_id: uuid.UUID) -> Response:
        return ensure_import_operation(store, run_id, json_body())

    @api.get(f"{INTERNAL}/worker/imports/<uuid:operation_id>")
    def worker_import_get(operation_id: uuid.UUID) -> Response:
        return forward(
            store.request("GET", f"{INTERNAL}/imports/{operation_id}", headers=request.headers)
        )

    @api.post(f"{INTERNAL}/worker/runs/<uuid:run_id>/finalize-release")
    def worker_finalize_release(run_id: uuid.UUID) -> Response:
        return finalize_candidate_release(store, run_id, json_body())

    @api.get(f"{INTERNAL}/worker/runs/<uuid:run_id>/release-build-context")
    def worker_release_build_context(run_id: uuid.UUID) -> Response:
        upstream = store.request(
            "GET", f"{INTERNAL}/runs/{run_id}/release-build-context", headers=request.headers
        )
        if upstream.status_code >= 400:
            return forward(upstream)
        raw = upstream.json()["context"]
        builder = resolve_release_builder(
            str(raw["release_builder_key"]), str(raw["release_builder_version"])
        )
        context = BuildContext(
            release_id=raw["release_id"],
            release_version=raw["release_version"],
            dataset_id=raw["dataset_id"],
            target_feature=raw["target_feature"],
            candidate_generation_id=raw["candidate_generation_id"],
            import_profile=raw["import_profile_key"],
            normalisation_version=raw["normalisation_version"],
            publisher=raw["publisher"],
            source=raw["source_name"],
            source_release=raw["source_release"],
            source_licence=raw["licence_id"],
            licence_url=raw["licence_url"],
            redistribution_policy=raw["redistribution_policy"],
            source_retrieved_at=raw.get("source_retrieved_at"),
            scope=raw["coverage_json"],
            supersedes_release_id=raw.get("supersedes_release_id"),
        )
        if context.import_profile not in builder.spec.import_profiles:
            return problem(409, "release_builder_mismatch", "Release builder/import mismatch")
        if context.target_feature != builder.spec.target_feature:
            return problem(409, "release_builder_mismatch", "Release builder/target mismatch")
        return jsonify(
            {
                "context": context.model_dump(mode="json"),
                "builder": {"key": builder.spec.key, "version": builder.spec.version},
                "target_contract": builder.spec.contract,
                "release_id": str(context.release_id),
            }
        )

    @api.get(f"{INTERNAL}/worker/releases/<uuid:release_id>/product-records")
    def worker_release_product_records(release_id: uuid.UUID) -> Response:
        return forward_json_bytes(
            store.request(
                "GET",
                f"{INTERNAL}/releases/{release_id}/product-records",
                headers=request.headers,
                params=request.args,
                timeout=120,
            )
        )

    return api


def ensure_import_operation(
    store: DataStoreClient, run_id: uuid.UUID, body: Mapping[str, Any]
) -> Response:
    """Idempotently connect one verified canonical artifact to the serial loader."""
    task_id = required_uuid(body, "run_task_id")
    run_response = store.request("GET", f"{INTERNAL}/runs/{run_id}", headers=request.headers)
    if run_response.status_code >= 400:
        return forward(run_response)
    run = run_response.json()["run"]
    job_response = store.request(
        "GET", f"{INTERNAL}/jobs/{run['job_definition_id']}", headers=request.headers
    )
    artifacts_response = store.request(
        "GET",
        f"{INTERNAL}/runs/{run_id}/artifacts",
        headers=request.headers,
        params={"limit": 100},
    )
    if job_response.status_code >= 400:
        return forward(job_response)
    if artifacts_response.status_code >= 400:
        return forward(artifacts_response)
    job = job_response.json()["job"]
    artifact = next(
        (
            item
            for item in reversed(artifacts_response.json().get("items", []))
            if item["artifact_kind"] == "canonical_import"
        ),
        None,
    )
    if artifact is None:
        return problem(409, "canonical_artifact_missing", "Verified canonical artifact is missing")
    releases_response = store.request(
        "GET",
        f"{INTERNAL}/releases",
        headers=request.headers,
        params={"ingestion_run_id": str(run_id), "limit": 1},
    )
    if releases_response.status_code >= 400:
        return forward(releases_response)
    release = next(iter(releases_response.json().get("items", [])), None)
    if release is None:
        release_response = store.request(
            "POST",
            f"{INTERNAL}/releases",
            headers=request.headers,
            json={
                "dataset_id": job["dataset_id"],
                "source_definition_id": run["source_definition_id"],
                "ingestion_run_id": str(run_id),
                "target_feature": job["target_feature"],
                "release_version": (f"release-{artifact['content_sha256'][:16]}-{str(run_id)[:8]}"),
                "schema_version": artifact["schema_version"],
                "coverage": run["requested_scope_json"],
                "record_count": 0,
                "content_sha256": artifact["content_sha256"],
                "artifact_record_id": artifact["id"],
                "manifest": {
                    "schema_version": artifact["schema_version"],
                    "release_id": (f"release-{artifact['content_sha256'][:16]}-{str(run_id)[:8]}"),
                    "dataset_id": job["dataset_id"],
                    "owner_feature": "student-1-propertyscope-data-platform",
                    "publisher": "PropertyScope registered ingestion",
                    "source_release": run["profile_key"],
                    "content_sha256": artifact["content_sha256"],
                    "record_count": 0,
                    "geographies": ["NSW"],
                    "measures": ["registered-source-record"],
                    "redistribution_policy": "metadata-only",
                    "known_limitations": ["Candidate evidence; not accepted product data"],
                },
                "status": "draft",
            },
        )
        if release_response.status_code >= 400:
            return forward(release_response)
        release = release_response.json()["release"]
    operation_response = store.request(
        "POST",
        f"{INTERNAL}/imports",
        headers=request.headers,
        json={
            "ingestion_run_id": str(run_id),
            "run_task_id": str(task_id),
            "candidate_release_id": release["id"],
            "import_profile_key": job["import_profile_key"],
            "import_profile_version": job["import_profile_version"],
            "artifact_record_id": artifact["id"],
            "idempotency_key": f"import:{run_id}:{job['import_profile_key']}",
        },
    )
    if operation_response.status_code >= 400:
        return forward(operation_response)
    operation = operation_response.json()["operation"]
    if operation["status"] in {"planned", "interrupted"}:
        operation_response = store.request(
            "POST",
            f"{INTERNAL}/imports/{operation['id']}/execute",
            headers=request.headers,
            json={},
        )
    return forward(operation_response)


def finalize_candidate_release(
    store: DataStoreClient, run_id: uuid.UUID, body: Mapping[str, Any]
) -> Response:
    context_response = store.request(
        "GET",
        f"{INTERNAL}/runs/{run_id}/release-build-context",
        headers=request.headers,
    )
    if context_response.status_code >= 400:
        return problem(409, "candidate_release_missing", "Candidate release is missing")
    release_id = context_response.json()["context"]["release_id"]
    required = {
        "artifact_record_id",
        "schema_version",
        "content_sha256",
        "record_count",
        "manifest",
    }
    if set(body) != required:
        return problem(
            422,
            "invalid_release_export_binding",
            "A complete release export binding is required",
        )
    try:
        manifest = ReleaseManifestV1.model_validate(body["manifest"])
    except (KeyError, ValidationError):
        return problem(422, "invalid_release_manifest", "Release manifest is contract-invalid")
    if (
        str(manifest.release_id) != release_id
        or manifest.product_schema_version != body["schema_version"]
        or manifest.content_sha256 != body["content_sha256"]
        or manifest.record_count != body["record_count"]
    ):
        return problem(
            422,
            "invalid_release_export_binding",
            "Release manifest and export binding disagree",
        )
    return forward(
        store.request(
            "POST",
            f"{INTERNAL}/releases/{release_id}/bind-export",
            headers=request.headers,
            json=dict(body),
        )
    )


def transition(
    store: DataStoreClient, release_id: uuid.UUID, target: str, body: Mapping[str, Any]
) -> Response:
    version = body.get("version")
    comment = body.get("comment") or body.get("reason")
    if not isinstance(version, int) or not isinstance(comment, str) or not comment.strip():
        return problem(422, "invalid_request", "version and a non-empty comment are required")
    return forward(
        store.request(
            "POST",
            f"{INTERNAL}/releases/{release_id}/transition",
            headers=request.headers,
            json={"version": version, "target": target, "comment": comment.strip()},
        )
    )


def publish_release(
    store: DataStoreClient,
    consumers: ConsumerImportClient,
    release_id: uuid.UUID,
    body: Mapping[str, Any],
    idempotency_key: str,
    *,
    tool_output: bool = False,
) -> Response:
    """Record the final consumer receipt before atomically activating a release."""
    current_response = store.request(
        "GET", f"{INTERNAL}/releases/{release_id}", headers=request.headers
    )
    if current_response.status_code >= 400:
        return forward(current_response)
    envelope = current_response.json()
    release = envelope["release"]
    prior_receipt = next(
        (
            item
            for item in envelope.get("receipts", [])
            if item["consumer_operation_id"] == idempotency_key
        ),
        None,
    )
    if release["status"] == "accepted" and prior_receipt:
        if not receipt_matches_release(prior_receipt, release):
            return problem(409, "receipt_evidence_conflict", "Receipt evidence does not match")
        if tool_output:
            return jsonify(
                {"status": "accepted", "receipt_id": prior_receipt["id"], "replayed": True}
            )
        return jsonify(
            {"release": release, "receipt": public_receipt(prior_receipt), "replayed": True}
        )
    if release["status"] != "awaiting_review":
        return problem(
            409,
            "release_not_publishable",
            "Only a quality-checked release awaiting review can be published",
        )
    version = body.get("version", release["version"])
    comment = body.get("comment")
    if not isinstance(version, int) or version != release["version"]:
        return problem(409, "release_version_conflict", "Release version does not match")
    if not isinstance(comment, str) or not comment.strip():
        return problem(422, "invalid_request", "A non-empty publication comment is required")
    if prior_receipt:
        if not receipt_matches_release(prior_receipt, release):
            return problem(409, "receipt_evidence_conflict", "Receipt evidence does not match")
        if prior_receipt["status"] != "accepted":
            return problem(
                424,
                "consumer_publication_failed",
                "The retained consumer receipt did not accept this release",
            )
        return complete_publication(
            store,
            release,
            prior_receipt,
            version=version,
            comment=comment.strip(),
            tool_output=tool_output,
            replayed=True,
        )
    publication = ConsumerPublicationRequest(
        release_id=release_id,
        dataset_id=release["dataset_id"],
        schema_version=release["schema_version"],
        content_sha256=release["content_sha256"],
        record_count=release["record_count"],
        manifest=release["manifest_json"],
        artifact_path=f"{BASE}/dataset-releases/{release_id}/artifact",
        idempotency_key=idempotency_key,
    )
    if release["target_feature"] == "feature-1":
        result = verify_local_publication(store, release, publication)
    else:
        result = consumers.publish(release["target_feature"], publication, request.headers)
    recorded = store.request(
        "POST",
        f"{INTERNAL}/releases/{release_id}/receipts",
        headers=request.headers,
        json={
            "target_feature": release["target_feature"],
            **result.model_dump(mode="json"),
            "request_id": request.headers.get("X-Request-ID", str(uuid.uuid4())),
        },
    )
    if recorded.status_code >= 400:
        return forward(recorded)
    receipt_envelope = recorded.json()
    receipt = receipt_envelope["receipt"]
    if result.status != "accepted":
        return problem(
            424,
            "consumer_publication_failed",
            "Consumer did not accept the release; the prior accepted release remains live",
        )
    return complete_publication(
        store,
        release,
        receipt,
        version=version,
        comment=comment.strip(),
        tool_output=tool_output,
        replayed=not receipt_envelope["created"],
    )


def receipt_matches_release(receipt: Mapping[str, Any], release: Mapping[str, Any]) -> bool:
    return (
        receipt.get("schema_version") == release.get("schema_version")
        and receipt.get("content_sha256") == release.get("content_sha256")
        and receipt.get("rows_received") == release.get("record_count")
        and receipt.get("rows_accepted") == release.get("record_count")
        and receipt.get("rows_rejected") == 0
    )


def complete_publication(
    store: DataStoreClient,
    release: Mapping[str, Any],
    receipt: Mapping[str, Any],
    *,
    version: int,
    comment: str,
    tool_output: bool,
    replayed: bool,
) -> Response:
    queued = store.request(
        "POST",
        f"{INTERNAL}/releases/{release['id']}/activations",
        headers=request.headers,
        json={
            "publication_receipt_id": receipt["id"],
            "expected_release_version": version,
            "comment": comment,
            "idempotency_key": receipt["consumer_operation_id"],
        },
    )
    if queued.status_code >= 400:
        return forward(queued)
    activation_envelope = queued.json()
    activation = activation_envelope["activation"]
    completed = activation_envelope.get("outcome") == "completed"
    if tool_output:
        response = jsonify(
            {
                "status": "accepted" if completed else "pending",
                "receipt_id": receipt["id"],
                "replayed": replayed,
            }
        )
        response.status_code = 200 if completed else 202
        return response
    response = jsonify(
        {
            "release": release,
            "receipt": public_receipt(receipt),
            "activation": public_activation(activation),
            "publication_status": "completed" if completed else "pending",
            "replayed": replayed,
        }
    )
    response.status_code = 200 if completed else 202
    return response


def verify_local_publication(
    store: DataStoreClient,
    release: Mapping[str, Any],
    publication: ConsumerPublicationRequest,
) -> PublicationReceiptResult:
    """Validate Feature 1's durable export binding without rereading source-scale bytes.

    Release construction schema-validates every projected row while
    :class:`LocalArtifactStore` hashes and fsyncs the immutable content-addressed object. The
    publication request therefore checks that durable evidence rather than repeating a complete
    hash, decompression and schema pass while an HTTP client waits. Source-scale serving-index
    materialisation remains in the leased database loader before the accepted pointer changes.
    """
    try:
        manifest = ReleaseManifestV1.model_validate(publication.manifest)
        resolve_release_builder(manifest.builder_key, manifest.builder_version)
        upstream = store.request(
            "GET", f"{INTERNAL}/releases/{release['id']}/artifact", headers=request.headers
        )
        upstream.raise_for_status()
        artifact = upstream.json()["artifact"]
        expected_storage_key = (
            f"sha256/{publication.content_sha256[:2]}/{publication.content_sha256}"
        )
        if (
            artifact["artifact_kind"] != "release_export"
            or artifact["content_sha256"] != publication.content_sha256
            or int(artifact["bytes"]) != int(publication.manifest["byte_count"])
            or artifact["storage_key"] != expected_storage_key
            or str(manifest.release_id) != str(publication.release_id)
            or manifest.dataset_id != publication.dataset_id
            or manifest.target_feature != release["target_feature"]
            or manifest.product_schema_version != publication.schema_version
            or manifest.content_sha256 != publication.content_sha256
            or manifest.record_count != publication.record_count
        ):
            raise ArtifactError("artifact registration does not match the release")
    except (ArtifactError, KeyError, TypeError, ValueError, ValidationError, httpx.HTTPError):
        return PublicationReceiptResult(
            consumer_operation_id=publication.idempotency_key,
            status="failed",
            schema_version=publication.schema_version,
            content_sha256=publication.content_sha256,
            rows_received=publication.record_count,
            rows_accepted=0,
            rows_rejected=publication.record_count,
            error={
                "code": "local_publication_binding_failed",
                "message": "Feature 1 could not validate the registered release artifact binding",
                "retryable": False,
            },
        )
    return PublicationReceiptResult(
        consumer_operation_id=publication.idempotency_key,
        status="accepted",
        schema_version=publication.schema_version,
        content_sha256=publication.content_sha256,
        rows_received=publication.record_count,
        rows_accepted=publication.record_count,
        rows_rejected=0,
    )


def release_inspection(store: DataStoreClient, release_id: uuid.UUID) -> Response:
    """Compose release, quality, and accepted predecessor evidence without SQL access."""
    response = store.request("GET", f"{INTERNAL}/releases/{release_id}", headers=request.headers)
    if response.status_code >= 400:
        return forward(response)
    release_envelope = response.json()
    release = release_envelope["release"]
    quality_response = store.request(
        "GET",
        f"{INTERNAL}/runs/{release['ingestion_run_id']}/quality-results",
        headers=request.headers,
        params={"limit": 100},
    )
    predecessor = None
    if release.get("supersedes_release_id"):
        predecessor_response = store.request(
            "GET",
            f"{INTERNAL}/releases/{release['supersedes_release_id']}",
            headers=request.headers,
        )
        if predecessor_response.status_code < 400:
            predecessor = predecessor_response.json().get("release")
    elif release["status"] != "accepted":
        releases_response = store.request(
            "GET",
            f"{INTERNAL}/releases",
            headers=request.headers,
            params={
                "status": "accepted",
                "dataset_id": release["dataset_id"],
                "target_feature": release["target_feature"],
                "limit": 1,
                "offset": 0,
            },
        )
        predecessor = next(iter(releases_response.json().get("items", [])), None)
    quality_results = quality_response.json().get("items", [])
    quality_summary = {
        "total": len(quality_results),
        "passed": sum(item.get("status") == "pass" for item in quality_results),
        "failed": sum(item.get("status") == "fail" for item in quality_results),
        "blocking_failures": sum(
            item.get("status") == "fail" and item.get("severity") == "blocking"
            for item in quality_results
        ),
    }
    payload = {
        "release": release,
        "quality_results": quality_results,
        "quality_summary": quality_summary,
        "receipts": [public_receipt(item) for item in release_envelope.get("receipts", [])],
        "activations": [
            public_activation(item) for item in release_envelope.get("activations", [])
        ],
        "accepted_predecessor": predecessor,
    }
    try:
        payload["release_contract"] = release_detail_contract(
            release, receipts=release_envelope.get("receipts", [])
        )
    except ValidationError:
        payload["release_contract"] = None
    return jsonify(payload)


def release_detail_contract(release: Mapping[str, Any], *, receipts: Any = ()) -> dict[str, Any]:
    receipt_contracts = tuple(public_receipt(item) for item in receipts)
    return ReleaseDetailContract.model_validate(
        {
            "id": release["id"],
            "dataset_id": release["dataset_id"],
            "target_feature": release["target_feature"],
            "release_version": release["release_version"],
            "schema_version": release["schema_version"],
            "status": release["status"],
            "record_count": release["record_count"],
            "content_sha256": release["content_sha256"],
            "manifest_json": release["manifest_json"],
            "supersedes_release_id": release.get("supersedes_release_id"),
            "version": release["version"],
            "receipts": receipt_contracts,
        }
    ).model_dump(mode="json")


def public_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Project datastore evidence onto the closed public consumer receipt contract."""
    return PublicationReceiptResult.model_validate(
        {
            "consumer_operation_id": receipt["consumer_operation_id"],
            "status": receipt["status"],
            "schema_version": receipt["schema_version"],
            "content_sha256": receipt["content_sha256"],
            "rows_received": receipt["rows_received"],
            "rows_accepted": receipt["rows_accepted"],
            "rows_rejected": receipt["rows_rejected"],
            "error": receipt.get("error", receipt.get("error_json")),
        }
    ).model_dump(mode="json")


def public_activation(operation: Mapping[str, Any]) -> dict[str, Any]:
    """Expose progress without loader lease credentials or internal review text."""
    return {
        key: operation.get(key)
        for key in (
            "id",
            "status",
            "attempt_number",
            "requested_at",
            "started_at",
            "materialized_at",
            "finished_at",
            "error_json",
            "version",
        )
    }
