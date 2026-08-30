"""HTTP registration for dataset release inspection and publication."""

from __future__ import annotations

import base64
import uuid
from pathlib import Path

from flask import Blueprint, Response, jsonify, request, send_file
from pydantic import ValidationError

from propertyscope_data_platform.artifacts import ArtifactError, LocalArtifactStore
from propertyscope_data_platform.clients import ConsumerImportClient, DataStoreClient
from propertyscope_data_platform.http_support import (
    forward,
    json_body,
    problem,
    proxy_collection,
    proxy_item,
)
from propertyscope_data_platform.release_builders import ReleaseManifestV1
from propertyscope_data_platform.release_imports import (
    ensure_import_operation,
    finalize_candidate_release,
)
from propertyscope_data_platform.release_projection import (
    public_activation,
    public_consumer_import,
    public_receipt,
    release_detail_contract,
    release_inspection,
)
from propertyscope_data_platform.release_publication import (
    complete_publication,
    publish_release,
    receipt_matches_release,
    transition,
    verify_local_publication,
)

BASE = "/api/data-platform/v1"
INTERNAL = "/internal/data-platform/v1"

__all__ = (
    "complete_publication",
    "ensure_import_operation",
    "finalize_candidate_release",
    "public_activation",
    "public_receipt",
    "publish_release",
    "receipt_matches_release",
    "register_release_routes",
    "release_detail_contract",
    "release_inspection",
    "transition",
    "verify_local_publication",
)


def register_release_routes(
    api: Blueprint,
    store: DataStoreClient,
    consumers: ConsumerImportClient,
    *,
    artifact_root: Path,
) -> None:
    """Register release inspection, artifact, review, and publication routes."""

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
        return transition(store, release_id, "awaiting_review", json_body())

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

    @api.get(f"{BASE}/dataset-releases/<uuid:release_id>/consumer-imports/<uuid:operation_id>")
    def release_consumer_import(release_id: uuid.UUID, operation_id: uuid.UUID) -> Response:
        upstream = store.request(
            "GET", f"{INTERNAL}/consumer-imports/{operation_id}", headers=request.headers
        )
        if upstream.status_code >= 400:
            return forward(upstream)
        operation = upstream.json()["operation"]
        if str(operation["dataset_release_id"]) != str(release_id):
            return problem(404, "consumer_import_not_found", "Consumer import does not exist")
        activation = None
        publication_status = {
            "published": "completed",
            "rejected": "failed",
            "failed": "failed",
        }.get(str(operation["status"]), "pending")
        if operation.get("release_activation_id"):
            activation_response = store.request(
                "GET",
                f"{INTERNAL}/activations/{operation['release_activation_id']}",
                headers=request.headers,
            )
            if activation_response.status_code < 400:
                activation = public_activation(activation_response.json()["activation"])
                publication_status = {
                    "succeeded": "completed",
                    "failed": "failed",
                }.get(str(activation["status"]), "pending")
        return jsonify(
            {
                "consumer_import": public_consumer_import(operation),
                "activation": activation,
                "publication_status": publication_status,
            }
        )

    @api.post(f"{BASE}/dataset-releases/<uuid:release_id>/reject")
    def release_reject(release_id: uuid.UUID) -> Response:
        return transition(store, release_id, "rejected", json_body())
