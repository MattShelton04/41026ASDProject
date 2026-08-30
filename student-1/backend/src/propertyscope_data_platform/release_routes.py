"""Dataset release routes and publication/import orchestration."""

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
from propertyscope_data_platform.clients import ConsumerImportClient, DataStoreClient
from propertyscope_data_platform.domain import ConsumerPublicationRequest, PublicationReceiptResult
from propertyscope_data_platform.http_support import (
    forward,
    json_body,
    problem,
    proxy_collection,
    proxy_item,
    required_uuid,
)
from propertyscope_data_platform.release_builders import (
    ReleaseDetailContract,
    ReleaseManifestV1,
    resolve_release_builder,
)

BASE = "/api/data-platform/v1"
INTERNAL = "/internal/data-platform/v1"


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

