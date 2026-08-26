"""Public/control, private worker, and AI tool HTTP surface."""

from __future__ import annotations

import base64
import json
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx
from flask import Blueprint, Response, jsonify, request
from pydantic import ValidationError

from propertyscope_data_platform.approval import approved_tool_call
from propertyscope_data_platform.artifacts import ArtifactError, LocalArtifactStore
from propertyscope_data_platform.assistant import (
    ASSISTANT_FEATURE_KEY,
    AssistantTurnRequest,
    build_assistant_objective,
    capability_guide,
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
)
from propertyscope_data_platform.http_support import (
    forward,
    json_body,
    problem,
    proxy_collection,
    proxy_item,
    required_uuid,
    tool_envelope,
)
from propertyscope_data_platform.release_builders import (
    MAX_PUBLIC_ARTIFACT_BYTES,
    BuildContext,
    ProductEnvelope,
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
                "showcase_available": True,
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

    @api.route(f"{BASE}/sources", methods=["GET", "POST"])
    def sources() -> Response:
        return proxy_collection(store, f"{INTERNAL}/sources")

    @api.route(f"{BASE}/sources/<uuid:source_id>", methods=["GET", "PUT", "DELETE"])
    def source(source_id: uuid.UUID) -> Response:
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
                "limits": {
                    name: job_data[name]
                    for name in (
                        "max_objects",
                        "max_bytes",
                        "max_rows",
                        "timeout_seconds",
                        "max_parallelism",
                    )
                },
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
                "hard_limits": {
                    name: job_data[name]
                    for name in ("max_objects", "max_bytes", "max_rows", "timeout_seconds")
                },
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

    for action in ("cancel", "resume"):

        def run_action(run_id: uuid.UUID, action: str = action) -> Response:
            return forward(
                store.request(
                    "POST",
                    f"{INTERNAL}/runs/{run_id}/{action}",
                    headers=request.headers,
                    json=json_body(optional=True),
                )
            )

        api.add_url_rule(
            f"{BASE}/ingestion-runs/<uuid:run_id>/{action}",
            f"run_{action}",
            run_action,
            methods=["POST"],
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
        body = {
            "run_mode": "full_refresh",
            "scope": run_data["requested_scope_json"],
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
        body = {
            "run_mode": "reprocess_cached",
            "scope": run_data["requested_scope_json"],
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
        if (
            artifact["artifact_kind"] != "release_export"
            or int(artifact["bytes"]) > MAX_PUBLIC_ARTIFACT_BYTES
        ):
            return problem(413, "artifact_not_bounded", "Release artifact exceeds export policy")
        try:
            data = LocalArtifactStore(artifact_root).read_verified(
                artifact["storage_key"],
                artifact["content_sha256"],
                max_bytes=MAX_PUBLIC_ARTIFACT_BYTES,
            )
        except ArtifactError:
            return problem(503, "artifact_unavailable", "Verified release artifact is unavailable")
        response = Response(data, content_type=artifact["media_type"])
        response.headers["Content-Disposition"] = f'attachment; filename="{release_id}.json"'
        digest_bytes = bytes.fromhex(artifact["content_sha256"])
        response.headers["Digest"] = f"sha-256=:{base64.b64encode(digest_bytes).decode()}:"
        response.headers["ETag"] = f'"sha256-{artifact["content_sha256"]}"'
        response.headers["Cache-Control"] = (
            "public, max-age=31536000, immutable"
            if artifact["release_status"] in {"accepted", "superseded"}
            else "private, no-store"
        )
        if artifact.get("content_encoding"):
            response.headers["Content-Encoding"] = artifact["content_encoding"]
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
        return publish_release(store, consumers, release_id, body, key, artifact_root=artifact_root)

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

    @api.post(f"{BASE}/dataset-releases/<uuid:release_id>/agent-runs")
    def release_agent_run(release_id: uuid.UUID) -> Response:
        release_response = store.request(
            "GET", f"{INTERNAL}/releases/{release_id}", headers=request.headers
        )
        if release_response.status_code >= 400:
            return forward(release_response)
        release_data = release_response.json()["release"]
        predecessor_id = "none"
        if release_data.get("dataset_id") and release_data.get("target_feature"):
            accepted_response = store.request(
                "GET",
                f"{INTERNAL}/releases",
                headers=request.headers,
                params={"status": "accepted", "limit": 100},
            )
            predecessor = next(
                (
                    item
                    for item in accepted_response.json().get("items", [])
                    if item["dataset_id"] == release_data["dataset_id"]
                    and item["target_feature"] == release_data["target_feature"]
                    and item["id"] != str(release_id)
                ),
                None,
            )
            if predecessor:
                predecessor_id = predecessor["id"]
        supplied_objective = str(json_body(optional=True).get("objective", "")).strip()
        objective = (
            f"Release under investigation: {release_id}. "
            f"Accepted predecessor release: {predecessor_id}. Use only these exact identifiers; "
            "never send placeholders to tools. "
        ) + (
            supplied_objective[:3500]
            if supplied_objective
            else "Compare its accepted predecessor, preserve accepted data, and propose "
            "only a reviewed safe recovery."
        )
        upstream = ai_mode.create_run(
            {
                "feature_key": "student-1-propertyscope-data-platform",
                "objective": objective,
                "prompt_set": "default.v4",
                "limits": {
                    "max_iterations": 6,
                    "max_tool_calls": 12,
                    "time_budget_ms": 300000,
                    "max_model_repairs": 2,
                },
            },
            request.headers,
        )
        return forward(upstream)

    @api.post(f"{BASE}/assistant/turns")
    def assistant_turn() -> Response:
        """Create one feature-scoped durable run for one conversational turn."""
        try:
            command = AssistantTurnRequest.model_validate(json_body())
        except ValidationError as exc:
            issue = exc.errors(include_url=False)[0]
            location = ".".join(str(item) for item in issue.get("loc", ())) or "request"
            return problem(422, "invalid_assistant_turn", f"{location}: {issue['msg']}")
        upstream = ai_mode.create_run(
            {
                "feature_key": ASSISTANT_FEATURE_KEY,
                "objective": build_assistant_objective(command),
                "prompt_set": "default.v4",
                "limits": {
                    "max_iterations": 6,
                    "max_tool_calls": 10,
                    "time_budget_ms": 180000,
                    "max_model_repairs": 2,
                },
            },
            request.headers,
        )
        return forward(upstream)

    @api.get(f"{BASE}/assistant/turns/<uuid:run_id>")
    def assistant_turn_detail(run_id: uuid.UUID) -> Response:
        return forward(ai_mode.get(f"/api/v1/agent-runs/{run_id}", request.headers))

    @api.get(f"{BASE}/assistant/turns/<uuid:run_id>/events")
    def assistant_turn_events(run_id: uuid.UUID) -> Response:
        suffix = ""
        if request.query_string:
            suffix = "?" + request.query_string.decode("ascii", errors="ignore")
        return forward(ai_mode.get(f"/api/v1/agent-runs/{run_id}/events{suffix}", request.headers))

    @api.post(f"{BASE}/assistant/turns/<uuid:run_id>/cancel")
    def assistant_turn_cancel(run_id: uuid.UUID) -> Response:
        return forward(ai_mode.cancel_run(str(run_id), request.headers))

    @api.get(f"{BASE}/agent-runs/<uuid:run_id>")
    def agent_run(run_id: uuid.UUID) -> Response:
        return forward(ai_mode.get(f"/api/v1/agent-runs/{run_id}", request.headers))

    @api.get(f"{BASE}/agent-runs")
    def agent_runs() -> Response:
        params: dict[str, str | list[str]] = {
            "feature_key": "student-1-propertyscope-data-platform"
        }
        for name in ("status", "model_profile", "cursor", "limit"):
            values = request.args.getlist(name)
            if values:
                params[name] = values if name == "status" else values[-1]
        return forward(ai_mode.get("/api/v1/agent-runs", request.headers, params=params))

    @api.get(f"{BASE}/agent-runs/<uuid:run_id>/events")
    def agent_events(run_id: uuid.UUID) -> Response:
        suffix = ""
        if request.query_string:
            suffix = "?" + request.query_string.decode("ascii", errors="ignore")
        return forward(ai_mode.get(f"/api/v1/agent-runs/{run_id}/events{suffix}", request.headers))

    # AI tools bind exactly to the checked catalogue paths and output schemas.
    @api.post(f"{BASE}/tools/sources.list.v1")
    def tool_sources() -> Response:
        body = json_body()
        params: dict[str, Any] = {"limit": min(int(body.get("limit", 25)), 50)}
        if body.get("status"):
            params["status"] = str(body["status"])
        return tool_envelope(
            store.request("GET", f"{INTERNAL}/sources", headers=request.headers, params=params)
        )

    @api.post(f"{BASE}/tools/releases.list.v1")
    def tool_releases() -> Response:
        body = json_body()
        params: dict[str, Any] = {"limit": min(int(body.get("limit", 25)), 50)}
        for name in ("status", "dataset_id", "target_feature"):
            if body.get(name):
                params[name] = str(body[name])
        upstream = store.request(
            "GET", f"{INTERNAL}/releases", headers=request.headers, params=params
        )
        if upstream.status_code >= 400:
            return forward(upstream)
        fields = (
            "id",
            "dataset_id",
            "source_definition_id",
            "ingestion_run_id",
            "target_feature",
            "release_version",
            "schema_version",
            "record_count",
            "status",
            "supersedes_release_id",
            "accepted_at",
            "created_at",
            "updated_at",
        )
        summaries = [
            {name: item.get(name) for name in fields if name in item}
            for item in upstream.json().get("items", [])[:50]
            if isinstance(item, dict)
        ]
        return jsonify({"items": summaries, "count": len(summaries)})

    @api.post(f"{BASE}/tools/platform.capabilities.v1")
    def tool_platform_capabilities() -> Response:
        body = json_body()
        if body:
            return problem(422, "invalid_tool_input", "Capability guide takes no input fields")
        return jsonify(capability_guide())

    @api.post(f"{BASE}/tools/runs.list.v1")
    def tool_runs() -> Response:
        body = json_body()
        params: dict[str, Any] = {
            "limit": min(int(body.get("limit", 10)), 25),
            "status": str(body.get("status", "succeeded")),
        }
        upstream = store.request("GET", f"{INTERNAL}/runs", headers=request.headers, params=params)
        if upstream.status_code >= 400:
            return forward(upstream)
        fields = (
            "id",
            "job_definition_id",
            "job_name",
            "source_definition_id",
            "source_name",
            "status",
            "run_mode",
            "requested_scope_json",
            "rows_discovered",
            "rows_staged",
            "rows_accepted",
            "rows_rejected",
            "requested_at",
            "started_at",
            "finished_at",
        )
        summaries = [
            {name: item.get(name) for name in fields if name in item}
            for item in upstream.json().get("items", [])[:25]
            if isinstance(item, dict)
        ]
        return jsonify({"items": summaries, "count": len(summaries)})

    @api.post(f"{BASE}/tools/runs.inspect.v1")
    def tool_run() -> Response:
        run_id = required_uuid(json_body(), "run_id")
        run_response = store.request("GET", f"{INTERNAL}/runs/{run_id}", headers=request.headers)
        if run_response.status_code >= 400:
            return forward(run_response)
        tasks = store.request(
            "GET",
            f"{INTERNAL}/runs/{run_id}/tasks",
            headers=request.headers,
            params={"limit": 100},
        )
        quality = store.request(
            "GET",
            f"{INTERNAL}/runs/{run_id}/quality-results",
            headers=request.headers,
            params={"limit": 100},
        )
        return jsonify(
            {
                "run": run_response.json()["run"],
                "tasks": tasks.json().get("items", []),
                "quality_results": quality.json().get("items", []),
            }
        )

    @api.post(f"{BASE}/tools/releases.inspect.v1")
    def tool_release() -> Response:
        return release_inspection(store, required_uuid(json_body(), "release_id"))

    @api.post(f"{BASE}/tools/releases.compare.v1")
    def tool_release_compare() -> Response:
        body = json_body()
        candidate = store.request(
            "GET",
            f"{INTERNAL}/releases/{required_uuid(body, 'candidate_release_id')}",
            headers=request.headers,
        )
        predecessor = store.request(
            "GET",
            f"{INTERNAL}/releases/{required_uuid(body, 'predecessor_release_id')}",
            headers=request.headers,
        )
        if candidate.status_code >= 400:
            return forward(candidate)
        if predecessor.status_code >= 400:
            return forward(predecessor)
        left, right = candidate.json()["release"], predecessor.json()["release"]
        fields = ("schema_version", "record_count", "content_sha256", "coverage_json", "status")
        differences = [
            {"field": field, "candidate": left.get(field), "predecessor": right.get(field)}
            for field in fields
            if left.get(field) != right.get(field)
        ]
        return jsonify({"candidate": left, "predecessor": right, "differences": differences})

    @api.post(f"{BASE}/tools/coverage.inspect.v1")
    def tool_coverage() -> Response:
        body = json_body()
        locality = str(body.get("locality", "")).strip()
        if not locality:
            return problem(422, "invalid_request", "locality is required")
        search = store.request(
            "GET",
            f"{INTERNAL}/properties/search",
            headers=request.headers,
            params={"q": locality, "state": "NSW", "limit": 25},
        )
        if search.status_code >= 400:
            return forward(search)
        evidence: dict[tuple[str, str], dict[str, Any]] = {}
        for item in search.json().get("items", []):
            if body.get("postcode") and item.get("postcode") != body["postcode"]:
                continue
            response = store.request(
                "GET",
                f"{INTERNAL}/properties/{item['property_ref']}/coverage",
                headers=request.headers,
            )
            for row in response.json().get("items", []):
                evidence[(row["dataset_id"], row["target_feature"])] = row
        return jsonify({"items": list(evidence.values())[:50]})

    @api.post(f"{BASE}/tools/properties.search.v1")
    def tool_property_search() -> Response:
        body = json_body()
        response = store.request(
            "GET",
            f"{INTERNAL}/properties/search",
            headers=request.headers,
            params={"q": body.get("query", ""), "state": "NSW", "limit": body.get("limit", 10)},
        )
        if response.status_code >= 400:
            return forward(response)
        data = response.json()
        return jsonify({"items": data.get("items", []), "count": data.get("count", 0)})

    @api.post(f"{BASE}/tools/properties.inspect.v1")
    def tool_property_inspect() -> Response:
        property_ref = required_uuid(json_body(), "property_ref")
        upstream = store.request(
            "GET", f"{INTERNAL}/properties/{property_ref}", headers=request.headers
        )
        if upstream.status_code >= 400:
            return forward(upstream)
        snapshot = upstream.json()
        return jsonify(
            {
                "property": snapshot["property"],
                "identifiers": snapshot.get("identifiers", [])[:25],
                "aliases": snapshot.get("aliases", [])[:25],
                "coverage": snapshot.get("coverage", [])[:25],
            }
        )

    @api.post(f"{BASE}/tools/runs.retry.v1")
    def tool_retry() -> Response:
        body = json_body()
        key = str(body.get("idempotency_key", "")).strip()
        if not key or not approved_tool_call(ai_mode, request.headers, "data.run_retry.v1", body):
            return problem(
                422,
                "human_approval_required",
                "Protected retry requires an approved agent run and idempotency key",
            )
        run_id = required_uuid(body, "run_id")
        original = store.request("GET", f"{INTERNAL}/runs/{run_id}", headers=request.headers)
        if original.status_code >= 400:
            return forward(original)
        source_run = original.json()["run"]
        created = store.request(
            "POST",
            f"{INTERNAL}/jobs/{source_run['job_definition_id']}/runs",
            headers=request.headers,
            json={
                "run_mode": "full_refresh",
                "scope": source_run["requested_scope_json"],
                "parent_run_id": str(run_id),
                "idempotency_key": key,
                "request_id": request.headers.get("X-Request-ID", str(uuid.uuid4())),
            },
        )
        if created.status_code >= 400:
            return forward(created)
        result = created.json()
        return jsonify({"child_run_id": result["run"]["id"], "replayed": not result["created"]})

    @api.post(f"{BASE}/tools/releases.publish.v1")
    def tool_publish() -> Response:
        body = json_body()
        key = str(body.get("idempotency_key", "")).strip()
        if not key or not approved_tool_call(
            ai_mode, request.headers, "data.release_publish.v1", body
        ):
            return problem(
                422,
                "human_approval_required",
                "Protected publication requires an approved agent run and idempotency key",
            )
        release_id = required_uuid(body, "release_id")
        return publish_release(
            store,
            consumers,
            release_id,
            {"comment": f"Approved agent operation {key}"},
            key,
            artifact_root=artifact_root,
            tool_output=True,
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
        return forward(
            store.request(
                "GET",
                f"{INTERNAL}/releases/{release_id}/product-records",
                headers=request.headers,
                params=request.args,
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
    artifact_root: Path,
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
        result = verify_local_publication(store, release, publication, artifact_root)
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
    activation = queued.json()["activation"]
    if tool_output:
        response = jsonify(
            {
                "status": "pending",
                "receipt_id": receipt["id"],
                "replayed": replayed,
            }
        )
        response.status_code = 202
        return response
    response = jsonify(
        {
            "release": release,
            "receipt": public_receipt(receipt),
            "activation": public_activation(activation),
            "replayed": replayed,
        }
    )
    response.status_code = 202
    return response


def verify_local_publication(
    store: DataStoreClient,
    release: Mapping[str, Any],
    publication: ConsumerPublicationRequest,
    artifact_root: Path,
) -> PublicationReceiptResult:
    """Verify Feature 1's own exported bytes before recording consumer acceptance."""
    try:
        manifest = ReleaseManifestV1.model_validate(publication.manifest)
        upstream = store.request(
            "GET", f"{INTERNAL}/releases/{release['id']}/artifact", headers=request.headers
        )
        upstream.raise_for_status()
        artifact = upstream.json()["artifact"]
        if (
            artifact["artifact_kind"] != "release_export"
            or artifact["content_sha256"] != publication.content_sha256
            or int(artifact["bytes"]) != int(publication.manifest["byte_count"])
        ):
            raise ArtifactError("artifact registration does not match the release")
        content = LocalArtifactStore(artifact_root).read_verified(
            artifact["storage_key"],
            publication.content_sha256,
            max_bytes=MAX_PUBLIC_ARTIFACT_BYTES,
        )
        envelope = ProductEnvelope.model_validate(json.loads(content))
        if (
            envelope.schema_version != publication.schema_version
            or envelope.release_id != publication.release_id
            or envelope.dataset_id != publication.dataset_id
            or len(envelope.records) != publication.record_count
        ):
            raise ArtifactError("product envelope does not match the release")
        builder = resolve_release_builder(manifest.builder_key, manifest.builder_version)
        for record in envelope.records:
            builder.spec.record_adapter.validate_python(record)
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
                "code": "local_publication_verification_failed",
                "message": "Feature 1 could not verify the registered release artifact",
                "retryable": True,
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
