"""Public/control, private worker, and AI tool HTTP surface."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from flask import Blueprint, Response, jsonify, request

from propertyscope_data_platform.artifacts import ArtifactError, LocalArtifactStore
from propertyscope_data_platform.clients import (
    AiModeClient,
    ConsumerImportClient,
    DataStoreClient,
    DependencyUnavailableError,
)
from propertyscope_data_platform.domain import (
    ConsumerPublicationRequest,
    PublicationReceiptResult,
)

BASE = "/api/data-platform/v1"
INTERNAL = "/internal/data-platform/v1"


def create_blueprint(
    store: DataStoreClient,
    ai_mode: AiModeClient,
    consumers: ConsumerImportClient,
    *,
    artifact_root: Path,
    full_data_enabled: bool = False,
    psi_transport_enabled: bool = False,
    psi_cached_years: tuple[int, ...] = (),
    psi_cached_weeks: tuple[str, ...] = (),
) -> Blueprint:
    """Create Feature 1's public API without any persistence imports."""
    api = Blueprint("propertyscope-data-platform", __name__)

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
        connected = ["schools-master", "bocsar-sparse", "gnaf-nsw"]
        if psi_transport_enabled:
            connected.append("psi-sales")
        return jsonify(
            {
                "full_data_enabled": full_data_enabled,
                "implemented_live_profiles": [
                    "schools-master",
                    "bocsar-sparse",
                    "gnaf-nsw",
                    "psi-sales",
                ],
                "host_verified_profiles": ["psi-sales"],
                "connected_live_profiles": connected if full_data_enabled else [],
                "cached_live_profiles": ["psi-sales"] if psi_cached_years else [],
                "cached_source_years": {"psi-sales": list(psi_cached_years)},
                "cached_source_weeks": {"psi-sales": list(psi_cached_weeks)},
                "catalogued_profiles": ["psi-sales"],
                "showcase_available": True,
            }
        )

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
            body.get("scope", job_data["scope_json"]),
            run_mode=mode,
            full_data_enabled=full_data_enabled,
            psi_transport_enabled=psi_transport_enabled,
            psi_cached_years=psi_cached_years,
        )
        if scope_error is not None:
            return scope_error
        assert scope is not None
        cached_psi = _psi_scope_is_cached(
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
            body.get("scope", job_response.json()["job"]["scope_json"]),
            run_mode=mode,
            full_data_enabled=full_data_enabled,
            psi_transport_enabled=psi_transport_enabled,
            psi_cached_years=psi_cached_years,
        )
        if scope_error is not None:
            return scope_error
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
        return forward(
            store.request("GET", f"{INTERNAL}/releases/{release_id}", headers=request.headers)
        )

    @api.get(f"{BASE}/dataset-releases/<uuid:release_id>/manifest")
    def release_manifest(release_id: uuid.UUID) -> Response:
        upstream = store.request(
            "GET", f"{INTERNAL}/releases/{release_id}", headers=request.headers
        )
        if upstream.status_code >= 400:
            return forward(upstream)
        return jsonify(upstream.json()["release"]["manifest_json"])

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
        if artifact["artifact_kind"] != "release_export" or int(artifact["bytes"]) > 50_000_000:
            return problem(413, "artifact_not_bounded", "Release artifact exceeds export policy")
        try:
            data = LocalArtifactStore(artifact_root).read_verified(
                artifact["storage_key"], artifact["content_sha256"], max_bytes=50_000_000
            )
        except ArtifactError:
            return problem(503, "artifact_unavailable", "Verified release artifact is unavailable")
        response = Response(data, content_type=artifact["media_type"])
        response.headers["Content-Disposition"] = f'attachment; filename="{release_id}.json"'
        response.headers["Digest"] = f"sha-256={artifact['content_sha256']}"
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
                "prompt_set": "default.v3",
                "model_profile": "local-standard.v1",
                "limits": {
                    "max_iterations": 6,
                    "max_tool_calls": 12,
                    "time_budget_ms": 300000,
                    "max_model_repairs": 1,
                },
            },
            request.headers,
        )
        return forward(upstream)

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

    @api.post(f"{BASE}/tools/runs.list.v1")
    def tool_runs() -> Response:
        body = json_body()
        params: dict[str, Any] = {"limit": min(int(body.get("limit", 25)), 50)}
        if body.get("status"):
            params["status"] = str(body["status"])
        return tool_envelope(
            store.request("GET", f"{INTERNAL}/runs", headers=request.headers, params=params)
        )

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
        return forward(
            store.request("GET", f"{INTERNAL}/properties/{property_ref}", headers=request.headers)
        )

    @api.post(f"{BASE}/tools/runs.retry.v1")
    def tool_retry() -> Response:
        body = json_body()
        key = str(body.get("idempotency_key", "")).strip()
        if not key or not approved_tool_call(ai_mode, "data.run_retry.v1", body):
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
        if not key or not approved_tool_call(ai_mode, "data.release_publish.v1", body):
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
        return finalize_candidate_release(store, run_id)

    return api


