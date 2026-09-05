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
from propertyscope_data_platform.release_projection import (
    public_activation,
    public_consumer_import,
    public_receipt,
)

BASE = "/api/data-platform/v1"
INTERNAL = "/internal/data-platform/v1"
LOCAL_CONSUMER_OPERATION_NAMESPACE = uuid.UUID("f1b44f22-38ae-5f24-9e8d-a2101fc6b14e")


def _catalog_publication_output(
    status: str,
    *,
    receipt_id: object | None,
    replayed: bool,
    status_code: int,
) -> Response:
    """Return the closed assistant-tool result catalog on every publication outcome."""
    response = jsonify(
        {
            "status": status,
            "receipt_id": str(receipt_id) if receipt_id is not None else None,
            "replayed": replayed,
        }
    )
    response.status_code = status_code
    return response


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
    """Verify producer evidence and queue activation independently of downstream imports."""
    current_response = store.request(
        "GET", f"{INTERNAL}/releases/{release_id}", headers=request.headers
    )
    if current_response.status_code >= 400:
        if tool_output:
            return _catalog_publication_output(
                "failed", receipt_id=None, replayed=False, status_code=current_response.status_code
            )
        return forward(current_response)
    envelope = current_response.json()
    release = envelope["release"]
    coverage = release.get("coverage_json")
    if isinstance(coverage, Mapping) and (
        coverage.get("complete") is False or coverage.get("profile") == "psi-year-range"
    ):
        if tool_output:
            return _catalog_publication_output(
                "failed", receipt_id=None, replayed=False, status_code=409
            )
        return problem(
            409,
            "partial_release_not_publishable",
            "A scoped PSI archive-year candidate cannot replace the accepted complete "
            "sales-history generation",
        )
    prior_receipt = next(
        (
            item
            for item in envelope.get("receipts", [])
            if (
                str(item["consumer_operation_id"]).startswith("feature-1-local:")
                or release["target_feature"] == "feature-1"
            )
            and item.get("status") == "accepted"
            and receipt_matches_release(item, release)
        ),
        None,
    )
    prior_operation = next(
        (
            item
            for item in envelope.get("consumer_imports", [])
            if item["idempotency_key"] == idempotency_key
            or consumer_import_matches_release(item, release)
        ),
        None,
    )
    accepted_receipt = next(
        (
            item
            for item in envelope.get("receipts", [])
            if item.get("status") == "accepted" and receipt_matches_release(item, release)
        ),
        None,
    )
    if release["status"] == "accepted" and accepted_receipt:
        if tool_output:
            return jsonify(
                {"status": "accepted", "receipt_id": accepted_receipt["id"], "replayed": True}
            )
        return jsonify(
            {
                "release": release,
                "receipt": public_receipt(accepted_receipt),
                "publication_status": "completed",
                "replayed": True,
            }
        )
    if release["status"] == "accepted" and prior_operation:
        if tool_output:
            return _catalog_publication_output(
                "accepted",
                receipt_id=prior_operation.get("publication_receipt_id"),
                replayed=True,
                status_code=200,
            )
        return jsonify(
            {
                "release": release,
                "consumer_import": public_consumer_import(prior_operation),
                "publication_status": "completed",
                "replayed": True,
                "status_path": (
                    f"{BASE}/dataset-releases/{release_id}/consumer-imports/{prior_operation['id']}"
                ),
            }
        )
    if release["status"] != "awaiting_review":
        if tool_output:
            return _catalog_publication_output(
                "failed", receipt_id=None, replayed=False, status_code=409
            )
        return problem(
            409,
            "release_not_publishable",
            "Only a quality-checked release awaiting review can be published",
        )
    version = body.get("version", release["version"])
    comment = body.get("comment")
    if not isinstance(version, int) or version != release["version"]:
        if tool_output:
            return _catalog_publication_output(
                "failed", receipt_id=None, replayed=False, status_code=409
            )
        return problem(409, "release_version_conflict", "Release version does not match")
    if not isinstance(comment, str) or not comment.strip():
        if tool_output:
            return _catalog_publication_output(
                "failed", receipt_id=None, replayed=False, status_code=422
            )
        return problem(422, "invalid_request", "A non-empty publication comment is required")
    if prior_receipt:
        if not receipt_matches_release(prior_receipt, release):
            if tool_output:
                return _catalog_publication_output(
                    "failed", receipt_id=prior_receipt.get("id"), replayed=True, status_code=409
                )
            return problem(409, "receipt_evidence_conflict", "Receipt evidence does not match")
        if prior_receipt["status"] != "accepted":
            if tool_output:
                return _catalog_publication_output(
                    "failed", receipt_id=prior_receipt.get("id"), replayed=True, status_code=424
                )
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
            idempotency_key=idempotency_key,
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
    result = verify_local_publication(store, release, publication)
    recorded = store.request(
        "POST",
        f"{INTERNAL}/releases/{release_id}/receipts",
        headers=request.headers,
        json={
            "target_feature": "feature-1",
            **result.model_dump(mode="json"),
            "request_id": request.headers.get("X-Request-ID", str(uuid.uuid4())),
        },
    )
    if recorded.status_code >= 400:
        if tool_output:
            return _catalog_publication_output(
                "failed", receipt_id=None, replayed=False, status_code=recorded.status_code
            )
        return forward(recorded)
    receipt_envelope = recorded.json()
    receipt = receipt_envelope["receipt"]
    if result.status != "accepted":
        if tool_output:
            return _catalog_publication_output(
                "failed",
                receipt_id=receipt.get("id"),
                replayed=not receipt_envelope["created"],
                status_code=424,
            )
        return problem(
            424,
            "consumer_publication_failed",
            "Producer artifact verification failed; the prior accepted release remains live",
        )
    return complete_publication(
        store,
        release,
        receipt,
        version=version,
        comment=comment.strip(),
        tool_output=tool_output,
        replayed=not receipt_envelope["created"],
        idempotency_key=idempotency_key,
    )


