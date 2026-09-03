from __future__ import annotations

import gzip
import hashlib
import json
from collections.abc import Mapping
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

import shared_consumer_protocol.consumer as consumer_module
from shared_consumer_protocol import (
    ArtifactAccessPolicy,
    ConsumerProtocolError,
    CorrelationContext,
    ImportEvidence,
    ImportReceipt,
    PublicationRequest,
    ReceiptError,
    ReleaseIdentity,
    consume_publication,
)

from .http_fixture import FixtureResponse, serve

RELEASE_ID = "3cc53c76-559d-4e5a-b8df-540f1ad15bd4"
TARGET = "consumer-a"
PATH = f"/v1/releases/{RELEASE_ID}/artifact"


class RecordingSink:
    def __init__(self) -> None:
        self.begin_calls = 0
        self.identity: ReleaseIdentity | None = None
        self.operation_id: str | None = None
        self.staged: list[tuple[int, Mapping[str, Any]]] = []
        self.evidence: ImportEvidence | None = None
        self.committed = False
        self.rolled_back = False

    def begin(self, identity: ReleaseIdentity, *, consumer_operation_id: str) -> None:
        self.begin_calls += 1
        self.identity = identity
        self.operation_id = consumer_operation_id

    def stage(self, record: Mapping[str, Any], *, ordinal: int) -> None:
        self.staged.append((ordinal, record))

    def commit(self, evidence: ImportEvidence) -> None:
        self.evidence = evidence
        self.committed = True

    def rollback(self) -> None:
        self.staged.clear()
        self.rolled_back = True