def approved_tool_call(ai_mode: AiModeClient, tool_name: str, arguments: Mapping[str, Any]) -> bool:
    """Verify a protected callback against AI-mode's durable human-review evidence."""
    raw_run_id = request.headers.get("X-Agent-Run-ID", "").strip()
    try:
        run_id = uuid.UUID(raw_run_id)
    except ValueError:
        return False
    response = ai_mode.get(f"/api/v1/agent-runs/{run_id}", request.headers)
    if response.status_code != 200:
        return False
    reviews = response.json().get("reviews", [])
    return any(
        review.get("decision") == "approve"
        and review.get("tool_call", {}).get("tool_name") == tool_name
        and review.get("tool_call", {}).get("arguments") == dict(arguments)
        for review in reviews
        if isinstance(review, dict)
    )


def _psi_scope_is_cached(
    job: Mapping[str, Any],
    scope: Mapping[str, Any],
    *,
    cached_years: tuple[int, ...],
    cached_weeks: tuple[str, ...],
) -> bool:
    if scope.get("profile") != "full-data" or str(job.get("import_profile_key")) != "psi-sales":
        return False
    today = datetime.now(UTC).date()
    required_years = set(scope.get("years", []))
    if scope.get("all_history") is True:
        required_years.update(range(1990, today.year))
    required_weeks = set(scope.get("weeks", []))
    if scope.get("include_current_weekly") is True:
        cursor = date(today.year, 1, 1)
        cursor += timedelta(days=(7 - cursor.weekday()) % 7)
        while cursor <= today:
            required_weeks.add(cursor.isoformat())
            cursor += timedelta(days=7)
    return (
        bool(required_years or required_weeks)
        and required_years.issubset(cached_years)
        and required_weeks.issubset(cached_weeks)
    )