def receipt_matches_release(receipt: Mapping[str, Any], release: Mapping[str, Any]) -> bool:
    return (
        receipt.get("schema_version") == release.get("schema_version")
        and receipt.get("content_sha256") == release.get("content_sha256")
        and receipt.get("rows_received") == release.get("record_count")
        and receipt.get("rows_accepted") == release.get("record_count")
        and receipt.get("rows_rejected") == 0
    )


def consumer_import_matches_release(
    operation: Mapping[str, Any], release: Mapping[str, Any]
) -> bool:
    return (
        str(operation.get("dataset_release_id")) == str(release.get("id"))
        and operation.get("dataset_id") == release.get("dataset_id")
        and operation.get("target_feature") == release.get("target_feature")
        and operation.get("schema_version") == release.get("schema_version")
        and operation.get("content_sha256") == release.get("content_sha256")
        and operation.get("record_count") == release.get("record_count")
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
    idempotency_key: str | None = None,
) -> Response:
    queued = store.request(
        "POST",
        f"{INTERNAL}/releases/{release['id']}/activations",
        headers=request.headers,
        json={
            "publication_receipt_id": receipt["id"],
            "expected_release_version": version,
            "comment": comment,
            "idempotency_key": idempotency_key or receipt["consumer_operation_id"],
        },
    )
    if queued.status_code >= 400:
        if tool_output:
            return _catalog_publication_output(
                "failed",
                receipt_id=receipt.get("id"),
                replayed=replayed,
                status_code=queued.status_code,
            )
        return forward(queued)
    activation_envelope = queued.json()
    activation = activation_envelope["activation"]
    completed = activation_envelope.get("outcome") == "completed"
    failed = activation.get("status") == "failed"
    if tool_output:
        return _catalog_publication_output(
            "accepted" if completed else "failed" if failed else "pending",
            receipt_id=receipt["id"],
            replayed=replayed,
            status_code=200 if completed else 424 if failed else 202,
        )
    response = jsonify(
        {
            "release": release,
            "receipt": public_receipt(receipt),
            "activation": public_activation(activation),
            "publication_status": "completed" if completed else "failed" if failed else "pending",
            "replayed": replayed,
        }
    )
    response.status_code = 200 if completed else 424 if failed else 202
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
    local_operation_id = _local_consumer_operation_id(publication)
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
            consumer_operation_id=local_operation_id,
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
        consumer_operation_id=local_operation_id,
        status="accepted",
        schema_version=publication.schema_version,
        content_sha256=publication.content_sha256,
        rows_received=publication.record_count,
        rows_accepted=publication.record_count,
        rows_rejected=0,
    )


def _local_consumer_operation_id(publication: ConsumerPublicationRequest) -> str:
    identity = ":".join(
        (
            str(publication.release_id),
            publication.dataset_id,
            publication.schema_version,
            publication.content_sha256,
            str(publication.record_count),
        )
    )
    return f"feature-1-local:{uuid.uuid5(LOCAL_CONSUMER_OPERATION_NAMESPACE, identity)}"


