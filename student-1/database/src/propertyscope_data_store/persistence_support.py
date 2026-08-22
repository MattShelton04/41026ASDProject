"""Pure serialization, projection, and replay-validation helpers."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from propertyscope_data_store.errors import ConflictError

JsonObject = dict[str, Any]


def json_document(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def project_run(run: JsonObject) -> JsonObject:
    """Add explicit retry semantics without claiming parent artifacts were reused."""
    projected = dict(run)
    if projected.get("parent_run_id") is None:
        projected["execution_semantics"] = "new_pipeline_run"
    elif projected.get("run_mode") == "reprocess_cached":
        projected["execution_semantics"] = "cached_artifact_reprocess"
    else:
        projected["execution_semantics"] = "full_pipeline_retry"
    return projected


def validate_artifact_replay(existing: Mapping[str, Any], values: Mapping[str, Any]) -> None:
    expected = (
        values["content_sha256"],
        values["storage_key"],
        values["media_type"],
        int(values["bytes"]),
    )
    actual = (
        existing["content_sha256"],
        existing["storage_key"],
        existing["media_type"],
        int(existing["bytes"]),
    )
    if expected != actual:
        raise ConflictError("artifact idempotency key arguments do not match")


def receipt_matches_values(
    receipt: Mapping[str, Any], release_id: uuid.UUID, values: Mapping[str, Any]
) -> bool:
    expected = (
        str(release_id),
        values["status"],
        values["schema_version"],
        values["content_sha256"],
        int(values["rows_received"]),
        int(values["rows_accepted"]),
        int(values["rows_rejected"]),
    )
    actual = (
        str(receipt["dataset_release_id"]),
        receipt["status"],
        receipt["schema_version"],
        receipt["content_sha256"],
        int(receipt["rows_received"]),
        int(receipt["rows_accepted"]),
        int(receipt["rows_rejected"]),
    )
    return expected == actual


def require_source_snapshot(values: Mapping[str, Any]) -> Mapping[str, Any]:
    snapshot = values.get("source_snapshot")
    if not isinstance(snapshot, dict):
        raise ConflictError("source snapshot metadata is required")
    source_release = snapshot.get("source_release")
    if not isinstance(source_release, str) or not 1 <= len(source_release) <= 100:
        raise ConflictError("source snapshot release evidence is invalid")
    objects = snapshot.get("objects")
    if not isinstance(objects, list) or not objects:
        raise ConflictError("source snapshot object evidence is invalid")
    return snapshot


def cancellation_error() -> JsonObject:
    return {"code": "operator_cancelled", "message": "Run cancelled by operator"}


def lease_expired_error() -> JsonObject:
    return {
        "code": "task_lease_expired",
        "message": "Worker heartbeat expired; explicit resume is required",
        "retryable": True,
    }


def normalise_row(row: Mapping[str, Any] | None) -> JsonObject:
    if row is None:
        raise RuntimeError("expected database row")
    return {key: normalise_value(value) for key, value in row.items()}


def normalise_rows(rows: Sequence[Mapping[str, Any]]) -> list[JsonObject]:
    return [normalise_row(row) for row in rows]


def normalise_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value