def validate_job_scope(
    job: Mapping[str, Any],
    raw_scope: Any,
    *,
    run_mode: str,
    full_data_enabled: bool = False,
    psi_transport_enabled: bool = False,
    psi_cached_years: tuple[int, ...] = (),
) -> tuple[dict[str, Any] | None, Response | None]:
    """Bound operator scope overrides and expose unavailable live transports before launch."""
    if not isinstance(raw_scope, dict):
        return None, problem(422, "invalid_scope", "Run scope must be a JSON object")
    if len(raw_scope) > 20:
        return None, problem(422, "invalid_scope", "Run scope has too many fields")
    scope = dict(raw_scope)
    profile = scope.get("profile", "showcase")
    if profile not in {"test", "showcase", "full-data"}:
        return None, problem(422, "invalid_scope", "Scope profile is not registered")
    scope["profile"] = profile
    maximum_records = scope.get("maximum_records")
    if maximum_records is not None and (
        not isinstance(maximum_records, int)
        or isinstance(maximum_records, bool)
        or maximum_records < 1
        or maximum_records > int(job["max_rows"])
    ):
        return None, problem(422, "invalid_scope", "maximum_records exceeds the job limit")
    if str(job.get("import_profile_key")) == "psi-sales":
        years = scope.get("years")
        all_history = scope.get("all_history") is True
        weekly_only = isinstance(scope.get("weeks"), list) and bool(scope.get("weeks"))
        if (
            not all_history
            and not weekly_only
            and (not isinstance(years, list) or not years or len(years) > 100)
        ):
            return None, problem(
                422, "invalid_scope", "PSI scope requires source years or complete history"
            )
        checked_years: list[Any] = [] if all_history or not isinstance(years, list) else list(years)
        maximum_year = datetime.now(UTC).year + 1
        if any(
            not isinstance(year, int)
            or isinstance(year, bool)
            or year < 1990
            or year > maximum_year
            for year in checked_years
        ):
            return None, problem(422, "invalid_scope", "PSI source year is outside the range")
        if checked_years != sorted(set(checked_years)):
            return None, problem(422, "invalid_scope", "PSI source years must be unique and sorted")
        weeks = scope.get("weeks", [])
        if not isinstance(weeks, list) or len(weeks) > 1000:
            return None, problem(422, "invalid_scope", "PSI weekly partitions are invalid")
        try:
            parsed_weeks = [date.fromisoformat(value) for value in weeks]
        except (TypeError, ValueError):
            return None, problem(422, "invalid_scope", "PSI weeks must use ISO dates")
        if parsed_weeks != sorted(set(parsed_weeks)):
            return None, problem(422, "invalid_scope", "PSI weeks must be unique and sorted")
    if run_mode == "full_refresh" and profile == "full-data" and not full_data_enabled:
        return None, problem(
            422,
            "full_data_runtime_disabled",
            "Start the explicit full-data runtime before launching live acquisition",
        )
    if (
        run_mode == "full_refresh"
        and profile == "full-data"
        and (
            str(job.get("import_profile_key"))
            not in {"schools-master", "bocsar-sparse", "gnaf-nsw", "property-fixture"}
            and not (str(job.get("import_profile_key")) == "psi-sales" and psi_transport_enabled)
        )
    ):
        return None, problem(
            422,
            "live_transport_unavailable",
            "This source is catalogued but its live acquisition transport is not connected",
        )
    return scope, None


def proxy_collection(store: DataStoreClient, path: str) -> Response:
    return forward(
        store.request(
            request.method,
            path,
            headers=request.headers,
            params=request.args,
            json=json_body() if request.method == "POST" else None,
        )
    )


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
        "GET", f"{INTERNAL}/releases", headers=request.headers, params={"limit": 100}
    )
    release = next(
        (
            item
            for item in releases_response.json().get("items", [])
            if item["ingestion_run_id"] == str(run_id)
        ),
        None,
    )
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


def finalize_candidate_release(store: DataStoreClient, run_id: uuid.UUID) -> Response:
    releases = store.request(
        "GET", f"{INTERNAL}/releases", headers=request.headers, params={"limit": 100}
    )
    release = next(
        (
            item
            for item in releases.json().get("items", [])
            if item["ingestion_run_id"] == str(run_id)
        ),
        None,
    )
    if release is None:
        return problem(409, "candidate_release_missing", "Candidate release is missing")
    if release["status"] == "candidate":
        return jsonify({"release": release, "replayed": True})
    return forward(
        store.request(
            "POST",
            f"{INTERNAL}/releases/{release['id']}/transition",
            headers=request.headers,
            json={
                "version": release["version"],
                "target": "candidate",
                "comment": "Registered import and quality checks completed",
            },
        )
    )


