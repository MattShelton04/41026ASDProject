"""Safe, format-aware import of Feature 1 publication artifacts."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import uuid
import zlib
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from jsonschema import Draft202012Validator, FormatChecker

from .feature1_client import AcceptedRelease, Feature1Client

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SCHEMA_VERSION = re.compile(r"^[a-z0-9][a-z0-9._-]{0,99}$")
_TARGET_FEATURE = re.compile(r"^feature-[1-5]$")
_RECORD_DEFINITION = {
    "propertyscope.property-snapshot.v1": "PropertySnapshotRecord",
    "propertyscope.property-sales.v2": "PropertySaleRecord",
    "propertyscope.crime-series.v1": "CrimeSeriesRecord",
    "propertyscope.school-points.v1": "SchoolPointRecord",
}


class PublicationImportError(ValueError):
    """A publication could not be safely imported."""


class PublicationConflictError(PublicationImportError):
    """An idempotency key was reused for different release evidence."""


@dataclass(frozen=True, slots=True)
class PublicationRequest:
    release_id: uuid.UUID
    dataset_id: str
    target_feature: str
    schema_version: str
    content_sha256: str
    record_count: int
    manifest: Mapping[str, Any]
    artifact_path: str
    idempotency_key: str

    @classmethod
    def from_callback(
        cls,
        payload: Mapping[str, Any],
        *,
        header_idempotency_key: str,
    ) -> PublicationRequest:
        required = {
            "release_id",
            "dataset_id",
            "schema_version",
            "content_sha256",
            "record_count",
            "manifest",
            "artifact_path",
            "idempotency_key",
        }
        if set(payload) != required:
            raise PublicationImportError("publication request fields do not match v1")
        body_key = payload.get("idempotency_key")
        if not isinstance(body_key, str) or body_key != header_idempotency_key:
            raise PublicationImportError("header and body idempotency keys must match")
        try:
            request = cls(
                release_id=uuid.UUID(str(payload["release_id"])),
                dataset_id=str(payload["dataset_id"]),
                target_feature=str(cast_manifest(payload["manifest"])["target_feature"]),
                schema_version=str(payload["schema_version"]),
                content_sha256=str(payload["content_sha256"]),
                record_count=int(payload["record_count"]),
                manifest=dict(cast_manifest(payload["manifest"])),
                artifact_path=str(payload["artifact_path"]),
                idempotency_key=body_key,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise PublicationImportError("publication request is malformed") from exc
        request.validate()
        return request

    @classmethod
    def from_accepted(cls, release: AcceptedRelease) -> PublicationRequest:
        key = f"reconcile-{release.target_feature}-{release.release_id}"
        request = cls(
            release_id=release.release_id,
            dataset_id=release.dataset_id,
            target_feature=release.target_feature,
            schema_version=release.schema_version,
            content_sha256=release.content_sha256,
            record_count=release.record_count,
            manifest=dict(release.manifest),
            artifact_path=release.artifact_path,
            idempotency_key=key,
        )
        request.validate()
        return request

    def validate(self) -> None:
        manifest = self.manifest
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,99}", self.dataset_id):
            raise PublicationImportError("dataset ID is invalid")
        if not _TARGET_FEATURE.fullmatch(self.target_feature):
            raise PublicationImportError("target feature is invalid")
        if not _SCHEMA_VERSION.fullmatch(self.schema_version):
            raise PublicationImportError("schema version is invalid")
        if self.schema_version not in _RECORD_DEFINITION:
            raise PublicationImportError("product schema is not supported")
        if not _SHA256.fullmatch(self.content_sha256) or self.record_count < 0:
            raise PublicationImportError("checksum or record count is invalid")
        if not 8 <= len(self.idempotency_key) <= 200:
            raise PublicationImportError("idempotency key is outside contract bounds")
        expected_path = f"/api/data-platform/v1/dataset-releases/{self.release_id}/artifact"
        if self.artifact_path != expected_path:
            raise PublicationImportError("artifact path is not bound to the release")
        expected = {
            "release_id": str(self.release_id),
            "dataset_id": self.dataset_id,
            "target_feature": self.target_feature,
            "product_schema_version": self.schema_version,
            "content_sha256": self.content_sha256,
            "record_count": self.record_count,
        }
        for key, value in expected.items():
            if manifest.get(key) != value:
                raise PublicationImportError(f"manifest {key} does not match publication")
        if manifest.get("manifest_schema_version") != "propertyscope.release-manifest.v1":
            raise PublicationImportError("manifest schema version is unsupported")
        try:
            byte_count = int(manifest["byte_count"])
            uuid.UUID(str(manifest["candidate_generation_id"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise PublicationImportError("manifest artifact evidence is malformed") from exc
        if byte_count < 1:
            raise PublicationImportError("manifest byte count must be positive")
        media_type = manifest.get("media_type")
        encoding = manifest.get("content_encoding")
        if (media_type, encoding) not in {
            ("application/x-ndjson", "gzip"),
            ("application/json", None),
        }:
            raise PublicationImportError("artifact media type or encoding is unsupported")


@dataclass(frozen=True, slots=True)
class PublicationReceipt:
    consumer_operation_id: str
    status: str
    schema_version: str
    content_sha256: str
    rows_received: int
    rows_accepted: int
    rows_rejected: int
    error: Mapping[str, Any] | None = None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> PublicationReceipt:
        try:
            receipt = cls(
                consumer_operation_id=str(payload["consumer_operation_id"]),
                status=str(payload["status"]),
                schema_version=str(payload["schema_version"]),
                content_sha256=str(payload["content_sha256"]),
                rows_received=int(payload["rows_received"]),
                rows_accepted=int(payload["rows_accepted"]),
                rows_rejected=int(payload["rows_rejected"]),
                error=payload.get("error") if isinstance(payload.get("error"), Mapping) else None,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise PublicationImportError("store returned a malformed publication receipt") from exc
        if receipt.status not in {"accepted", "rejected", "failed"}:
            raise PublicationImportError("store returned an invalid receipt status")
        return receipt

    def as_dict(self) -> dict[str, Any]:
        return {
            "consumer_operation_id": self.consumer_operation_id,
            "status": self.status,
            "schema_version": self.schema_version,
            "content_sha256": self.content_sha256,
            "rows_received": self.rows_received,
            "rows_accepted": self.rows_accepted,
            "rows_rejected": self.rows_rejected,
            "error": dict(self.error) if self.error is not None else None,
        }


@dataclass(frozen=True, slots=True)
class StoredPublication:
    request: PublicationRequest
    receipt: PublicationReceipt


class PublicationStore(Protocol):
    """Transaction-owning consumer persistence seam."""

    def find_publication(
        self, target_feature: str, idempotency_key: str
    ) -> StoredPublication | None: ...

    def import_release_atomic(
        self,
        publication: PublicationRequest,
        records: Iterable[Mapping[str, Any]],
    ) -> Mapping[str, Any]:
        """Consume records inside one transaction and return the durable receipt."""
        ...


class RecordValidator(Protocol):
    def validate(self, schema_version: str, record: Mapping[str, Any]) -> None: ...


class JsonSchemaRecordValidator:
    """Compile Feature 1's public envelope schemas into per-record validators."""

    def __init__(self, schemas: Mapping[str, Mapping[str, Any]]) -> None:
        validators: dict[str, Draft202012Validator] = {}
        for schema_version, definition_name in _RECORD_DEFINITION.items():
            schema = schemas.get(schema_version)
            if schema is None:
                continue
            definitions = schema.get("$defs")
            if not isinstance(definitions, Mapping) or definition_name not in definitions:
                raise ValueError(f"schema has no {definition_name} definition")
            record_schema = {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "$defs": dict(definitions),
                "$ref": f"#/$defs/{definition_name}",
            }
            Draft202012Validator.check_schema(record_schema)
            validators[schema_version] = Draft202012Validator(
                record_schema, format_checker=FormatChecker()
            )
        self._validators = validators

    def validate(self, schema_version: str, record: Mapping[str, Any]) -> None:
        validator = self._validators.get(schema_version)
        if validator is None:
            raise PublicationImportError(f"no validator is registered for {schema_version}")
        errors = sorted(validator.iter_errors(record), key=lambda item: tuple(item.path))
        if errors:
            raise PublicationImportError(f"product record is invalid: {errors[0].message}")


