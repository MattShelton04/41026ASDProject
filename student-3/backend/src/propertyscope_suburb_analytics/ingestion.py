"""Feature-owned consumer: bounded contract discovery, durable jobs and HTTP staging."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import threading
import time
from collections.abc import Mapping
from datetime import date
from typing import Any
from urllib.parse import quote
from uuid import uuid4
from zipfile import ZipFile

import httpx
from jsonschema_rs import Draft202012Validator

from shared_consumer_protocol import (
    ArtifactAccessPolicy,
    ConsumerProtocolError,
    CorrelationContext,
    ImportEvidence,
    ImportReceipt,
    PublicationRequest,
    ReleaseIdentity,
    consume_publication,
)

from .clients import HttpClient, ServiceError

BASE = "/api/data-platform/v1"
IMPORT_PATH = "/api/data-import/v1/propertyscope-releases"
PRODUCTS = {
    "bocsar-crime": ("propertyscope.crime-series.v2", "feature-3", "crime-series.v2.schema.json"),
    "nsw-government-schools": (
        "propertyscope.school-points.v2",
        "feature-3",
        "school-points.v2.schema.json",
    ),
    "abs-seifa-2021": ("propertyscope.seifa-area.v1", "feature-1", "seifa-area.v1.schema.json"),
}


def access_policy(origin: str) -> ArtifactAccessPolicy:
    # Full observed BOCSAR candidate is ~500 MB compressed. No silent truncation.
    return ArtifactAccessPolicy(
        origin,
        BASE + "/dataset-releases/{release_id}/artifact",
        1_000_000_000,
        12_000_000_000,
        1_000_000,
        max_line_bytes=500_000,
    )


def validate_request(payload: dict[str, Any], *, callback: bool = True) -> PublicationRequest:
    request = PublicationRequest.model_validate(payload)
    expected = PRODUCTS.get(request.dataset_id)
    if (
        expected is None
        or request.schema_version != expected[0]
        or request.manifest_binding.target != expected[1]
    ):
        raise ValueError("unsupported_data_product")
    if callback and expected[1] != "feature-3":
        raise ValueError("population_requires_accepted_release_sync")
    if request.manifest.get("download_permitted") is not True:
        raise ValueError("redistribution_not_permitted")
    policy = access_policy("http://producer.invalid")
    policy.url_for(request)
    if (
        request.manifest_binding.byte_count > policy.max_compressed_bytes
        or request.record_count > policy.max_records
    ):
        raise ValueError("import_capacity_exceeded")
    return request


def bounded_get(client: httpx.Client, url: str, limit: int) -> bytes:
    with client.stream("GET", url, follow_redirects=False, timeout=30) as response:
        response.raise_for_status()
        chunks = bytearray()
        for chunk in response.iter_bytes():
            chunks.extend(chunk)
            if len(chunks) > limit:
                raise ValueError("contract_capacity_exceeded")
        return bytes(chunks)


def contract_validators(
    client: httpx.Client, origin: str, request: PublicationRequest
) -> tuple[Any, Any]:
    meta = json.loads(bounded_get(client, origin + BASE + "/product-contracts/v1", 65_536))
    digest = meta["content_sha256"]
    if not re.fullmatch("[0-9a-f]{64}", digest):
        raise ValueError("invalid_contract_digest")
    path = BASE + f"/product-contracts/v1/sha256/{digest}.zip"
    if meta["artifact_path"] != path:
        raise ValueError("invalid_contract_path")
    archive_bytes = bounded_get(client, origin + path, 2_000_000)
    if (
        len(archive_bytes) != meta["byte_count"]
        or hashlib.sha256(archive_bytes).hexdigest() != digest
    ):
        raise ValueError("contract_digest_mismatch")
    with ZipFile(io.BytesIO(archive_bytes)) as archive:
        names = archive.namelist()
        if (
            len(names) != len(set(names))
            or sum(item.file_size for item in archive.infolist()) > 8_000_000
        ):
            raise ValueError("invalid_contract_archive")
        index = json.loads(archive.read("product-contract-set.v1.json"))
        entry = next(
            item for item in index["contracts"] if item["schema_version"] == request.schema_version
        )
        if entry["schema_path"] != PRODUCTS[request.dataset_id][2] or any(
            entry[k] != request.manifest[k]
            for k in (
                "builder_key",
                "builder_version",
                "target_feature",
                "media_type",
                "content_encoding",
            )
        ):
            raise ValueError("contract_binding_mismatch")
        schema = json.loads(archive.read(entry["schema_path"]))
        manifest_schema = json.loads(archive.read("release-manifest.v2.schema.json"))
    # Never resolve remote schema references supplied by the producer archive.
    for schema_item in (schema, manifest_schema):
        if any(not ref.startswith("#/") for ref in references(schema_item)):
            raise ValueError("external_schema_reference")
    record_validator = Draft202012Validator(schema, validate_formats=True)
    manifest_validator = Draft202012Validator(manifest_schema, validate_formats=True)

    def validate(record: Mapping[str, Any], ordinal: int) -> None:
        record_validator.validate(record)
        provenance = record["provenance"]
        for key in (
            "release_id",
            "release_version",
            "candidate_generation_id",
            "normalisation_version",
        ):
            if provenance[key] != request.manifest[key]:
                raise ValueError("record_provenance_mismatch")
        if request.dataset_id == "bocsar-crime":
            months = record["observed_months"]
            if (
                hashlib.sha256(json.dumps(months, separators=(",", ":")).encode()).hexdigest()
                != record["completeness_sha256"]
            ):
                raise ValueError("invalid_coverage_hash")
            if (
                months != sorted(set(months))
                or len(months) != record["month_count"]
                or months[0] != record["first_month"]
                or months[-1] != record["last_month"]
            ):
                raise ValueError("invalid_crime_coverage")
            for month in months:
                if date.fromisoformat(month).day != 1:
                    raise ValueError("invalid_crime_month")
            observations = record["observations"]
            observed_months = set(months)
            if len({item["month"] for item in observations}) != len(observations) or any(
                item["month"] not in observed_months for item in observations
            ):
                raise ValueError("invalid_crime_observations")
        if ordinal < 1:
            raise ValueError("invalid_ordinal")

    return validate, manifest_validator.validate


def references(value: Any) -> list[str]:
    if isinstance(value, dict):
        return ([value["$ref"]] if "$ref" in value else []) + [
            ref for item in value.values() for ref in references(item)
        ]
    if isinstance(value, list):
        return [ref for item in value for ref in references(item)]
    return []


class BeforeCommitError(RuntimeError):
    """A staging flush failed before any commit request was sent."""


def retryable_import_error(exc: Exception) -> bool:
    if not isinstance(exc, ConsumerProtocolError):
        return isinstance(exc, httpx.TransportError)
    if exc.code in {"artifact_transport_failed", "artifact_response_rejected"}:
        return exc.retryable
    original = exc.original_error
    if isinstance(original, BeforeCommitError):
        original = original.__cause__
    return isinstance(original, ServiceError) and original.status == 503


class HttpSink:
    def __init__(self, store: HttpClient, job: dict[str, Any]) -> None:
        self.store, self.job = store, job
        self.items: list[dict[str, Any]] = []
        self.size = 0
        self.rows_received = 0

    def begin(self, identity: ReleaseIdentity, *, consumer_operation_id: str) -> None:
        if consumer_operation_id != self.job["id"]:
            raise ValueError("operation_mismatch")

    def send(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.store.request(
            "POST",
            f"/internal/v1/imports/{self.job['id']}/{action}",
            payload | {"token": self.job["token"]},
        )

    def flush(self) -> None:
        if self.items:
            self.send("stage", {"items": self.items})
            self.items, self.size = [], 0

    def stage(self, record: Mapping[str, Any], *, ordinal: int) -> None:
        self.rows_received = ordinal
        self.items.append({"record": dict(record), "ordinal": ordinal})
        self.size += len(json.dumps(record))
        if self.size >= 500_000 or len(self.items) >= 50:
            self.flush()

    def commit(self, evidence: ImportEvidence) -> None:
        try:
            self.flush()
        except ServiceError as exc:
            raise BeforeCommitError("staging_flush_failed") from exc
        receipt = ImportReceipt(
            **{k: getattr(evidence, k) for k in ReleaseIdentity.model_fields},
            consumer_operation_id=self.job["id"],
            status="accepted",
            rows_received=evidence.rows_received,
            rows_accepted=evidence.rows_received,
            rows_rejected=0,
        )
        self.send("commit", {"receipt": receipt.model_dump(mode="json")})

    def rollback(self) -> None:
        # Failure receipt removes invisible staging atomically; no cleanup after uncertain commit.
        self.items = []


class Ingestion:
    def __init__(self, store: HttpClient, origin: str) -> None:
        self.store, self.origin = store, origin.rstrip("/")
        self.policy = access_policy(self.origin)

    def enqueue(
        self,
        payload: dict[str, Any],
        correlation: dict[str, Any],
        key: str,
        *,
        callback: bool = True,
    ) -> dict[str, Any]:
        request = validate_request(payload, callback=callback)
        if key != request.idempotency_key:
            raise ValueError("idempotency_key_mismatch")
        context = CorrelationContext.model_validate(correlation)
        return self.store.request(
            "POST",
            "/internal/v1/imports",
            {
                "request": request.model_dump(mode="json"),
                "correlation": context.model_dump(mode="json"),
            },
        )

    def sync(self, dataset: str, correlation: dict[str, Any]) -> dict[str, Any]:
        if dataset not in PRODUCTS:
            raise ValueError("unsupported_data_product")
        with httpx.Client() as client:
            release = json.loads(
                bounded_get(
                    client, self.origin + BASE + f"/data-products/{dataset}/accepted", 2_000_000
                )
            )["release"]
        manifest = release["manifest"] if "manifest" in release else release["manifest_json"]
        payload = {
            key: manifest[key]
            for key in ("release_id", "dataset_id", "content_sha256", "record_count")
        }
        payload.update(
            schema_version=manifest["product_schema_version"],
            manifest=manifest,
            artifact_path=BASE + f"/dataset-releases/{quote(manifest['release_id'])}/artifact",
            idempotency_key="sync-" + manifest["release_id"],
        )
        return self.enqueue(payload, correlation, payload["idempotency_key"], callback=False)

    def run_once(self, client: httpx.Client) -> bool:
        job = self.store.request("POST", "/internal/v1/imports/claim", {})
        if not job:
            return False
        request = validate_request(job["request"], callback=False)
        sink = HttpSink(self.store, job)
        try:
            validate, validate_manifest = contract_validators(client, self.origin, request)
            consume_publication(
                request,
                target=PRODUCTS[request.dataset_id][1],
                consumer_operation_id=job["id"],
                correlation=CorrelationContext.model_validate(job["correlation"]),
                policy=self.policy,
                client=client,
                sink=sink,
                record_validator=validate,
                manifest_validator=validate_manifest,
            )
        except Exception as exc:
            if (
                isinstance(exc, ConsumerProtocolError)
                and exc.code == "atomic_commit_outcome_unknown"
                and not isinstance(exc.original_error, BeforeCommitError)
            ):
                # A committed receipt wins. Otherwise leave lease recovery to a later attempt.
                self.store.request("GET", f"/internal/v1/imports/{job['id']}")
                return True
            receipt = {
                key: getattr(request, key)
                for key in (
                    "release_id",
                    "dataset_id",
                    "schema_version",
                    "content_sha256",
                    "record_count",
                )
            }
            receipt.update(
                consumer_operation_id=job["id"],
                target=PRODUCTS[request.dataset_id][1],
                status="failed",
                rows_received=sink.rows_received,
                rows_accepted=0,
                rows_rejected=0,
                error={
                    "code": getattr(exc, "code", "import_validation_failed"),
                    "message": "Import failed validation or transport; "
                    "previous evidence is unchanged.",
                    "retryable": retryable_import_error(exc),
                },
            )
            sink.send("fail", {"receipt": receipt})
        return True

    def start(self) -> None:
        def work() -> None:
            next_sync = 0.0
            with httpx.Client() as client:
                while True:
                    if time.monotonic() >= next_sync:
                        next_sync = time.monotonic() + 900
                        self.reconcile_accepted()
                    try:
                        self.run_once(client)
                    except (ServiceError, httpx.HTTPError, ValueError):
                        logging.getLogger(__name__).warning(
                            "Import worker waiting for dependency recovery"
                        )
                    threading.Event().wait(2)

        threading.Thread(target=work, name="feature-3-imports", daemon=True).start()

    def reconcile_accepted(self) -> None:
        """Discover only approved releases, independent of browser traffic."""
        for dataset in PRODUCTS:
            try:
                self.sync(dataset, {"request_id": str(uuid4())})
            except (ServiceError, httpx.HTTPError, ValueError, KeyError, TypeError):
                logging.getLogger(__name__).info("Accepted release unavailable for %s", dataset)


def correlation(environ: dict[str, Any]) -> dict[str, Any]:
    return {
        "request_id": environ.get("HTTP_X_REQUEST_ID") or str(uuid4()),
        "traceparent": environ.get("HTTP_TRACEPARENT"),
    }
