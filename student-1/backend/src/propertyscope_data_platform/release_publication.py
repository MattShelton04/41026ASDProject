"""Release review transitions and receipt-backed publication orchestration."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

import httpx
from flask import Response, jsonify, request
from pydantic import ValidationError

from propertyscope_data_platform.artifacts import ArtifactError
from propertyscope_data_platform.clients import ConsumerImportClient, DataStoreClient
from propertyscope_data_platform.domain import ConsumerPublicationRequest, PublicationReceiptResult
from propertyscope_data_platform.http_support import forward, problem
from propertyscope_data_platform.release_builders import ReleaseManifestV1, resolve_release_builder
from propertyscope_data_platform.release_projection import public_activation, public_receipt

BASE = "/api/data-platform/v1"
INTERNAL = "/internal/data-platform/v1"


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

    Release construction schema-validates every projected row while the artifact store hashes and
    fsyncs the immutable content-addressed object. Publication therefore verifies the durable
    registration rather than repeating a complete byte and schema pass during an HTTP request.
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
