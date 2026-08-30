"""Public release evidence projections and inspection composition."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from flask import Response, jsonify, request
from pydantic import ValidationError

from propertyscope_data_platform.clients import DataStoreClient
from propertyscope_data_platform.domain import PublicationReceiptResult
from propertyscope_data_platform.http_support import forward
from propertyscope_data_platform.release_builders import ReleaseDetailContract

INTERNAL = "/internal/data-platform/v1"
CONSUMER_CONNECT_TIMEOUT_SECONDS = 5
CONSUMER_STATUS_TIMEOUT_SECONDS = 5
CONSUMER_RESPONSE_MAX_BYTES = 64 * 1024


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
        "consumer_imports": [
            public_consumer_import(item) for item in release_envelope.get("consumer_imports", [])
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


def public_consumer_import(operation: Mapping[str, Any]) -> dict[str, Any]:
    """Expose durable delivery progress without worker credentials or review comments."""
    projected = {
        key: operation.get(key)
        for key in (
            "id",
            "dataset_release_id",
            "dataset_id",
            "target_feature",
            "schema_version",
            "content_sha256",
            "record_count",
            "status",
            "phase_key",
            "remote_status",
            "consumer_operation_id",
            "publication_receipt_id",
            "release_activation_id",
            "attempt_number",
            "requested_at",
            "started_at",
            "finished_at",
            "error_json",
            "version",
        )
    }
    projected["budgets"] = {
        "connect_timeout_seconds": CONSUMER_CONNECT_TIMEOUT_SECONDS,
        "status_timeout_seconds": CONSUMER_STATUS_TIMEOUT_SECONDS,
        "maximum_response_bytes": CONSUMER_RESPONSE_MAX_BYTES,
    }
    return projected