class PublicationImporter:
    """Validate, stream and atomically persist one publication or reconciliation pull."""

    def __init__(
        self,
        feature1: Feature1Client,
        store: PublicationStore,
        validator: RecordValidator,
        *,
        maximum_artifact_bytes: int = 250_000_000,
        maximum_legacy_json_bytes: int = 50_000_000,
    ) -> None:
        if maximum_artifact_bytes < 1 or maximum_legacy_json_bytes < 1:
            raise ValueError("artifact limits must be positive")
        self._feature1 = feature1
        self._store = store
        self._validator = validator
        self._maximum_artifact_bytes = maximum_artifact_bytes
        self._maximum_legacy_json_bytes = maximum_legacy_json_bytes

    def import_callback(
        self,
        payload: Mapping[str, Any],
        *,
        header_idempotency_key: str,
        headers: Mapping[str, str] | None = None,
    ) -> PublicationReceipt:
        publication = PublicationRequest.from_callback(
            payload, header_idempotency_key=header_idempotency_key
        )
        return self.import_publication(publication, headers=headers)

    def reconcile_accepted(
        self,
        dataset_id: str,
        target_feature: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> PublicationReceipt | None:
        accepted = self._feature1.accepted_release(dataset_id, target_feature, headers=headers)
        if accepted is None:
            return None
        return self.import_publication(PublicationRequest.from_accepted(accepted), headers=headers)

    def import_publication(
        self,
        publication: PublicationRequest,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> PublicationReceipt:
        publication.validate()
        existing = self._store.find_publication(
            publication.target_feature, publication.idempotency_key
        )
        if existing is not None:
            if not _same_evidence(existing.request, publication):
                raise PublicationConflictError(
                    "idempotency key is already bound to different release evidence"
                )
            _validate_receipt(existing.receipt, publication)
            return existing.receipt

        with self._feature1.stream_artifact(
            publication.artifact_path,
            release_id=publication.release_id,
            headers=headers,
        ) as response:
            _validate_digest_header(response, publication.content_sha256)
            records = self._records(publication, response.iter_raw())
            receipt = PublicationReceipt.from_mapping(
                self._store.import_release_atomic(publication, records)
            )
        _validate_receipt(receipt, publication)
        return receipt

    def _records(
        self, publication: PublicationRequest, raw_chunks: Iterable[bytes]
    ) -> Iterator[Mapping[str, Any]]:
        media_type = publication.manifest["media_type"]
        encoding = publication.manifest.get("content_encoding")
        if (media_type, encoding) == ("application/x-ndjson", "gzip"):
            yield from self._gzip_ndjson_records(publication, raw_chunks)
            return
        yield from self._legacy_json_records(publication, raw_chunks)

    def _gzip_ndjson_records(
        self, publication: PublicationRequest, raw_chunks: Iterable[bytes]
    ) -> Iterator[Mapping[str, Any]]:
        digest = hashlib.sha256()
        raw_count = 0
        buffer = b""
        decompressor = zlib.decompressobj(wbits=31)
        records = 0
        for chunk in raw_chunks:
            raw_count = _observe_raw(
                publication,
                chunk,
                digest,
                raw_count,
                maximum=self._maximum_artifact_bytes,
            )
            try:
                buffer += decompressor.decompress(chunk)
            except zlib.error as exc:
                raise PublicationImportError("artifact is not valid gzip data") from exc
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                if not line:
                    raise PublicationImportError("NDJSON artifact contains an empty record")
                record = _json_object(line)
                self._validate_record(publication, record)
                records += 1
                yield record
        try:
            buffer += decompressor.flush()
        except zlib.error as exc:
            raise PublicationImportError("artifact gzip stream is incomplete") from exc
        if not decompressor.eof or decompressor.unused_data:
            raise PublicationImportError("artifact gzip stream is incomplete or concatenated")
        if buffer:
            record = _json_object(buffer)
            self._validate_record(publication, record)
            records += 1
            yield record
        _validate_artifact_totals(publication, digest.hexdigest(), raw_count, records)

    def _legacy_json_records(
        self, publication: PublicationRequest, raw_chunks: Iterable[bytes]
    ) -> Iterator[Mapping[str, Any]]:
        digest = hashlib.sha256()
        raw_count = 0
        content = bytearray()
        maximum = min(self._maximum_artifact_bytes, self._maximum_legacy_json_bytes)
        for chunk in raw_chunks:
            raw_count = _observe_raw(publication, chunk, digest, raw_count, maximum=maximum)
            content.extend(chunk)
        envelope = _json_object(bytes(content))
        expected = {
            "schema_version": publication.schema_version,
            "release_id": str(publication.release_id),
            "release_version": publication.manifest["release_version"],
            "dataset_id": publication.dataset_id,
            "target_feature": publication.target_feature,
            "candidate_generation_id": publication.manifest["candidate_generation_id"],
        }
        for key, value in expected.items():
            if envelope.get(key) != value:
                raise PublicationImportError(f"product envelope {key} does not match publication")
        records_value = envelope.get("records")
        if not isinstance(records_value, list):
            raise PublicationImportError("legacy product envelope has no records array")
        for record in records_value:
            if not isinstance(record, Mapping):
                raise PublicationImportError("product record is not an object")
            self._validate_record(publication, record)
            yield record
        _validate_artifact_totals(publication, digest.hexdigest(), raw_count, len(records_value))

    def _validate_record(self, publication: PublicationRequest, record: Mapping[str, Any]) -> None:
        self._validator.validate(publication.schema_version, record)
        provenance = record.get("provenance")
        if not isinstance(provenance, Mapping):
            raise PublicationImportError("product record has no provenance")
        expected = {
            "release_id": str(publication.release_id),
            "release_version": publication.manifest["release_version"],
            "candidate_generation_id": publication.manifest["candidate_generation_id"],
            "normalisation_version": publication.manifest["normalisation_version"],
        }
        for key, value in expected.items():
            if provenance.get(key) != value:
                raise PublicationImportError(f"record provenance {key} does not match manifest")


def cast_manifest(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PublicationImportError("publication manifest must be an object")
    return value


def _json_object(value: bytes) -> Mapping[str, Any]:
    try:
        payload = json.loads(value)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublicationImportError("artifact contains invalid UTF-8 JSON") from exc
    if not isinstance(payload, Mapping):
        raise PublicationImportError("artifact record must be a JSON object")
    return payload


def _observe_raw(
    publication: PublicationRequest,
    chunk: bytes,
    digest: Any,
    count: int,
    *,
    maximum: int,
) -> int:
    next_count = count + len(chunk)
    manifest_bytes = int(publication.manifest["byte_count"])
    if next_count > manifest_bytes or next_count > maximum:
        raise PublicationImportError("artifact exceeds its declared or consumer byte limit")
    digest.update(chunk)
    return next_count


def _validate_artifact_totals(
    publication: PublicationRequest, digest: str, byte_count: int, record_count: int
) -> None:
    if byte_count != int(publication.manifest["byte_count"]):
        raise PublicationImportError("artifact byte count does not match manifest")
    if digest != publication.content_sha256:
        raise PublicationImportError("artifact checksum does not match publication")
    if record_count != publication.record_count:
        raise PublicationImportError("artifact record count does not match publication")


def _validate_digest_header(response: Any, expected_sha256: str) -> None:
    expected = base64.b64encode(bytes.fromhex(expected_sha256)).decode()
    if response.headers.get("Digest") != f"sha-256=:{expected}:":
        raise PublicationImportError("artifact Digest header is missing or mismatched")


def _same_evidence(left: PublicationRequest, right: PublicationRequest) -> bool:
    return (
        left.release_id,
        left.dataset_id,
        left.target_feature,
        left.schema_version,
        left.content_sha256,
        left.record_count,
        left.artifact_path,
    ) == (
        right.release_id,
        right.dataset_id,
        right.target_feature,
        right.schema_version,
        right.content_sha256,
        right.record_count,
        right.artifact_path,
    )


def _validate_receipt(receipt: PublicationReceipt, publication: PublicationRequest) -> None:
    if (
        receipt.consumer_operation_id != publication.idempotency_key
        or receipt.schema_version != publication.schema_version
        or receipt.content_sha256 != publication.content_sha256
        or receipt.rows_received > publication.record_count
    ):
        raise PublicationImportError("consumer receipt does not match publication evidence")
    if receipt.status == "accepted" and (
        receipt.rows_received != publication.record_count
        or receipt.rows_accepted != publication.record_count
        or receipt.rows_rejected != 0
    ):
        raise PublicationImportError("accepted receipt does not account for every record")


def contract_friction_notes() -> tuple[str, ...]:
    """Machine-visible POC findings that should be resolved before owner integrations."""
    return (
        "Live artifacts are gzip NDJSON records while the v1 guide and HTTP reference test "
        "describe a JSON envelope.",
        "Product schemas define an envelope; live consumers must select the matching $defs "
        "record schema.",
        "The synchronous provider callback timeout is short for source-scale validation and "
        "atomic import.",
        "Feature 4 has no registered product and Feature 5 is a pull-based composition owner.",
        "G-NAF redistribution blocks artifact download, so consumers use property identity/report "
        "APIs.",
    )
