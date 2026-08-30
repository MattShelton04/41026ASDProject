from __future__ import annotations

import base64
import gzip
import hashlib
import json
import sys
import uuid
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

ROOT = Path(__file__).parents[3]
sys.path.insert(0, str(ROOT / "poc" / "feature-6" / "backend" / "src"))

from propertyscope_integration_poc import (  # noqa: E402
    Feature1Client,
    Feature1HttpError,
    JsonSchemaRecordValidator,
    PublicationConflictError,
    PublicationImporter,
    PublicationImportError,
    PublicationReceipt,
    PublicationRequest,
    StoredPublication,
)

RELEASE_ID = uuid.UUID("60000000-0000-0000-0000-000000000002")
GENERATION_ID = str(RELEASE_ID)
SCHEMA_VERSION = "propertyscope.property-sales.v2"


class AtomicMemoryStore:
    def __init__(self) -> None:
        self.records: list[Mapping[str, Any]] = []
        self.publications: dict[tuple[str, str], StoredPublication] = {}
        self.import_calls = 0

    def find_publication(
        self, target_feature: str, idempotency_key: str
    ) -> StoredPublication | None:
        return self.publications.get((target_feature, idempotency_key))

    def import_release_atomic(
        self,
        publication: PublicationRequest,
        records: Iterable[Mapping[str, Any]],
    ) -> Mapping[str, Any]:
        self.import_calls += 1
        staged = list(records)
        receipt = PublicationReceipt(
            consumer_operation_id=publication.idempotency_key,
            status="accepted",
            schema_version=publication.schema_version,
            content_sha256=publication.content_sha256,
            rows_received=len(staged),
            rows_accepted=len(staged),
            rows_rejected=0,
        )
        self.records.extend(staged)
        self.publications[(publication.target_feature, publication.idempotency_key)] = (
            StoredPublication.from_request(publication, receipt)
        )
        return receipt.as_dict()


class CrossKeyReplayStore(AtomicMemoryStore):
    def import_release_atomic(
        self,
        publication: PublicationRequest,
        records: Iterable[Mapping[str, Any]],
    ) -> Mapping[str, Any]:
        for retained in self.publications.values():
            if retained.release_id == publication.release_id:
                return {**retained.receipt.as_dict(), "replayed": True}
        return super().import_release_atomic(publication, records)


def _schema_validator() -> JsonSchemaRecordValidator:
    schema = json.loads(
        (ROOT / "student-1" / "contracts" / "property-sales.v2.schema.json").read_text(
            encoding="utf-8"
        )
    )
    return JsonSchemaRecordValidator({SCHEMA_VERSION: schema})


def _envelope() -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(
            (
                ROOT / "student-1" / "contracts" / "fixtures" / "property-sales.v2.valid.json"
            ).read_text(encoding="utf-8")
        ),
    )


def _publication(
    artifact: bytes,
    *,
    media_type: str = "application/x-ndjson",
    content_encoding: str | None = "gzip",
    checksum: str | None = None,
    key: str = "feature-6-poc-import",
) -> dict[str, Any]:
    digest = checksum or hashlib.sha256(artifact).hexdigest()
    manifest = {
        "manifest_schema_version": "propertyscope.release-manifest.v1",
        "product_schema_version": SCHEMA_VERSION,
        "release_id": str(RELEASE_ID),
        "release_version": "fixture-sales-v2",
        "dataset_id": "nsw-psi-sales",
        "target_feature": "feature-2",
        "candidate_generation_id": GENERATION_ID,
        "normalisation_version": "1.0.0",
        "record_count": 1,
        "content_sha256": digest,
        "byte_count": len(artifact),
        "media_type": media_type,
        "content_encoding": content_encoding,
    }
    return {
        "release_id": str(RELEASE_ID),
        "dataset_id": "nsw-psi-sales",
        "schema_version": SCHEMA_VERSION,
        "content_sha256": digest,
        "record_count": 1,
        "manifest": manifest,
        "artifact_path": (f"/api/data-platform/v1/dataset-releases/{RELEASE_ID}/artifact"),
        "idempotency_key": key,
    }