def proxy_item(store: DataStoreClient, path: str) -> Response:
    return forward(
        store.request(
            request.method,
            path,
            headers=request.headers,
            json=json_body() if request.method == "PUT" else None,
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
        if tool_output:
            return jsonify(
                {"status": "accepted", "receipt_id": prior_receipt["id"], "replayed": True}
            )
        return jsonify({"release": release, "receipt": prior_receipt, "replayed": True})
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
        result = PublicationReceiptResult(
            consumer_operation_id=idempotency_key,
            status="accepted",
            schema_version=release["schema_version"],
            content_sha256=release["content_sha256"],
            rows_received=release["record_count"],
            rows_accepted=release["record_count"],
            rows_rejected=0,
        )
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
    published = store.request(
        "POST",
        f"{INTERNAL}/releases/{release_id}/transition",
        headers=request.headers,
        json={"version": version, "target": "accepted", "comment": comment.strip()},
    )
    if published.status_code >= 400:
        return forward(published)
    if tool_output:
        return jsonify(
            {
                "status": "accepted",
                "receipt_id": receipt["id"],
                "replayed": not receipt_envelope["created"],
            }
        )
    return jsonify(
        {
            "release": published.json()["release"],
            "receipt": receipt,
            "replayed": not receipt_envelope["created"],
        }
    )


def json_body(*, optional: bool = False) -> dict[str, Any]:
    if optional and not request.data:
        return {}
    value: Any = request.get_json(silent=True)
    if not isinstance(value, dict):
        return {}
    return value


def required_uuid(body: Mapping[str, Any], name: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(body.get(name, "")))
    except ValueError as exc:
        raise ValueError(f"{name} must be a UUID") from exc


def tool_envelope(upstream: httpx.Response) -> Response:
    """Strip internal pagination fields to match bounded tool output contracts."""
    if upstream.status_code >= 400:
        return forward(upstream)
    data = upstream.json()
    return jsonify({"items": data.get("items", []), "count": data.get("count", 0)})


def release_inspection(store: DataStoreClient, release_id: uuid.UUID) -> Response:
    """Compose release, quality, and accepted predecessor evidence without SQL access."""
    response = store.request("GET", f"{INTERNAL}/releases/{release_id}", headers=request.headers)
    if response.status_code >= 400:
        return forward(response)
    release = response.json()["release"]
    quality_response = store.request(
        "GET",
        f"{INTERNAL}/runs/{release['ingestion_run_id']}/quality-results",
        headers=request.headers,
        params={"limit": 100},
    )
    releases_response = store.request(
        "GET",
        f"{INTERNAL}/releases",
        headers=request.headers,
        params={"status": "accepted", "limit": 100},
    )
    predecessor = next(
        (
            item
            for item in releases_response.json().get("items", [])
            if item["dataset_id"] == release["dataset_id"]
            and item["target_feature"] == release["target_feature"]
            and item["id"] != release["id"]
        ),
        None,
    )
    return jsonify(
        {
            "release": release,
            "quality_results": quality_response.json().get("items", []),
            "accepted_predecessor": predecessor,
        }
    )


def forward(upstream: httpx.Response) -> Response:
    try:
        data = upstream.json()
    except ValueError:
        data = {"status": upstream.status_code}
    response = jsonify(data)
    response.status_code = upstream.status_code
    if upstream.headers.get("content-type", "").split(";", 1)[0] == "application/problem+json":
        response.content_type = "application/problem+json"
    for name in ("Location", "X-Request-ID", "X-Agent-Run-ID"):
        if name in upstream.headers:
            response.headers[name] = upstream.headers[name]
    return response


def problem(status: int, code: str, detail: str) -> Response:
    response = jsonify(
        {
            "type": f"https://propertyscope.local/problems/{code}",
            "title": code.replace("_", " ").title(),
            "status": status,
            "detail": detail,
            "code": code,
            "request_id": request.headers.get("X-Request-ID", "unknown"),
        }
    )
    response.status_code = status
    response.content_type = "application/problem+json"
    return response


def register_error_handlers(app: Any) -> None:
    app.register_error_handler(
        DependencyUnavailableError, lambda error: problem(503, "dependency_unavailable", str(error))
    )
    app.register_error_handler(
        ValueError, lambda error: problem(422, "invalid_request", str(error))
    )
    app.register_error_handler(
        404, lambda _: problem(404, "route_not_found", "Route does not exist")
    )
    app.register_error_handler(
        405, lambda _: problem(405, "method_not_allowed", "Method is not allowed")
    )
