"""Private worker HTTP routes for the Feature 1 data platform."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from typing import Any

from flask import Blueprint, Response, jsonify, request

from propertyscope_data_platform.clients import ConsumerImportClient, DataStoreClient
from propertyscope_data_platform.http_support import (
    forward,
    forward_json_bytes,
    json_body,
    problem,
)
from propertyscope_data_platform.release_builders import BuildContext, resolve_release_builder
from propertyscope_data_platform.release_publication import process_consumer_import

WorkerOperation = Callable[[DataStoreClient, uuid.UUID, Mapping[str, Any]], Response]


def register_worker_routes(
    api: Blueprint,
    store: DataStoreClient,
    consumers: ConsumerImportClient,
    *,
    internal: str,
    ensure_import_operation: WorkerOperation,
    finalize_candidate_release: WorkerOperation,
) -> None:
    """Register the private runner boundary on ``api``."""

    @api.post(f"{internal}/worker/consumer-imports/claim")
    def worker_consumer_import_claim() -> Response:
        return forward(
            store.request(
                "POST",
                f"{internal}/consumer-imports/claim",
                headers=request.headers,
                json=json_body(),
            )
        )

    @api.post(f"{internal}/worker/consumer-imports/<uuid:operation_id>/step")
    def worker_consumer_import_step(operation_id: uuid.UUID) -> Response:
        body = json_body()
        operation_response = store.request(
            "GET", f"{internal}/consumer-imports/{operation_id}", headers=request.headers
        )
        if operation_response.status_code >= 400:
            return forward(operation_response)
        operation = operation_response.json()["operation"]
        worker_id = str(body.get("worker_id", ""))
        lease_token = str(body.get("lease_token", ""))
        if (
            not worker_id
            or not lease_token
            or operation.get("status") != "claimed"
            or operation.get("lease_owner") != worker_id
            or operation.get("lease_token") != lease_token
        ):
            return problem(409, "consumer_import_lease_conflict", "Consumer import lease is stale")
        return process_consumer_import(
            store,
            consumers,
            operation,
            worker_id=worker_id,
            lease_token=lease_token,
        )

    @api.post(f"{internal}/worker/tasks/claim")
    def worker_claim() -> Response:
        return forward(
            store.request(
                "POST", f"{internal}/worker/tasks/claim", headers=request.headers, json=json_body()
            )
        )

    for action in ("heartbeat", "complete", "fail", "artifacts"):

        def worker_action(task_id: uuid.UUID, action: str = action) -> Response:
            return forward(
                store.request(
                    "POST",
                    f"{internal}/worker/tasks/{task_id}/{action}",
                    headers=request.headers,
                    json=json_body(),
                )
            )

        api.add_url_rule(
            f"{internal}/worker/tasks/<uuid:task_id>/{action}",
            f"worker_{action}",
            worker_action,
            methods=["POST"],
        )

    @api.post(f"{internal}/worker/runs/<uuid:run_id>/imports")
    def worker_import(run_id: uuid.UUID) -> Response:
        return ensure_import_operation(store, run_id, json_body())

    @api.get(f"{internal}/worker/imports/<uuid:operation_id>")
    def worker_import_get(operation_id: uuid.UUID) -> Response:
        return forward(
            store.request("GET", f"{internal}/imports/{operation_id}", headers=request.headers)
        )

    @api.post(f"{internal}/worker/runs/<uuid:run_id>/finalize-release")
    def worker_finalize_release(run_id: uuid.UUID) -> Response:
        return finalize_candidate_release(store, run_id, json_body())

    @api.get(f"{internal}/worker/runs/<uuid:run_id>/release-build-context")
    def worker_release_build_context(run_id: uuid.UUID) -> Response:
        upstream = store.request(
            "GET", f"{internal}/runs/{run_id}/release-build-context", headers=request.headers
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

    @api.get(f"{internal}/worker/releases/<uuid:release_id>/product-records")
    def worker_release_product_records(release_id: uuid.UUID) -> Response:
        return forward_json_bytes(
            store.request(
                "GET",
                f"{internal}/releases/{release_id}/product-records",
                headers=request.headers,
                params=request.args,
                timeout=120,
            )
        )
