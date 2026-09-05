"""Full-release delivery, bounded staging, crash recovery and accepted visibility."""

from __future__ import annotations

import gzip
import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from propertyscope_market_intelligence.app import create_app
from propertyscope_market_intelligence.clients import DependencyUnavailableError, StoreClient
from propertyscope_market_intelligence.import_worker import SalesImportWorker
from propertyscope_market_store.app import create_app as database_app
from propertyscope_market_store.configuration import StoreSettings
from propertyscope_market_store.import_operations import (
    ImportConflictError,
    ImportLeaseConflictError,
)
from propertyscope_market_store.repository import MarketStore

RELEASE = "70000000-0000-4000-8000-000000000099"
PROPERTY = "11111111-1111-4111-8111-111111111199"
PUBLIC = "/api/data-import/v1/propertyscope-releases"


def _record(index: int) -> dict[str, Any]:
    return {
        "source_business_key": f"psi:{index}",
        "source_revision": 1,
        "source_era": "modern",
        "property_ref": PROPERTY,
        "price_aud": 123456,
        "contract_date": "2025-01-01",
        "match_tier": "A",
        "match_confidence": "1.0000",
        "geographic_precision": "exact",
        "provenance": {
            "release_id": RELEASE,
            "release_version": "test-v1",
            "candidate_generation_id": RELEASE,
            "source_record_sha256": "b" * 64,
            "normalisation_version": "1.0.0",
        },
    }


def _publication(count: int, artifact: bytes) -> dict[str, Any]:
    digest = hashlib.sha256(artifact).hexdigest()
    return {
        "release_id": RELEASE,
        "dataset_id": "nsw-psi-sales",
        "schema_version": "propertyscope.property-sales.v3",
        "content_sha256": digest,
        "record_count": count,
        "idempotency_key": "full-sales-test",
        "artifact_path": f"/api/data-platform/v1/dataset-releases/{RELEASE}/artifact",
        "manifest": {
            "release_id": RELEASE,
            "dataset_id": "nsw-psi-sales",
            "target_feature": "feature-2",
            "product_schema_version": "propertyscope.property-sales.v3",
            "content_sha256": digest,
            "record_count": count,
            "content_encoding": "gzip",
            "byte_count": len(artifact),
        },
    }


class Source:
    def __init__(self, artifact: bytes) -> None:
        self.artifact = artifact
        self.downloads = 0

    def iter_artifact(self, _path: str) -> Iterator[bytes]:
        self.downloads += 1
        for start in range(0, len(self.artifact), 137):
            yield self.artifact[start : start + 137]


def _stack(tmp_path: Path, source: Source) -> tuple[Any, StoreClient, MarketStore]:
    store = MarketStore(tmp_path / "import.sqlite3")
    store.initialize()
    app = database_app(StoreSettings(tmp_path / "import.sqlite3", "test-token"), store=store)
    client = StoreClient(
        "http://database", "test-token", client=httpx.Client(transport=httpx.WSGITransport(app=app))
    )
    backend = create_app(store=client, feature1=source, ai_mode=object()).test_client()
    return backend, client, store