def process_consumer_import(
    store: DataStoreClient,
    consumers: ConsumerImportClient,
    operation: Mapping[str, Any],
    *,
    worker_id: str,
    lease_token: str,
) -> Response:
    """Advance exactly one short, durably leased publication-delivery phase."""
    operation_id = str(operation["id"])
    phase = str(operation["phase_key"])
    publication = ConsumerPublicationRequest(
        release_id=operation["dataset_release_id"],
        dataset_id=operation["dataset_id"],
        schema_version=operation["schema_version"],
        content_sha256=operation["content_sha256"],
        record_count=operation["record_count"],
        manifest=operation["manifest_json"],
        artifact_path=operation["artifact_path"],
        idempotency_key=operation["idempotency_key"],
    )
    lease = {"worker_id": worker_id, "lease_token": lease_token}
    if phase in {"connect", "poll"}:
        outcome = (
            consumers.connect(operation["target_feature"], publication, request.headers)
            if phase == "connect"
            else consumers.poll(
                operation["target_feature"],
                str(operation["consumer_operation_id"]),
                publication,
                request.headers,
            )
        )
        if outcome.consumer_operation_id is None:
            retry = store.request(
                "POST",
                f"{INTERNAL}/consumer-imports/{operation_id}/retry",
                headers=request.headers,
                json={
                    **lease,
                    "error": (
                        outcome.error.model_dump(mode="json")
                        if outcome.error is not None
                        else {
                            "code": "consumer_response_invalid",
                            "message": "Consumer did not return a durable operation reference",
                            "retryable": True,
                        }
                    ),
                    "retry_seconds": 5,
                },
            )
            return forward(retry)
        acknowledgement = store.request(
            "POST",
            f"{INTERNAL}/consumer-imports/{operation_id}/acknowledge",
            headers=request.headers,
            json={
                **lease,
                "consumer_operation_id": outcome.consumer_operation_id,
                "remote_status": outcome.status,
                "result": (
                    outcome.receipt.model_dump(mode="json") if outcome.receipt is not None else None
                ),
                "poll_seconds": 2,
            },
        )
        return forward(acknowledgement)
    if phase == "record_receipt":
        try:
            receipt_result = PublicationReceiptResult.model_validate(operation["result_json"])
        except (KeyError, ValidationError):
            retry = store.request(
                "POST",
                f"{INTERNAL}/consumer-imports/{operation_id}/retry",
                headers=request.headers,
                json={
                    **lease,
                    "error": {
                        "code": "consumer_receipt_invalid",
                        "message": "Persisted consumer result is not a closed receipt",
                        "retryable": False,
                    },
                    "retry_seconds": 5,
                },
            )
            return forward(retry)
        recorded = store.request(
            "POST",
            f"{INTERNAL}/releases/{operation['dataset_release_id']}/receipts",
            headers=request.headers,
            json={
                "target_feature": operation["target_feature"],
                **receipt_result.model_dump(mode="json"),
                "request_id": operation["request_id"],
            },
        )
        if recorded.status_code >= 400:
            return forward(recorded)
        receipt = recorded.json()["receipt"]
        attached = store.request(
            "POST",
            f"{INTERNAL}/consumer-imports/{operation_id}/receipt",
            headers=request.headers,
            json={
                **lease,
                "publication_receipt_id": receipt["id"],
                "receipt_status": receipt["status"],
            },
        )
        return forward(attached)
    if phase == "queue_activation":
        queued = store.request(
            "POST",
            f"{INTERNAL}/releases/{operation['dataset_release_id']}/activations",
            headers=request.headers,
            json={
                "publication_receipt_id": operation["publication_receipt_id"],
                "expected_release_version": operation["expected_release_version"],
                "comment": operation["review_comment"],
                "idempotency_key": (
                    f"consumer-import:{operation_id}:activation:"
                    f"{int(operation.get('activation_attempt', 1))}"
                ),
            },
        )
        if queued.status_code >= 400:
            return forward(queued)
        attached = store.request(
            "POST",
            f"{INTERNAL}/consumer-imports/{operation_id}/activation",
            headers=request.headers,
            json={
                **lease,
                "release_activation_id": queued.json()["activation"]["id"],
            },
        )
        return forward(attached)
    if phase == "wait_activation":
        activation_response = store.request(
            "GET",
            f"{INTERNAL}/activations/{operation['release_activation_id']}",
            headers=request.headers,
        )
        if activation_response.status_code >= 400:
            retry = store.request(
                "POST",
                f"{INTERNAL}/consumer-imports/{operation_id}/retry",
                headers=request.headers,
                json={
                    **lease,
                    "error": {
                        "code": "activation_status_unavailable",
                        "message": "Release activation status is temporarily unavailable",
                        "retryable": True,
                    },
                    "retry_seconds": 5,
                },
            )
            return forward(retry)
        activation = activation_response.json()["activation"]
        activation_outcome = store.request(
            "POST",
            f"{INTERNAL}/consumer-imports/{operation_id}/activation-status",
            headers=request.headers,
            json={
                **lease,
                "activation_status": activation["status"],
                "error": activation.get("error_json"),
                "poll_seconds": 2,
            },
        )
        return forward(activation_outcome)
    return problem(409, "consumer_import_phase_invalid", "Consumer import phase is terminal")
