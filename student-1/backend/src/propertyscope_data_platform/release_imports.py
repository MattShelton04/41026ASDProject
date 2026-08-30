"""Candidate-release binding and serial import orchestration."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from flask import Response, request
from pydantic import ValidationError

from propertyscope_data_platform.clients import DataStoreClient
from propertyscope_data_platform.http_support import forward, problem, required_uuid
from propertyscope_data_platform.release_builders import ReleaseManifestV1

INTERNAL = "/internal/data-platform/v1"


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