def artifact(records: list[dict[str, Any]]) -> bytes:
    payload = b"".join(
        json.dumps(record, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        for record in records
    )
    return gzip.compress(payload, mtime=0)


def compressed_payload(payload: bytes, *, compresslevel: int = 9) -> bytes:
    return gzip.compress(payload, compresslevel=compresslevel, mtime=0)


def publication(body: bytes, **changes: Any) -> PublicationRequest:
    checksum = changes.pop("content_sha256", hashlib.sha256(body).hexdigest())
    count = changes.pop("record_count", 2)
    manifest: dict[str, Any] = {
        "manifest_schema_version": "release-manifest.v1",
        "release_id": RELEASE_ID,
        "dataset_id": "dataset-a",
        "target": TARGET,
        "schema_version": "records.v1",
        "content_sha256": checksum,
        "record_count": count,
        "byte_count": len(body),
        "media_type": "application/x-ndjson",
        "content_encoding": "gzip",
        "producer_extension": {"retained": True},
    }
    manifest.update(changes.pop("manifest", {}))
    return PublicationRequest(
        release_id=RELEASE_ID,
        dataset_id="dataset-a",
        schema_version="records.v1",
        content_sha256=checksum,
        record_count=count,
        manifest=manifest,
        artifact_path=changes.pop("artifact_path", PATH),
        idempotency_key=changes.pop("idempotency_key", "delivery-attempt-1"),
        **changes,
    )


def policy(origin: str, **changes: Any) -> ArtifactAccessPolicy:
    values: dict[str, Any] = {
        "origin": origin,
        "artifact_path_template": "/v1/releases/{release_id}/artifact",
        "max_compressed_bytes": 10_000,
        "max_uncompressed_bytes": 10_000,
        "max_records": 10,
        "max_line_bytes": 1_000,
        "timeout_seconds": 2,
    }
    values.update(changes)
    return ArtifactAccessPolicy(**values)


def validate_sequence(record: Mapping[str, Any], ordinal: int) -> None:
    if record.get("sequence") != ordinal:
        raise ValueError("sequence must match source order")


def consume(
    request: PublicationRequest,
    origin: str,
    sink: RecordingSink,
    **changes: Any,
) -> ImportReceipt:
    with httpx.Client() as client:
        return consume_publication(
            request,
            target=changes.pop("target", TARGET),
            consumer_operation_id=changes.pop("consumer_operation_id", "consumer-operation-7"),
            correlation=changes.pop("correlation", CorrelationContext(request_id="request-19")),
            policy=changes.pop("access_policy", policy(origin)),
            client=client,
            sink=sink,
            record_validator=changes.pop("record_validator", validate_sequence),
            **changes,
        )


def test_real_http_import_verifies_then_atomically_commits() -> None:
    body = artifact([{"sequence": 1}, {"sequence": 2}])
    sink = RecordingSink()
    with serve({PATH: FixtureResponse(200, body)}) as (origin, state):
        receipt = consume(publication(body), origin, sink)

    assert sink.committed is True
    assert sink.rolled_back is False
    assert sink.staged == [(1, {"sequence": 1}), (2, {"sequence": 2})]
    assert sink.evidence is not None
    assert sink.evidence.compressed_bytes == len(body)
    assert sink.evidence.rows_received == 2
    assert receipt.consumer_operation_id == "consumer-operation-7"
    assert receipt.matches(publication(body), target=TARGET)
    assert state.requests[0][0] == PATH
    assert state.requests[0][1]["X-Request-ID"] == "request-19"
    assert state.requests[0][1]["Idempotency-Key"] == "delivery-attempt-1"
    assert state.requests[0][1]["Accept-Encoding"] == "identity"


def test_large_expansion_ceiling_does_not_become_a_zlib_allocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = artifact([{"sequence": 1}, {"sequence": 2}])
    sink = RecordingSink()
    allocation_requests: list[int] = []
    real_decompressobj = consumer_module.zlib.decompressobj

    class ObservedDecompressor:
        def __init__(self, wbits: int = consumer_module.zlib.MAX_WBITS) -> None:
            self.inner = real_decompressobj(wbits)

        @property
        def unconsumed_tail(self) -> bytes:
            return self.inner.unconsumed_tail

        @property
        def eof(self) -> bool:
            return self.inner.eof

        @property
        def unused_data(self) -> bytes:
            return self.inner.unused_data

        def decompress(self, data: bytes, max_length: int = 0) -> bytes:
            allocation_requests.append(max_length)
            return self.inner.decompress(data, max_length)

        def flush(self, length: int) -> bytes:
            allocation_requests.append(length)
            return self.inner.flush(length)

    monkeypatch.setattr(consumer_module.zlib, "decompressobj", ObservedDecompressor)
    with serve({PATH: FixtureResponse(200, body)}) as (origin, _):
        consume(
            publication(body),
            origin,
            sink,
            access_policy=policy(origin, max_uncompressed_bytes=12_000_000_000),
        )

    assert sink.committed is True
    assert allocation_requests
    assert max(allocation_requests) <= 65_536


@pytest.mark.parametrize(
    ("manifest"),
    [
        {"target_feature": "different-target"},
        {"product_schema_version": "records.v2"},
    ],
)
def test_conflicting_recognized_manifest_aliases_are_rejected(
    manifest: dict[str, str],
) -> None:
    body = artifact([{"sequence": 1}, {"sequence": 2}])

    with pytest.raises(ValidationError, match="conflicts"):
        publication(body, manifest=manifest)


def test_equal_recognized_manifest_aliases_remain_compatible() -> None:
    body = artifact([{"sequence": 1}, {"sequence": 2}])

    request = publication(
        body,
        manifest={
            "target_feature": TARGET,
            "product_schema_version": "records.v1",
        },
    )

    assert request.manifest_binding.target == TARGET
    assert request.manifest_binding.schema_version == "records.v1"


def test_trace_context_is_forwarded_without_generating_values() -> None:
    body = artifact([{"sequence": 1}, {"sequence": 2}])
    sink = RecordingSink()
    traceparent = "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01"
    with serve({PATH: FixtureResponse(200, body)}) as (origin, state):
        consume(
            publication(body),
            origin,
            sink,
            correlation=CorrelationContext(request_id="request-20", traceparent=traceparent),
        )
    assert state.requests[0][1]["traceparent"] == traceparent


def test_redirect_is_rejected_and_staged_import_is_rolled_back() -> None:
    body = artifact([{"sequence": 1}, {"sequence": 2}])
    sink = RecordingSink()
    with (
        serve({PATH: FixtureResponse(302, headers={"Location": "/untrusted"})}) as (
            origin,
            state,
        ),
        pytest.raises(ConsumerProtocolError, match="redirects") as caught,
    ):
        consume(publication(body), origin, sink)

    assert caught.value.code == "artifact_redirect_rejected"
    assert sink.rolled_back is True
    assert sink.committed is False
    assert len(state.requests) == 1


@pytest.mark.parametrize(
    ("request_factory", "policy_changes", "expected_code", "begins_import"),
    [
        (
            lambda body: publication(body, content_sha256="0" * 64),
            {},
            "artifact_digest_mismatch",
            True,
        ),
        (
            lambda body: publication(body),
            {"max_compressed_bytes": 10},
            "artifact_too_large",
            False,
        ),
        (
            lambda body: publication(body, record_count=3, manifest={"record_count": 3}),
            {},
            "artifact_record_count_mismatch",
            True,
        ),
    ],
)
def test_failed_evidence_never_commits(
    request_factory: Any,
    policy_changes: dict[str, Any],
    expected_code: str,
    begins_import: bool,
) -> None:
    body = artifact([{"sequence": 1}, {"sequence": 2}])
    sink = RecordingSink()
    with (
        serve({PATH: FixtureResponse(200, body)}) as (origin, _),
        pytest.raises(ConsumerProtocolError) as caught,
    ):
        consume(
            request_factory(body),
            origin,
            sink,
            access_policy=policy(origin, **policy_changes),
        )

    assert caught.value.code == expected_code
    assert sink.committed is False
    assert sink.staged == []
    assert (sink.identity is not None) is begins_import
    assert sink.rolled_back is begins_import


def test_record_schema_hook_failure_rolls_back() -> None:
    body = artifact([{"sequence": 1}, {"unexpected": True}])
    sink = RecordingSink()
    with (
        serve({PATH: FixtureResponse(200, body)}) as (origin, _),
        pytest.raises(ConsumerProtocolError) as caught,
    ):
        consume(publication(body), origin, sink)

    assert caught.value.code == "record_schema_invalid"
    assert sink.rolled_back is True
    assert sink.staged == []


def test_fixed_path_is_checked_before_import_or_http_access() -> None:
    body = artifact([{"sequence": 1}, {"sequence": 2}])
    sink = RecordingSink()
    with (
        serve({PATH: FixtureResponse(200, body)}) as (origin, state),
        pytest.raises(ConsumerProtocolError) as caught,
    ):
        consume(publication(body, artifact_path="/v1/releases/other/artifact"), origin, sink)

    assert caught.value.code == "artifact_path_rejected"
    assert sink.identity is None
    assert state.requests == []


def test_manifest_binding_and_extension_are_validated_before_import() -> None:
    body = artifact([{"sequence": 1}, {"sequence": 2}])
    with pytest.raises(ValidationError, match="immutable evidence"):
        publication(body, manifest={"dataset_id": "different"})

    sink = RecordingSink()
    with (
        serve({PATH: FixtureResponse(200, body)}) as (origin, state),
        pytest.raises(ConsumerProtocolError) as caught,
    ):
        consume(
            publication(body),
            origin,
            sink,
            manifest_validator=lambda manifest: (_ for _ in ()).throw(ValueError()),
        )
    assert caught.value.code == "manifest_extension_invalid"
    assert sink.identity is None
    assert state.requests == []


def test_manifest_is_revalidated_if_callback_data_is_mutated_after_parsing() -> None:
    body = artifact([{"sequence": 1}, {"sequence": 2}])
    request = publication(body)
    request.manifest["content_sha256"] = "f" * 64
    sink = RecordingSink()
    with (
        serve({PATH: FixtureResponse(200, body)}) as (origin, state),
        pytest.raises(ConsumerProtocolError) as caught,
    ):
        consume(request, origin, sink)

    assert caught.value.code == "publication_binding_mismatch"
    assert sink.identity is None
    assert state.requests == []


def test_manifest_hook_cannot_mutate_verified_transport_evidence() -> None:
    body = artifact([{"sequence": 1}, {"sequence": 2}])
    request = publication(body)
    sink = RecordingSink()

    def mutate_hook(manifest: Mapping[str, Any]) -> None:
        assert isinstance(manifest, dict)
        manifest["byte_count"] = 1

    with serve({PATH: FixtureResponse(200, body)}) as (origin, _):
        receipt = consume(request, origin, sink, manifest_validator=mutate_hook)

    assert receipt.status == "accepted"
    assert request.manifest["byte_count"] == len(body)


def test_gzip_expansion_limit_rolls_back_staged_state() -> None:
    body = artifact(
        [
            {"sequence": 1, "payload": "x" * 500},
            {"sequence": 2, "payload": "x" * 500},
        ]
    )
    sink = RecordingSink()
    with (
        serve({PATH: FixtureResponse(200, body)}) as (origin, _),
        pytest.raises(ConsumerProtocolError) as caught,
    ):
        consume(
            publication(body),
            origin,
            sink,
            access_policy=policy(origin, max_uncompressed_bytes=100),
        )

    assert caught.value.code == "artifact_expansion_limit_exceeded"
    assert sink.rolled_back is True
    assert sink.committed is False


@pytest.mark.parametrize(
    "changes",
    [
        {"origin": "ftp://producer.test"},
        {"origin": "http://user:secret@producer.test"},
        {"origin": "http://producer.test/base"},
        {"origin": "http://producer.test?query=yes"},
        {"artifact_path_template": "relative/{release_id}"},
        {"artifact_path_template": "/v1/{release_id}/../artifact"},
        {"max_records": 0},
    ],
)
def test_access_policy_rejects_unsafe_configuration(changes: dict[str, Any]) -> None:
    values: dict[str, Any] = {
        "origin": "https://producer.test",
        "artifact_path_template": "/v1/releases/{release_id}/artifact",
        "max_compressed_bytes": 100,
        "max_uncompressed_bytes": 100,
        "max_records": 1,
    }
    values.update(changes)
    with pytest.raises(ValueError):
        ArtifactAccessPolicy(**values)


def test_declared_record_limit_is_rejected_before_staging_or_http() -> None:
    body = artifact([{"sequence": 1}, {"sequence": 2}])
    sink = RecordingSink()
    with (
        serve({PATH: FixtureResponse(200, body)}) as (origin, state),
        pytest.raises(ConsumerProtocolError) as caught,
    ):
        consume(publication(body), origin, sink, access_policy=policy(origin, max_records=1))
    assert caught.value.code == "record_limit_exceeded"
    assert sink.identity is None
    assert state.requests == []


@pytest.mark.parametrize(
    ("response", "expected_code", "retryable"),
    [
        (FixtureResponse(503), "artifact_response_rejected", True),
        (
            FixtureResponse(200, b"ignored", headers={"Content-Length": "invalid"}),
            "artifact_transport_failed",
            True,
        ),
        (
            FixtureResponse(200, b"ignored", headers={"Content-Length": "-1"}),
            "artifact_transport_failed",
            True,
        ),
    ],
)
def test_http_response_failures_are_safe_and_rollback(
    response: FixtureResponse, expected_code: str, retryable: bool
) -> None:
    body = artifact([{"sequence": 1}, {"sequence": 2}])
    sink = RecordingSink()
    with (
        serve({PATH: response}) as (origin, _),
        pytest.raises(ConsumerProtocolError) as caught,
    ):
        consume(publication(body), origin, sink)
    assert caught.value.code == expected_code
    assert caught.value.retryable is retryable
    assert sink.rolled_back is True


@pytest.mark.parametrize(
    ("payload", "expected_code"),
    [
        (b"{}\n\n", "record_invalid"),
        (b"{bad}\n", "record_invalid"),
        (b"[]\n", "record_invalid"),
        (b'{"a":1,"a":2}\n', "record_invalid"),
        (b'{"a":NaN}\n', "record_invalid"),
    ],
)
def test_invalid_ndjson_framing_rolls_back(payload: bytes, expected_code: str) -> None:
    body = compressed_payload(payload)
    count = 2 if payload == b"{}\n\n" else 1
    sink = RecordingSink()
    with (
        serve({PATH: FixtureResponse(200, body)}) as (origin, _),
        pytest.raises(ConsumerProtocolError) as caught,
    ):
        consume(
            publication(body, record_count=count, manifest={"record_count": count}),
            origin,
            sink,
            record_validator=lambda record, ordinal: None,
        )
    assert caught.value.code == expected_code
    assert sink.rolled_back is True


@pytest.mark.parametrize(
    ("served_body", "expected_code"),
    [
        (b"not-gzip", "artifact_gzip_invalid"),
        (compressed_payload(b'{"sequence":1}\n')[:-2], "artifact_gzip_invalid"),
        (compressed_payload(b'{"sequence":1}\n') + b"trailing", "artifact_gzip_invalid"),
    ],
)
def test_invalid_gzip_rolls_back(served_body: bytes, expected_code: str) -> None:
    sink = RecordingSink()
    request = publication(served_body, record_count=1, manifest={"record_count": 1})
    with (
        serve({PATH: FixtureResponse(200, served_body)}) as (origin, _),
        pytest.raises(ConsumerProtocolError) as caught,
    ):
        consume(request, origin, sink)
    assert caught.value.code == expected_code
    assert sink.rolled_back is True


def test_final_record_without_newline_is_imported() -> None:
    body = compressed_payload(b'{"sequence":1}')
    sink = RecordingSink()
    with serve({PATH: FixtureResponse(200, body)}) as (origin, _):
        receipt = consume(
            publication(body, record_count=1, manifest={"record_count": 1}), origin, sink
        )
    assert receipt.rows_accepted == 1


def test_runtime_record_and_byte_limits_defend_against_false_declarations() -> None:
    declared = compressed_payload(b'{"sequence":1}\n')
    served = compressed_payload(b'{"sequence":1}\n{"sequence":2}\n')
    request = publication(declared, record_count=1, manifest={"record_count": 1})

    record_sink = RecordingSink()
    with (
        serve({PATH: FixtureResponse(200, served)}) as (origin, _),
        pytest.raises(ConsumerProtocolError) as record_error,
    ):
        consume(
            request,
            origin,
            record_sink,
            access_policy=policy(origin, max_compressed_bytes=len(served) + 1, max_records=1),
        )
    assert record_error.value.code == "record_limit_exceeded"

    byte_sink = RecordingSink()
    with (
        serve({PATH: FixtureResponse(200, served, include_content_length=False)}) as (origin, _),
        pytest.raises(ConsumerProtocolError) as byte_error,
    ):
        consume(
            request,
            origin,
            byte_sink,
            access_policy=policy(origin, max_compressed_bytes=len(declared)),
        )
    assert byte_error.value.code == "artifact_too_large"


def test_manifest_byte_count_mismatch_precedes_digest_check() -> None:
    payload = b'{"sequence":1,"payload":"' + b"x" * 500 + b'"}\n'
    served = compressed_payload(payload)
    sink = RecordingSink()
    with (
        serve({PATH: FixtureResponse(200, served)}) as (origin, _),
        pytest.raises(ConsumerProtocolError) as caught,
    ):
        consume(
            publication(
                served,
                record_count=1,
                manifest={"record_count": 1, "byte_count": len(served) - 1},
            ),
            origin,
            sink,
            record_validator=lambda record, ordinal: None,
        )
    assert caught.value.code == "artifact_byte_count_mismatch"


def test_sink_and_cleanup_failures_are_reported_without_committing() -> None:
    body = artifact([{"sequence": 1}, {"sequence": 2}])

    class FailingBeginSink(RecordingSink):
        def begin(self, identity: ReleaseIdentity, *, consumer_operation_id: str) -> None:
            super().begin(identity, consumer_operation_id=consumer_operation_id)
            raise RuntimeError("begin failed")

    begin_sink = FailingBeginSink()
    with (
        serve({PATH: FixtureResponse(200, body)}) as (origin, _),
        pytest.raises(ConsumerProtocolError) as begin_error,
    ):
        consume(publication(body), origin, begin_sink)
    assert begin_error.value.code == "atomic_import_failed"
    assert isinstance(begin_error.value.original_error, RuntimeError)
    assert begin_sink.rolled_back is True

    class FailingRollbackSink(FailingBeginSink):
        def rollback(self) -> None:
            raise RuntimeError("rollback failed")

    rollback_sink = FailingRollbackSink()
    with (
        serve({PATH: FixtureResponse(200, body)}) as (origin, _),
        pytest.raises(ConsumerProtocolError) as rollback_error,
    ):
        consume(publication(body), origin, rollback_sink)
    assert rollback_error.value.code == "atomic_rollback_failed"
    assert isinstance(rollback_error.value.original_error, RuntimeError)
    assert isinstance(rollback_error.value.cleanup_error, RuntimeError)
    assert rollback_error.value.__cause__ is rollback_error.value.original_error


def test_staging_failure_before_commit_rolls_back_known_uncommitted_state() -> None:
    body = artifact([{"sequence": 1}, {"sequence": 2}])

    class FailingStageSink(RecordingSink):
        def stage(self, record: Mapping[str, Any], *, ordinal: int) -> None:
            super().stage(record, ordinal=ordinal)
            raise RuntimeError("staging failed")

    sink = FailingStageSink()
    with (
        serve({PATH: FixtureResponse(200, body)}) as (origin, _),
        pytest.raises(ConsumerProtocolError) as caught,
    ):
        consume(publication(body), origin, sink)

    assert caught.value.code == "atomic_import_failed"
    assert isinstance(caught.value.original_error, RuntimeError)
    assert sink.rolled_back is True
    assert sink.staged == []
    assert sink.committed is False


def test_commit_failure_before_durable_effect_is_still_an_unknown_outcome() -> None:
    body = artifact([{"sequence": 1}, {"sequence": 2}])

    class FailingCommitSink(RecordingSink):
        def commit(self, evidence: ImportEvidence) -> None:
            del evidence
            raise RuntimeError("commit failed before writing")

    sink = FailingCommitSink()
    with (
        serve({PATH: FixtureResponse(200, body)}) as (origin, _),
        pytest.raises(ConsumerProtocolError) as caught,
    ):
        consume(publication(body), origin, sink)

    assert caught.value.code == "atomic_commit_outcome_unknown"
    assert caught.value.retryable is True
    assert isinstance(caught.value.original_error, RuntimeError)
    assert caught.value.__cause__ is caught.value.original_error
    assert sink.rolled_back is False
    assert sink.committed is False
    assert len(sink.staged) == 2


def test_durable_commit_then_exception_never_rolls_back_and_reconciles_idempotently() -> None:
    body = artifact([{"sequence": 1}, {"sequence": 2}])
    request = publication(body)
    operation_id = "consumer-operation-uncertain-9"

    class DurableThenRaiseSink(RecordingSink):
        def commit(self, evidence: ImportEvidence) -> None:
            super().commit(evidence)
            raise RuntimeError("connection lost after durable commit")

    sink = DurableThenRaiseSink()
    with (
        serve({PATH: FixtureResponse(200, body)}) as (origin, _),
        pytest.raises(ConsumerProtocolError) as caught,
    ):
        consume(request, origin, sink, consumer_operation_id=operation_id)

    assert caught.value.code == "atomic_commit_outcome_unknown"
    assert caught.value.retryable is True
    assert isinstance(caught.value.original_error, RuntimeError)
    assert sink.committed is True
    assert sink.rolled_back is False
    assert sink.evidence is not None
    assert sink.identity is not None
    persisted_receipt = ImportReceipt(
        **sink.identity.model_dump(),
        consumer_operation_id=operation_id,
        status="accepted",
        rows_received=sink.evidence.rows_received,
        rows_accepted=sink.evidence.rows_received,
        rows_rejected=0,
    )

    def reconcile_before_import(existing: ImportReceipt | None) -> ImportReceipt | None:
        if existing is not None and existing.reconciles(
            publication(body, idempotency_key="replayed-delivery"),
            target=TARGET,
            consumer_operation_id=operation_id,
        ):
            return existing
        raise AssertionError("reconciliation should prevent a second download/import")

    assert reconcile_before_import(persisted_receipt) is persisted_receipt
    assert sink.begin_calls == 1
    assert (
        persisted_receipt.reconciles(
            request, target=TARGET, consumer_operation_id="different-operation"
        )
        is False
    )


def test_closed_models_reject_incoherent_count_evidence() -> None:
    body = artifact([{"sequence": 1}, {"sequence": 2}])
    request = publication(body)
    identity = {
        "release_id": request.release_id,
        "dataset_id": request.dataset_id,
        "target": TARGET,
        "schema_version": request.schema_version,
        "content_sha256": request.content_sha256,
        "record_count": 2,
    }
    with pytest.raises(ValidationError, match="verified row count"):
        ImportEvidence(
            **identity, compressed_bytes=len(body), uncompressed_bytes=10, rows_received=1
        )
    with pytest.raises(ValidationError, match="cannot exceed"):
        ImportReceipt(
            **identity,
            consumer_operation_id="operation-1",
            status="failed",
            rows_received=1,
            rows_accepted=1,
            rows_rejected=1,
            error=ReceiptError(code="failed", message="Failed"),
        )
    with pytest.raises(ValidationError, match="complete bound release"):
        ImportReceipt(
            **identity,
            consumer_operation_id="operation-1",
            status="accepted",
            rows_received=1,
            rows_accepted=1,
            rows_rejected=0,
        )
    with pytest.raises(ValidationError, match="requires a safe error"):
        ImportReceipt(
            **identity,
            consumer_operation_id="operation-1",
            status="failed",
            rows_received=0,
            rows_accepted=0,
            rows_rejected=0,
        )


def test_receipts_are_closed_and_mismatched_evidence_is_not_replayable() -> None:
    body = artifact([{"sequence": 1}, {"sequence": 2}])
    sink = RecordingSink()
    request = publication(body)
    with serve({PATH: FixtureResponse(200, body)}) as (origin, _):
        receipt = consume(request, origin, sink)

    with pytest.raises(ValidationError, match="Extra inputs"):
        ImportReceipt.model_validate({**receipt.model_dump(), "invented": "evidence"})
    assert not receipt.matches(
        publication(body, idempotency_key="another-delivery"), target="different-consumer"
    )
    request.manifest["record_count"] = 3
    assert receipt.matches(request, target=TARGET) is False


def test_nonaccepted_receipt_requires_a_real_operation_id_and_safe_error() -> None:
    body = artifact([{"sequence": 1}, {"sequence": 2}])
    request = publication(body)
    receipt = ImportReceipt(
        release_id=request.release_id,
        dataset_id=request.dataset_id,
        target=TARGET,
        schema_version=request.schema_version,
        content_sha256=request.content_sha256,
        record_count=request.record_count,
        consumer_operation_id="persisted-operation-8",
        status="failed",
        rows_received=0,
        rows_accepted=0,
        rows_rejected=0,
        error=ReceiptError(code="transport_failed", message="Artifact retrieval failed"),
    )
    assert receipt.consumer_operation_id == "persisted-operation-8"
    assert receipt.matches(request, target=TARGET) is False
