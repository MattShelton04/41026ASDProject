"""Source, job, and ingestion-run HTTP routes."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from flask import Blueprint, Response, jsonify, request

from propertyscope_data_platform.clients import DataStoreClient, DependencyUnavailableError
from propertyscope_data_platform.configuration import JobProfile, Registry
from propertyscope_data_platform.domain import SourceDefinitionCreate, SourceDefinitionUpdate
from propertyscope_data_platform.http_support import (
    forward,
    json_body,
    problem,
    proxy_collection,
    proxy_item,
)
from propertyscope_data_platform.scope_policy import (
    psi_scope_is_cached,
    resolve_registered_scope,
    validate_job_scope,
)


def register_ingestion_routes(
    api: Blueprint,
    store: DataStoreClient,
    *,
    base: str,
    internal: str,
    job_profiles: Registry[JobProfile],
    psi_cached_years: tuple[int, ...],
    psi_cached_weeks: tuple[str, ...],
) -> None:
    """Register source definitions, jobs, and ingestion-run lifecycle routes."""

    def complete_lineage_scope(
        run_data: Mapping[str, Any], *, run_mode: str
    ) -> tuple[dict[str, Any] | None, Response | None]:
        job_id = run_data["job_definition_id"]
        job_response = store.request("GET", f"{internal}/jobs/{job_id}", headers=request.headers)
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

    @api.route(f"{base}/sources", methods=["GET", "POST"])
    def sources() -> Response:
        if request.method == "POST":
            body = SourceDefinitionCreate.model_validate(json_body()).model_dump(mode="json")
            return forward(
                store.request(
                    "POST",
                    f"{internal}/sources",
                    headers=request.headers,
                    params=request.args,
                    json=body,
                )
            )
        return proxy_collection(store, f"{internal}/sources")

    @api.route(f"{base}/sources/<uuid:source_id>", methods=["GET", "PUT", "DELETE"])
    def source(source_id: uuid.UUID) -> Response:
        if request.method == "PUT":
            body = SourceDefinitionUpdate.model_validate(json_body()).model_dump(mode="json")
            return forward(
                store.request(
                    "PUT",
                    f"{internal}/sources/{source_id}",
                    headers=request.headers,
                    json=body,
                )
            )
        return proxy_item(store, f"{internal}/sources/{source_id}")

    @api.route(f"{base}/jobs", methods=["GET", "POST"])
    def jobs() -> Response:
        return proxy_collection(store, f"{internal}/jobs")

    @api.route(f"{base}/jobs/<uuid:job_id>", methods=["GET", "PUT", "DELETE"])
    def job(job_id: uuid.UUID) -> Response:
        return proxy_item(store, f"{internal}/jobs/{job_id}")

    @api.get(f"{base}/jobs/<uuid:job_id>/capabilities")
    def job_capabilities(job_id: uuid.UUID) -> Response:
        response = store.request("GET", f"{internal}/jobs/{job_id}", headers=request.headers)
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

    @api.post(f"{base}/jobs/<uuid:job_id>/plans")
    def job_plan(job_id: uuid.UUID) -> Response:
        body = json_body()
        response = store.request("GET", f"{internal}/jobs/{job_id}", headers=request.headers)
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

    @api.post(f"{base}/jobs/<uuid:job_id>/runs")
    def run_create(job_id: uuid.UUID) -> Response:
        body = json_body()
        key = request.headers.get("Idempotency-Key", "").strip()
        if not key:
            return problem(422, "idempotency_key_required", "Idempotency-Key is required")
        job_response = store.request("GET", f"{internal}/jobs/{job_id}", headers=request.headers)
        if job_response.status_code >= 400:
            return forward(job_response)
        mode = str(body.get("run_mode", "full_refresh"))
        if mode not in {"full_refresh", "reprocess_cached"}:
            return problem(
                422,
                "capability_unsupported",
                "Only full_refresh and reprocess_cached are supported",
            )
        job_data = job_response.json()["job"]
        scope, scope_error = validate_job_scope(
            job_data,
            resolve_registered_scope(job_data, body.get("scope"), job_profiles),
            run_mode=mode,
        )
        if scope_error is not None:
            return problem(scope_error.status, scope_error.code, scope_error.detail)
        body["scope"] = scope
        body["idempotency_key"] = key
        body["request_id"] = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        return forward(
            store.request(
                "POST", f"{internal}/jobs/{job_id}/runs", headers=request.headers, json=body
            )
        )

    @api.get(f"{base}/ingestion-runs")
    def runs() -> Response:
        return forward(
            store.request("GET", f"{internal}/runs", headers=request.headers, params=request.args)
        )

    @api.get(f"{base}/ingestion-runs/<uuid:run_id>")
    def run(run_id: uuid.UUID) -> Response:
        return forward(store.request("GET", f"{internal}/runs/{run_id}", headers=request.headers))

    for child in ("tasks", "artifacts", "quality-results"):
        endpoint = child.replace("-", "_")

        def run_child(run_id: uuid.UUID, child: str = child) -> Response:
            return forward(
                store.request(
                    "GET",
                    f"{internal}/runs/{run_id}/{child}",
                    headers=request.headers,
                    params=request.args,
                )
            )

        api.add_url_rule(
            f"{base}/ingestion-runs/<uuid:run_id>/{child}", endpoint, run_child, methods=["GET"]
        )

    @api.post(f"{base}/ingestion-runs/<uuid:run_id>/cancel")
    def run_cancel(run_id: uuid.UUID) -> Response:
        try:
            cancellation = store.request(
                "POST",
                f"{internal}/runs/{run_id}/cancel",
                headers=request.headers,
                json=json_body(optional=True),
            )
        except DependencyUnavailableError:
            return reconcile_cancel(run_id)
        if cancellation.status_code < 500:
            return forward(cancellation)
        return reconcile_cancel(run_id)

    def reconcile_cancel(run_id: uuid.UUID) -> Response:
        """Return cancellation only when a read proves its durable request timestamp."""
        try:
            current = store.request("GET", f"{internal}/runs/{run_id}", headers=request.headers)
        except DependencyUnavailableError:
            current = None
        if current is not None and current.status_code < 400:
            try:
                payload = current.json()
            except ValueError:
                payload = None
            run_data = payload.get("run") if isinstance(payload, dict) else None
            if isinstance(run_data, dict) and run_data.get("cancel_requested_at"):
                return forward(current)
        return problem(
            503,
            "cancellation_unconfirmed",
            "The cancellation outcome could not be confirmed; retry this cancellation request",
        )

    def create_follow_up_run(run_id: uuid.UUID, *, run_mode: str) -> Response:
        original = store.request("GET", f"{internal}/runs/{run_id}", headers=request.headers)
        if original.status_code >= 400:
            return forward(original)
        run_data = original.json()["run"]
        key = request.headers.get("Idempotency-Key", "").strip()
        if not key:
            return problem(422, "idempotency_key_required", "Idempotency-Key is required")
        scope, scope_response = complete_lineage_scope(run_data, run_mode=run_mode)
        if scope_response is not None:
            return scope_response
        if run_mode == "reprocess_cached" and run_data.get("requested_scope_json") != scope:
            return problem(
                409,
                "incomplete_legacy_run",
                "Cached artifacts from a historical partial run cannot be reprocessed; "
                "start a new complete update",
            )
        body = {
            "run_mode": run_mode,
            "scope": scope,
            "parent_run_id": str(run_id),
            "idempotency_key": key,
            "request_id": request.headers.get("X-Request-ID", str(uuid.uuid4())),
        }
        return forward(
            store.request(
                "POST",
                f"{internal}/jobs/{run_data['job_definition_id']}/runs",
                headers=request.headers,
                json=body,
            )
        )

    @api.post(f"{base}/ingestion-runs/<uuid:run_id>/resume")
    def run_resume(run_id: uuid.UUID) -> Response:
        original = store.request("GET", f"{internal}/runs/{run_id}", headers=request.headers)
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
                f"{internal}/runs/{run_id}/resume",
                headers=request.headers,
                json=json_body(optional=True),
            )
        )

    @api.post(f"{base}/ingestion-runs/<uuid:run_id>/retry")
    def run_retry(run_id: uuid.UUID) -> Response:
        return create_follow_up_run(run_id, run_mode="full_refresh")

    @api.post(f"{base}/ingestion-runs/<uuid:run_id>/reprocess-cached")
    def run_reprocess(run_id: uuid.UUID) -> Response:
        return create_follow_up_run(run_id, run_mode="reprocess_cached")