def test_large_import_recovers_committed_batch_without_exposing_partial_records(
    tmp_path: Path,
) -> None:
    count = 6001
    artifact = gzip.compress(
        b"".join(json.dumps(_record(i)).encode() + b"\n" for i in range(count))
    )
    source = Source(artifact)
    backend, client, store = _stack(tmp_path, source)
    payload = _publication(count, artifact)
    queued = backend.post(PUBLIC, json=payload)
    assert queued.status_code == 202
    operation_id = queued.json["consumer_operation_id"]
    assert source.downloads == 0  # Acknowledgement never performs data transfer.
    assert backend.post(PUBLIC, json=payload).json["consumer_operation_id"] == operation_id
    assert (
        backend.post(PUBLIC, json={**payload, "idempotency_key": "other-delivery"}).json[
            "consumer_operation_id"
        ]
        == operation_id
    )
    assert store.list_sales(PROPERTY) == []

    class LoseBatchReply:
        def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
            response = client.request(method, path, **kwargs)
            if path.endswith("/batches"):
                assert response.status_code == 200
                assert len(kwargs["json"]["records"]) <= 1000
                assert store.list_sales(PROPERTY) == []
                raise DependencyUnavailableError("committed batch response was lost")
            return response

    assert SalesImportWorker(LoseBatchReply(), source).run_once()
    interrupted = store.imports.get(operation_id)
    assert interrupted is not None and interrupted["status"] == "queued"
    assert interrupted["rows_staged"] == 1000
    with store._connect() as connection:
        connection.execute("UPDATE sales_import_operation SET next_attempt_at=0")
    assert SalesImportWorker(client, source).run_once()
    result = backend.get(f"{PUBLIC}/{operation_id}").json
    assert result["status"] == "accepted" and result["rows_accepted"] == count
    assert len(store.list_sales(PROPERTY, limit=10000)) == count
    assert backend.post(PUBLIC, json=payload).json["status"] == "accepted"
    assert not SalesImportWorker(client, source).run_once()
    assert source.downloads == 2
    with store._connect() as connection:
        assert (
            connection.execute("SELECT count(*) FROM sale_generation_record").fetchone()[0] == count
        )


@pytest.mark.parametrize("failure", ["checksum", "truncated", "count", "duplicate", "provenance"])
def test_invalid_artifact_never_changes_consumer_visibility(tmp_path: Path, failure: str) -> None:
    records = [_record(i) for i in range(1002)]
    if failure == "duplicate":
        records[-1] = records[0]
    if failure == "provenance":
        records[-1]["provenance"]["release_id"] = PROPERTY
    artifact = gzip.compress(b"".join(json.dumps(r).encode() + b"\n" for r in records))
    if failure == "truncated":
        artifact = artifact[:-8]
    payload = _publication(len(records) + int(failure == "count"), artifact)
    source = Source(artifact + b"changed" if failure == "checksum" else artifact)
    backend, client, store = _stack(tmp_path, source)
    operation_id = backend.post(PUBLIC, json=payload).json["consumer_operation_id"]
    assert SalesImportWorker(client, source).run_once()
    result = backend.get(f"{PUBLIC}/{operation_id}").json
    assert result["status"] == "failed"
    assert result["rows_accepted"] == 0
    assert store.list_sales(PROPERTY) == []
    with store._connect() as connection:
        assert (
            connection.execute("SELECT count(*) FROM sales_current_generation").fetchone()[0] == 0
        )


def test_reclaimed_worker_is_fenced_and_staging_replay_must_match(tmp_path: Path) -> None:
    _, _, store = _stack(tmp_path, Source(b""))
    operation = store.imports.create(_publication(1, b"valid-identity"))
    first = store.imports.claim()
    assert first is not None
    with store._connect() as connection:
        connection.execute("UPDATE sales_import_operation SET lease_until=0")
    second = store.imports.claim()
    assert second is not None and second["id"] == first["id"]
    assert second["lease_token"] != first["lease_token"]
    with pytest.raises(ImportLeaseConflictError):
        store.imports.finish(operation["id"], first["lease_token"], error=None)
    normalized = {"release_id": RELEASE, "source_business_key": "sale", "source_revision": 1}
    store.imports.stage(operation["id"], second["lease_token"], 1, [normalized])
    with pytest.raises(ImportConflictError, match="different evidence"):
        store.imports.stage(
            operation["id"], second["lease_token"], 1, [{**normalized, "price_aud": 1}]
        )
    store.imports.stage(operation["id"], second["lease_token"], 1, [normalized])
    store.imports.finish(operation["id"], second["lease_token"], error=None)


def test_source_scale_manifest_is_accepted_without_dataset_size_cap(tmp_path: Path) -> None:
    source = Source(b"fixture")
    backend, _, _ = _stack(tmp_path, source)
    payload = _publication(7_402_643, b"fixture")
    payload["manifest"]["byte_count"] = 952_728_964
    response = backend.post(PUBLIC, json=payload)
    assert response.status_code == 202
    assert response.json["record_count"] == 7_402_643
    assert source.downloads == 0