def _digest_header(checksum: str) -> str:
    value = base64.b64encode(bytes.fromhex(checksum)).decode()
    return f"sha-256=:{value}:"


def _importer(
    artifact: bytes,
    publication: Mapping[str, Any],
    store: AtomicMemoryStore,
) -> PublicationImporter:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == publication["artifact_path"]
        return httpx.Response(
            200,
            stream=httpx.ByteStream(artifact),
            headers={"Digest": _digest_header(str(publication["content_sha256"]))},
        )

    client = Feature1Client(
        "http://feature-1.local",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    return PublicationImporter(client, store, _schema_validator())


def test_streamed_gzip_ndjson_import_is_atomic_and_replay_safe() -> None:
    record = _envelope()["records"][0]
    artifact = gzip.compress(
        json.dumps(record, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )
    publication = _publication(artifact)
    store = AtomicMemoryStore()
    importer = _importer(artifact, publication, store)

    first = importer.import_callback(publication, header_idempotency_key="feature-6-poc-import")
    replay = importer.import_callback(publication, header_idempotency_key="feature-6-poc-import")

    assert first == replay
    assert first.status == "accepted"
    assert first.rows_accepted == 1
    assert store.records == [record]
    assert store.import_calls == 1


def test_legacy_json_envelope_remains_consumable_by_manifest_declaration() -> None:
    envelope = _envelope()
    artifact = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
    publication = _publication(artifact, media_type="application/json", content_encoding=None)
    store = AtomicMemoryStore()

    receipt = _importer(artifact, publication, store).import_callback(
        publication, header_idempotency_key="feature-6-poc-import"
    )

    assert receipt.status == "accepted"
    assert store.records == envelope["records"]


def test_corrupt_stream_rolls_back_staged_records() -> None:
    record = _envelope()["records"][0]
    artifact = gzip.compress(json.dumps(record).encode() + b"\n")
    publication = _publication(artifact, checksum="0" * 64)
    store = AtomicMemoryStore()

    with pytest.raises(PublicationImportError, match="checksum"):
        _importer(artifact, publication, store).import_callback(
            publication, header_idempotency_key="feature-6-poc-import"
        )

    assert store.records == []
    assert store.publications == {}


def test_record_provenance_must_bind_to_release() -> None:
    record = _envelope()["records"][0]
    record["provenance"]["release_id"] = str(uuid.uuid4())
    artifact = gzip.compress(json.dumps(record).encode() + b"\n")
    publication = _publication(artifact)
    store = AtomicMemoryStore()

    with pytest.raises(PublicationImportError, match="provenance release_id"):
        _importer(artifact, publication, store).import_callback(
            publication, header_idempotency_key="feature-6-poc-import"
        )

    assert store.records == []


def test_same_idempotency_key_cannot_change_release_evidence() -> None:
    record = _envelope()["records"][0]
    artifact = gzip.compress(json.dumps(record).encode() + b"\n")
    publication = _publication(artifact)
    store = AtomicMemoryStore()
    importer = _importer(artifact, publication, store)
    importer.import_callback(publication, header_idempotency_key="feature-6-poc-import")
    changed = dict(publication)
    changed["record_count"] = 0
    changed_manifest = dict(changed["manifest"])
    changed_manifest["record_count"] = 0
    changed["manifest"] = changed_manifest

    with pytest.raises(PublicationConflictError):
        importer.import_callback(changed, header_idempotency_key="feature-6-poc-import")


def test_artifact_redirect_is_rejected_without_following_location() -> None:
    record = _envelope()["records"][0]
    artifact = gzip.compress(json.dumps(record).encode() + b"\n")
    publication = _publication(artifact)
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(302, headers={"Location": "https://attacker.invalid/file"})

    client = Feature1Client(
        "http://feature-1.local",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    importer = PublicationImporter(client, AtomicMemoryStore(), _schema_validator())

    with pytest.raises(Feature1HttpError, match="redirects are forbidden"):
        importer.import_callback(publication, header_idempotency_key="feature-6-poc-import")
    assert calls == 1


def test_accepted_reconciliation_pulls_once_and_handles_no_release() -> None:
    record = _envelope()["records"][0]
    artifact = gzip.compress(json.dumps(record).encode() + b"\n")
    publication = _publication(artifact)
    manifest = publication["manifest"]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/data-products/missing/accepted"):
            return httpx.Response(404, json={"detail": "No accepted release"})
        if request.url.path.endswith("/data-products/nsw-psi-sales/accepted"):
            return httpx.Response(
                200,
                json={
                    "release": {
                        "id": str(RELEASE_ID),
                        "dataset_id": "nsw-psi-sales",
                        "target_feature": "feature-2",
                        "release_version": "fixture-sales-v2",
                        "schema_version": SCHEMA_VERSION,
                        "status": "accepted",
                        "content_sha256": publication["content_sha256"],
                        "record_count": 1,
                        "manifest_json": manifest,
                    }
                },
            )
        return httpx.Response(
            200,
            stream=httpx.ByteStream(artifact),
            headers={"Digest": _digest_header(str(publication["content_sha256"]))},
        )

    feature1 = Feature1Client(
        "http://feature-1.local",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    store = AtomicMemoryStore()
    importer = PublicationImporter(feature1, store, _schema_validator())

    assert importer.reconcile_accepted("missing", "feature-2") is None
    first = importer.reconcile_accepted("nsw-psi-sales", "feature-2")
    replay = importer.reconcile_accepted("nsw-psi-sales", "feature-2")

    assert first == replay
    assert first is not None and first.status == "accepted"
    assert store.import_calls == 1


def test_accepted_reconciliation_reuses_callback_receipt_across_operation_keys() -> None:
    record = _envelope()["records"][0]
    artifact = gzip.compress(json.dumps(record).encode() + b"\n")
    callback = _publication(artifact, key="callback-publication-key")
    manifest = callback["manifest"]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/data-products/nsw-psi-sales/accepted"):
            return httpx.Response(
                200,
                json={
                    "release": {
                        "id": str(RELEASE_ID),
                        "dataset_id": "nsw-psi-sales",
                        "target_feature": "feature-2",
                        "release_version": "fixture-sales-v2",
                        "schema_version": SCHEMA_VERSION,
                        "status": "accepted",
                        "content_sha256": callback["content_sha256"],
                        "record_count": 1,
                        "manifest_json": manifest,
                    }
                },
            )
        return httpx.Response(
            200,
            stream=httpx.ByteStream(artifact),
            headers={"Digest": _digest_header(str(callback["content_sha256"]))},
        )

    feature1 = Feature1Client(
        "http://feature-1.local",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    store = CrossKeyReplayStore()
    importer = PublicationImporter(feature1, store, _schema_validator())

    callback_receipt = importer.import_callback(
        callback, header_idempotency_key="callback-publication-key"
    )
    reconciled_receipt = importer.reconcile_accepted("nsw-psi-sales", "feature-2")

    assert reconciled_receipt == callback_receipt
    assert reconciled_receipt is not None
    assert reconciled_receipt.consumer_operation_id == "callback-publication-key"
    assert store.import_calls == 1


@pytest.mark.parametrize(
    "origin",
    [
        "file:///tmp/provider",
        "https://user:secret@provider.invalid",
        "https://provider.invalid/api",
        "https://provider.invalid?next=evil",
    ],
)
def test_feature1_origin_must_be_a_plain_http_origin(origin: str) -> None:
    with pytest.raises(ValueError, match="HTTP origin"):
        Feature1Client(origin)


def test_transport_failure_is_projected_as_dependency_unavailability() -> None:
    def unavailable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    client = Feature1Client(
        "http://feature-1.local",
        client=httpx.Client(transport=httpx.MockTransport(unavailable)),
    )

    with pytest.raises(Feature1HttpError, match="unavailable") as raised:
        client.catalogue()
    assert raised.value.status_code == 503
