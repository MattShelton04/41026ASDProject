"""Bounded HTTP transport and atomic gzip-NDJSON consumer handoff."""

from __future__ import annotations

import hashlib
import json
import zlib
from collections.abc import Callable, Iterator, Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from pydantic import TypeAdapter

from shared_contracts.http import (
    IDEMPOTENCY_KEY_HEADER,
    REQUEST_ID_HEADER,
    TRACEPARENT_HEADER,
)

from .contracts import (
    CorrelationContext,
    Identifier,
    ImportEvidence,
    ImportReceipt,
    PublicationRequest,
    ReleaseIdentity,
    immutable_identity,
)

Record = Mapping[str, Any]
RecordValidator = Callable[[Record, int], None]
ManifestValidator = Callable[[Mapping[str, Any]], None]
_OPERATION_ID_ADAPTER = TypeAdapter(Identifier)


class ConsumerProtocolError(RuntimeError):
    """Safe, stable failure from the consumer protocol boundary."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        original_error: BaseException | None = None,
        cleanup_error: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.original_error = original_error
        self.cleanup_error = cleanup_error


class AtomicImportSink(Protocol):
    """Consumer-owned transaction/staging boundary.

    ``stage`` must not make records externally visible. ``commit`` must atomically expose the
    complete candidate and persist its evidence. ``rollback`` must remove staged state.
    """

    def begin(self, identity: ReleaseIdentity, *, consumer_operation_id: str) -> None: ...

    def stage(self, record: Record, *, ordinal: int) -> None: ...

    def commit(self, evidence: ImportEvidence) -> None: ...

    def rollback(self) -> None: ...


@dataclass(frozen=True, slots=True)
class ArtifactAccessPolicy:
    """Fixed producer origin/path and hard resource limits for artifact retrieval."""

    origin: str
    artifact_path_template: str
    max_compressed_bytes: int
    max_uncompressed_bytes: int
    max_records: int
    max_line_bytes: int = 2_000_000
    timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        origin = httpx.URL(self.origin)
        if (
            origin.scheme not in {"http", "https"}
            or not origin.host
            or bool(origin.username)
            or bool(origin.password)
            or origin.query
            or origin.fragment
            or origin.path not in {"", "/"}
        ):
            raise ValueError("origin must be an HTTP(S) authority without credentials or a path")
        template = self.artifact_path_template
        if (
            not template.startswith("/")
            or template.count("{release_id}") != 1
            or template.count("{") != 1
            or template.count("}") != 1
            or "\\" in template
            or "?" in template
            or "#" in template
            or any(part == ".." for part in template.split("/"))
        ):
            raise ValueError("artifact_path_template must be one fixed absolute release path")
        if (
            self.max_compressed_bytes < 1
            or self.max_uncompressed_bytes < 1
            or self.max_records < 1
            or self.max_line_bytes < 1
            or self.timeout_seconds <= 0
        ):
            raise ValueError("artifact limits and timeout must be positive")

    def url_for(self, request: PublicationRequest) -> str:
        """Resolve only the configured release-bound path, rejecting caller-selected URLs."""
        expected_path = self.artifact_path_template.replace("{release_id}", request.release_id)
        if request.artifact_path != expected_path:
            raise ConsumerProtocolError(
                "artifact_path_rejected",
                "The artifact path is not the configured path for this release",
            )
        return f"{self.origin.rstrip('/')}{expected_path}"


def publication_headers(
    request: PublicationRequest, correlation: CorrelationContext
) -> dict[str, str]:
    """Build safe correlation and idempotency headers without creating identifiers."""
    headers = {
        "Accept": "application/gzip",
        "Accept-Encoding": "identity",
        REQUEST_ID_HEADER: correlation.request_id,
        IDEMPOTENCY_KEY_HEADER: request.idempotency_key,
    }
    if correlation.traceparent is not None:
        headers[TRACEPARENT_HEADER] = correlation.traceparent
    return headers


def consume_publication(
    request: PublicationRequest,
    *,
    target: str,
    consumer_operation_id: str,
    correlation: CorrelationContext,
    policy: ArtifactAccessPolicy,
    client: httpx.Client,
    sink: AtomicImportSink,
    record_validator: RecordValidator,
    manifest_validator: ManifestValidator | None = None,
) -> ImportReceipt:
    """Verify and stage a publication, committing only after all evidence matches."""
    if (
        not consumer_operation_id
        or len(consumer_operation_id) > 200
        or consumer_operation_id[0].isspace()
        or consumer_operation_id[-1].isspace()
        or any(ord(character) < 0x20 for character in consumer_operation_id)
    ):
        raise ValueError("consumer_operation_id must be a safe supplied identifier")
    _OPERATION_ID_ADAPTER.validate_python(consumer_operation_id)
    identity = immutable_identity(request, target=target)
    binding = request.manifest_binding
    if (
        binding.release_id != request.release_id
        or binding.dataset_id != request.dataset_id
        or binding.target != target
        or binding.schema_version != request.schema_version
        or binding.content_sha256 != request.content_sha256
        or binding.record_count != request.record_count
    ):
        raise ConsumerProtocolError(
            "publication_binding_mismatch",
            "The publication request and manifest evidence do not match this consumer",
        )
    if binding.byte_count > policy.max_compressed_bytes:
        raise ConsumerProtocolError(
            "artifact_too_large", "The declared compressed artifact exceeds its byte limit"
        )
    if request.record_count > policy.max_records:
        raise ConsumerProtocolError(
            "record_limit_exceeded", "The declared artifact has too many records"
        )
    if manifest_validator is not None:
        try:
            manifest_validator(deepcopy(request.manifest))
        except Exception as exc:
            raise ConsumerProtocolError(
                "manifest_extension_invalid", "The producer manifest extension is invalid"
            ) from exc
    url = policy.url_for(request)
    commit_started = False
    try:
        sink.begin(identity, consumer_operation_id=consumer_operation_id)
        evidence = _download_and_stage(
            request,
            identity=identity,
            expected_byte_count=binding.byte_count,
            url=url,
            correlation=correlation,
            policy=policy,
            client=client,
            sink=sink,
            record_validator=record_validator,
        )
        commit_started = True
        sink.commit(evidence)
    except Exception as exc:
        if commit_started:
            raise ConsumerProtocolError(
                "atomic_commit_outcome_unknown",
                "The atomic commit outcome is unknown; reconcile the immutable release identity "
                "and consumer operation ID before retrying",
                retryable=True,
                original_error=exc,
            ) from exc
        _rollback_after_failure(sink, exc)
        if isinstance(exc, ConsumerProtocolError):
            raise
        raise ConsumerProtocolError(
            "atomic_import_failed",
            "The consumer could not atomically import the release",
            original_error=exc,
        ) from exc
    return ImportReceipt(
        **identity.model_dump(),
        consumer_operation_id=consumer_operation_id,
        status="accepted",
        rows_received=evidence.rows_received,
        rows_accepted=evidence.rows_received,
        rows_rejected=0,
    )


def _download_and_stage(
    request: PublicationRequest,
    *,
    identity: ReleaseIdentity,
    expected_byte_count: int,
    url: str,
    correlation: CorrelationContext,
    policy: ArtifactAccessPolicy,
    client: httpx.Client,
    sink: AtomicImportSink,
    record_validator: RecordValidator,
) -> ImportEvidence:
    try:
        with client.stream(
            "GET",
            url,
            headers=publication_headers(request, correlation),
            follow_redirects=False,
            timeout=policy.timeout_seconds,
        ) as response:
            if 300 <= response.status_code < 400:
                raise ConsumerProtocolError(
                    "artifact_redirect_rejected", "Artifact redirects are not permitted"
                )
            if response.status_code != 200:
                raise ConsumerProtocolError(
                    "artifact_response_rejected",
                    "The producer did not return the requested artifact",
                    retryable=response.status_code >= 500,
                )
            declared_length = response.headers.get("Content-Length")
            if declared_length is not None:
                try:
                    length = int(declared_length)
                except ValueError as exc:
                    raise ConsumerProtocolError(
                        "artifact_length_invalid", "The artifact length header is invalid"
                    ) from exc
                if length < 0 or length > policy.max_compressed_bytes:
                    raise ConsumerProtocolError(
                        "artifact_too_large", "The compressed artifact exceeds its byte limit"
                    )
            compressed_chunks = response.iter_raw()
            return _decode_and_stage(
                compressed_chunks,
                request=request,
                identity=identity,
                expected_byte_count=expected_byte_count,
                policy=policy,
                sink=sink,
                record_validator=record_validator,
            )
    except ConsumerProtocolError:
        raise
    except httpx.HTTPError as exc:
        raise ConsumerProtocolError(
            "artifact_transport_failed", "The artifact could not be retrieved", retryable=True
        ) from exc


def _decode_and_stage(
    chunks: Iterator[bytes],
    *,
    request: PublicationRequest,
    identity: ReleaseIdentity,
    expected_byte_count: int,
    policy: ArtifactAccessPolicy,
    sink: AtomicImportSink,
    record_validator: RecordValidator,
) -> ImportEvidence:
    digest = hashlib.sha256()
    decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
    compressed_bytes = 0
    uncompressed_bytes = 0
    line_buffer = bytearray()
    rows_received = 0

    def consume_output(output: bytes) -> None:
        nonlocal uncompressed_bytes, rows_received
        uncompressed_bytes += len(output)
        if uncompressed_bytes > policy.max_uncompressed_bytes:
            raise ConsumerProtocolError(
                "artifact_expansion_limit_exceeded",
                "The expanded artifact exceeds its byte limit",
            )
        line_buffer.extend(output)
        if len(line_buffer) > policy.max_line_bytes and b"\n" not in line_buffer:
            raise ConsumerProtocolError("record_too_large", "An artifact record is too large")
        while True:
            newline = line_buffer.find(b"\n")
            if newline < 0:
                break
            line = bytes(line_buffer[:newline])
            del line_buffer[: newline + 1]
            rows_received = _stage_line(
                line,
                rows_received=rows_received,
                policy=policy,
                sink=sink,
                record_validator=record_validator,
            )
        if len(line_buffer) > policy.max_line_bytes:
            raise ConsumerProtocolError("record_too_large", "An artifact record is too large")

    try:
        for chunk in chunks:
            if not chunk:
                continue
            compressed_bytes += len(chunk)
            if compressed_bytes > policy.max_compressed_bytes:
                raise ConsumerProtocolError(
                    "artifact_too_large", "The compressed artifact exceeds its byte limit"
                )
            digest.update(chunk)
            pending = chunk
            while pending:
                remaining = policy.max_uncompressed_bytes - uncompressed_bytes
                output = decompressor.decompress(pending, remaining + 1)
                consume_output(output)
                pending = decompressor.unconsumed_tail
                if not pending:
                    break
        remaining = policy.max_uncompressed_bytes - uncompressed_bytes
        consume_output(decompressor.flush(remaining + 1))
    except zlib.error as exc:
        raise ConsumerProtocolError(
            "artifact_gzip_invalid", "The artifact is not a valid gzip stream"
        ) from exc
    if not decompressor.eof or decompressor.unused_data:
        raise ConsumerProtocolError(
            "artifact_gzip_invalid", "The artifact gzip stream is incomplete or has trailing data"
        )
    if line_buffer:
        rows_received = _stage_line(
            bytes(line_buffer),
            rows_received=rows_received,
            policy=policy,
            sink=sink,
            record_validator=record_validator,
        )
    if compressed_bytes != expected_byte_count:
        raise ConsumerProtocolError(
            "artifact_byte_count_mismatch", "The artifact byte count does not match its manifest"
        )
    if digest.hexdigest() != request.content_sha256:
        raise ConsumerProtocolError(
            "artifact_digest_mismatch", "The artifact digest does not match its release"
        )
    if rows_received != request.record_count:
        raise ConsumerProtocolError(
            "artifact_record_count_mismatch", "The artifact record count does not match its release"
        )
    return ImportEvidence(
        **identity.model_dump(),
        compressed_bytes=compressed_bytes,
        uncompressed_bytes=uncompressed_bytes,
        rows_received=rows_received,
    )


def _stage_line(
    line: bytes,
    *,
    rows_received: int,
    policy: ArtifactAccessPolicy,
    sink: AtomicImportSink,
    record_validator: RecordValidator,
) -> int:
    if not line.strip():
        raise ConsumerProtocolError("record_invalid", "The artifact contains a blank record")
    if len(line) > policy.max_line_bytes:
        raise ConsumerProtocolError("record_too_large", "An artifact record is too large")
    ordinal = rows_received + 1
    if ordinal > policy.max_records:
        raise ConsumerProtocolError("record_limit_exceeded", "The artifact has too many records")
    try:
        value = json.loads(
            line,
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=_reject_non_finite_number,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ConsumerProtocolError(
            "record_invalid", "An artifact record is not valid JSON"
        ) from exc
    if not isinstance(value, dict):
        raise ConsumerProtocolError("record_invalid", "Every artifact record must be a JSON object")
    try:
        record_validator(value, ordinal)
    except Exception as exc:
        raise ConsumerProtocolError(
            "record_schema_invalid", "An artifact record does not match its schema"
        ) from exc
    sink.stage(value, ordinal=ordinal)
    return ordinal


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_non_finite_number(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _rollback_after_failure(sink: AtomicImportSink, original_error: BaseException) -> None:
    """Clean known-uncommitted staging while retaining both failure causes."""
    try:
        sink.rollback()
    except Exception as cleanup_error:
        raise ConsumerProtocolError(
            "atomic_rollback_failed",
            "The import failed and the consumer could not clean up its staged state",
            original_error=original_error,
            cleanup_error=cleanup_error,
        ) from original_error
