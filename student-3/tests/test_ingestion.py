"""Offline consumer tests: real database HTTP, streaming producer and durable recovery."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from threading import Thread
from typing import Any
from uuid import uuid4
from wsgiref.simple_server import make_server
from zipfile import ZipFile

import httpx
import pytest

import propertyscope_suburb_analytics.ingestion as ingestion_module
from propertyscope_suburb_analytics.app import create_app as create_backend
from propertyscope_suburb_analytics.clients import HttpClient, ServiceError
from propertyscope_suburb_analytics.ingestion import (
    PRODUCTS,
    Ingestion,
    access_policy,
    bounded_get,
    contract_validators,
    correlation,
    references,
    validate_request,
)
from propertyscope_suburb_store.app import create_app
from propertyscope_suburb_store.imports import Imports
from propertyscope_suburb_store.repository import Repository
from shared_consumer_protocol import ConsumerProtocolError, PublicationRequest


@contextmanager
def serve_origin(app: Any) -> Iterator[str]:
    with make_server("127.0.0.1", 0, app) as server:
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            thread.join(timeout=2)


@contextmanager
def serve(app: Any) -> Iterator[HttpClient]:
    with serve_origin(app) as origin:
        yield HttpClient(origin)


ORIGIN = "http://producer.test"
BASE = "/api/data-platform/v1"
CORRELATION = {"request_id": "test-request", "traceparent": None}


def capture_consumer_errors(monkeypatch: pytest.MonkeyPatch) -> list[BaseException]:
    """Retain the private exception chain only long enough for a failing test to report it."""
    errors: list[BaseException] = []
    consume = ingestion_module.consume_publication

    def capture(*args: Any, **kwargs: Any) -> Any:
        try:
            return consume(*args, **kwargs)
        except BaseException as exc:
            errors.append(exc)
            raise

    monkeypatch.setattr(ingestion_module, "consume_publication", capture)
    return errors


def exception_chain(errors: list[BaseException]) -> str:
    if not errors:
        return "consumer did not expose an exception"
    chain: list[str] = []
    current: BaseException | None = errors[-1]
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        code = getattr(current, "code", None)
        label = type(current).__name__ + (f"[{code}]" if code else "")
        chain.append(f"{label}: {current}")
        original = getattr(current, "original_error", None)
        current = original if isinstance(original, BaseException) else current.__cause__
    return " <- ".join(chain)


def fixture(
    dataset: str = "bocsar-crime", count: int = 1
) -> tuple[dict[str, Any], list[dict[str, Any]], bytes]:
    release = str(uuid4())
    provenance = {
        "release_id": release,
        "candidate_generation_id": release,
        "release_version": "test.1",
        "normalisation_version": "1.0.0",
        "source_record_sha256": "a" * 64,
    }
    months = ["2026-01-01", "2026-02-01"]
    if dataset == "bocsar-crime":
        record = {
            "geography_kind": "suburb",
            "geography_value": "Parramatta",
            "state": "NSW",
            "source_category_key": "theft",
            "offence_label": "Theft",
            "observed_months": months,
            "first_month": months[0],
            "last_month": months[-1],
            "month_count": 2,
            "blank_means_observed_zero": True,
            "completeness_sha256": hashlib.sha256(
                json.dumps(months, separators=(",", ":")).encode()
            ).hexdigest(),
            "observations": [{"month": months[0], "count": 3, "source_row_sha256": "a" * 64}],
        }
    elif dataset == "abs-seifa-2021":
        record = {
            "sal_code": "10001",
            "sal_name": "Parramatta",
            "locality_name": "Parramatta",
            "state": "NSW",
            "reference_year": 2021,
            "usual_resident_population": 30211,
        }
    else:
        record = {
            "school_code": "1001",
            "school_name": "Example School",
            "school_type": "Primary",
            "operational_status": "Open",
            "locality_original": "Parramatta",
            "locality_normalised": "PARRAMATTA",
            "state": "NSW",
            "lga": "Parramatta",
            "latitude": -33.81,
            "longitude": 151.01,
        }
    record["provenance"] = provenance
    records = [deepcopy(record) for _ in range(count)]
    for index, row in enumerate(records):
        key = {
            "bocsar-crime": "source_category_key",
            "abs-seifa-2021": "sal_code",
            "nsw-government-schools": "school_code",
        }[dataset]
        if index:
            row[key] = str(row[key]) + str(index)
    artifact = gzip.compress(b"".join(json.dumps(row).encode() + b"\n" for row in records))
    manifest = {
        "manifest_schema_version": "propertyscope.release-manifest.v2",
        "release_id": release,
        "dataset_id": dataset,
        "target_feature": PRODUCTS[dataset][1],
        "product_schema_version": PRODUCTS[dataset][0],
        "content_sha256": hashlib.sha256(artifact).hexdigest(),
        "record_count": count,
        "byte_count": len(artifact),
        "media_type": "application/x-ndjson",
        "content_encoding": "gzip",
        "download_permitted": True,
        "builder_key": "test-builder",
        "builder_version": "1.0.0",
        "source_release": "synthetic-offline-test",
        "known_limitations": ["Synthetic test only"],
        **{
            key: provenance[key]
            for key in ("candidate_generation_id", "release_version", "normalisation_version")
        },
    }
    payload = {
        key: manifest[key] for key in ("release_id", "dataset_id", "content_sha256", "record_count")
    }
    payload.update(
        schema_version=PRODUCTS[dataset][0],
        manifest=manifest,
        artifact_path=BASE + f"/dataset-releases/{release}/artifact",
        idempotency_key="delivery-" + release,
    )
    return payload, records, artifact


def producer_app(payload: dict[str, Any], artifact: bytes, mutate: Any = None) -> Any:
    # Producer-owned test schemas are served through discovery, never imported from Feature 1.
    schema = {
        "type": "object",
        "required": ["state", "provenance"],
        "properties": {"state": {"const": "NSW"}},
    }
    manifest_schema = {"type": "object", "required": ["download_permitted"]}
    entry = {
        key: payload["manifest"][key]
        for key in (
            "builder_key",
            "builder_version",
            "target_feature",
            "media_type",
            "content_encoding",
        )
    }
    entry.update(
        schema_path=PRODUCTS[payload["dataset_id"]][2], schema_version=payload["schema_version"]
    )
    files = {
        "product-contract-set.v1.json": {"contracts": [entry]},
        entry["schema_path"]: schema,
        "release-manifest.v2.schema.json": manifest_schema,
    }
    if mutate:
        mutate(files)
    stream = io.BytesIO()
    with ZipFile(stream, "w") as archive:
        for name, value in files.items():
            archive.writestr(name, json.dumps(value))
    blob = stream.getvalue()
    digest = hashlib.sha256(blob).hexdigest()
    contract_path = BASE + f"/product-contracts/v1/sha256/{digest}.zip"

    def respond(environ: dict[str, Any], start_response: Any) -> list[bytes]:
        path = environ["PATH_INFO"]
        if path.endswith("/product-contracts/v1"):
            body = json.dumps(
                {
                    "content_sha256": digest,
                    "byte_count": len(blob),
                    "artifact_path": contract_path,
                }
            ).encode()
            content_type = "application/json"
        elif path == contract_path:
            body = blob
            content_type = "application/zip"
        elif path.endswith("/accepted"):
            body = json.dumps({"release": {"manifest": payload["manifest"]}}).encode()
            content_type = "application/json"
        else:
            assert path == payload["artifact_path"]
            assert environ["HTTP_X_REQUEST_ID"] == CORRELATION["request_id"]
            body = artifact
            content_type = "application/gzip"
        start_response(
            "200 OK",
            [("Content-Type", content_type), ("Content-Length", str(len(body)))],
        )
        return [body]

    return respond


@pytest.fixture
def database(tmp_path: Path) -> Imports:
    repo = Repository(tmp_path / "test.sqlite3")
    repo.initialise()
    return Imports(repo)


@pytest.mark.parametrize("dataset", PRODUCTS)
def test_compiled_contract_validation_preserves_formats_and_types(dataset: str) -> None:
    payload, records, artifact = fixture(dataset)

    def strict_schema(files: dict[str, Any]) -> None:
        schema = files[PRODUCTS[dataset][2]]
        schema["properties"]["provenance"] = {
            "type": "object",
            "properties": {"release_id": {"type": "string", "format": "uuid"}},
        }
        schema["properties"]["strict_count"] = {"type": "integer", "minimum": 0}

    with serve_origin(producer_app(payload, artifact, mutate=strict_schema)) as origin:
        with httpx.Client() as client:
            validate, _ = contract_validators(
                client, origin, PublicationRequest.model_validate(payload)
            )
        validate(records[0], 1)
        invalid_format = deepcopy(records[0])
        invalid_format["provenance"]["release_id"] = "not-a-uuid"
        with pytest.raises(ValueError, match="uuid"):
            validate(invalid_format, 1)
        for invalid_count in (True, -1, 1.5, "1"):
            with pytest.raises(ValueError):
                validate(records[0] | {"strict_count": invalid_count}, 1)


@pytest.mark.parametrize("dataset", PRODUCTS)
def test_stream_commit_and_replay_through_real_database_http(
    database: Imports, dataset: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    errors = capture_consumer_errors(monkeypatch)
    payload, records, artifact = fixture(dataset, 2)
    with (
        serve(create_app(database.repository)) as store,
        serve_origin(producer_app(payload, artifact)) as origin,
        httpx.Client() as client,
    ):
        consumer = Ingestion(store, origin)
        ack = consumer.enqueue(payload, CORRELATION, payload["idempotency_key"], callback=False)
        assert ack["status"] == "queued"
        assert database.localities("")["items"] == []
        assert consumer.run_once(client)
        assert not consumer.run_once(client)
        terminal = database.status(ack["consumer_operation_id"])
        assert terminal["status"] == "accepted", exception_chain(errors)
        assert terminal["rows_accepted"] == 2
        assert (
            consumer.enqueue(payload, CORRELATION, payload["idempotency_key"], callback=False)
            == terminal
        )
        assert database.localities("parra")["items"] == ["PARRAMATTA"]
        key = {
            "bocsar-crime": "crime",
            "abs-seifa-2021": "population",
            "nsw-government-schools": "schools",
        }[dataset]
        assert database.context(" Parramatta ")[key] == records
        assert database.sources()["items"][0]["active"] is True


@pytest.mark.parametrize(
    "fault",
    [
        "digest",
        "schema",
        "provenance",
        "coverage",
        "bounds",
        "months",
        "observation",
        "duplicate",
        "duplicate_key",
    ],
)
def test_failed_replacement_never_exposes_staging(
    database: Imports, fault: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    errors = capture_consumer_errors(monkeypatch)
    payload, records, artifact = fixture()
    with serve(create_app(database.repository)) as store:
        with serve_origin(producer_app(payload, artifact)) as origin, httpx.Client() as client:
            consumer = Ingestion(store, origin)
            baseline = consumer.enqueue(payload, CORRELATION, payload["idempotency_key"])
            consumer.run_once(client)
        baseline_status = database.status(baseline["consumer_operation_id"])
        assert baseline_status["status"] == "accepted", exception_chain(errors)
        next_payload, next_records, next_artifact = fixture()
        row = next_records[0]
        if fault == "schema":
            row["state"] = "VIC"
        if fault == "provenance":
            row["provenance"]["release_id"] = str(uuid4())
        if fault == "coverage":
            row["completeness_sha256"] = "b" * 64
        if fault == "bounds":
            row["month_count"] = 1
        if fault == "months":
            row["observed_months"] = ["2026-01-02", "2026-02-01"]
            row["first_month"] = "2026-01-02"
            row["completeness_sha256"] = hashlib.sha256(
                json.dumps(row["observed_months"], separators=(",", ":")).encode()
            ).hexdigest()
        if fault == "observation":
            row["observations"][0]["month"] = "2027-01-01"
        if fault == "duplicate":
            row["observations"].append(deepcopy(row["observations"][0]))
        if fault == "duplicate_key":
            next_records.append(deepcopy(row))
        if fault != "digest":
            next_artifact = gzip.compress(
                b"".join(json.dumps(item).encode() + b"\n" for item in next_records)
            )
        else:
            next_artifact = gzip.compress(b"{}\n")
        next_payload["manifest"]["byte_count"] = len(next_artifact)
        if fault != "digest":
            next_payload["content_sha256"] = next_payload["manifest"]["content_sha256"] = (
                hashlib.sha256(next_artifact).hexdigest()
            )
        next_payload["record_count"] = next_payload["manifest"]["record_count"] = len(next_records)
        with (
            serve_origin(producer_app(next_payload, next_artifact)) as origin,
            httpx.Client() as client,
        ):
            consumer = Ingestion(store, origin)
            ack = consumer.enqueue(next_payload, CORRELATION, next_payload["idempotency_key"])
            consumer.run_once(client)
        assert database.status(ack["consumer_operation_id"])["status"] == "failed"
        assert database.context("Parramatta")["crime"] == records


def test_reclaim_fences_old_worker_and_preserves_identity(database: Imports) -> None:
    payload, records, _ = fixture()
    ack = database.enqueue({"request": payload, "correlation": CORRELATION})
    first = database.claim()
    database.apply(
        first["id"],
        "stage",
        {"token": first["token"], "items": [{"ordinal": 1, "record": records[0]}]},
    )
    assert database.localities("")["items"] == []
    with database.repository.connect() as db:
        db.execute("UPDATE source_imports SET lease_until=0")
    second = Imports(database.repository).claim()
    assert first["id"] == second["id"] == ack["consumer_operation_id"]
    assert first["token"] != second["token"]
    with pytest.raises(ValueError, match="lease_conflict"):
        database.apply(first["id"], "stage", {"token": first["token"], "items": []})
    with database.repository.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM source_records").fetchone()[0] == 1
    database.apply(
        second["id"],
        "stage",
        {
            "token": second["token"],
            "items": [{"ordinal": 1, "record": records[0]}],
        },
    )
    changed = deepcopy(records[0])
    changed["offence_label"] = "Changed data"
    with pytest.raises(ValueError, match="staging_evidence_conflict"):
        database.apply(
            second["id"],
            "stage",
            {
                "token": second["token"],
                "items": [{"ordinal": 1, "record": changed}],
            },
        )
    replay = deepcopy(payload)
    replay["idempotency_key"] = "another-delivery"
    assert (
        database.enqueue({"request": replay, "correlation": CORRELATION})["consumer_operation_id"]
        == first["id"]
    )
    replacement, _, _ = fixture()
    replacement["idempotency_key"] = "another-delivery"
    with pytest.raises(ValueError, match="identity_conflict"):
        database.enqueue({"request": replacement, "correlation": CORRELATION})
    with pytest.raises(ValueError, match="not_found"):
        database.status("missing")


@pytest.mark.parametrize(
    "fault", ["dataset", "schema", "target", "licence", "bytes", "records", "path", "population"]
)
def test_rejects_unsupported_requests(fault: str) -> None:
    payload, _, _ = fixture("abs-seifa-2021" if fault == "population" else "bocsar-crime")
    if fault == "dataset":
        payload["dataset_id"] = payload["manifest"]["dataset_id"] = "unknown"
    if fault == "schema":
        payload["schema_version"] = payload["manifest"]["product_schema_version"] = "unknown.v1"
    if fault == "target":
        payload["manifest"]["target_feature"] = "feature-2"
    if fault == "licence":
        payload["manifest"]["download_permitted"] = False
    if fault == "bytes":
        payload["manifest"]["byte_count"] = 1_000_000_001
    if fault == "records":
        payload["record_count"] = payload["manifest"]["record_count"] = 1_000_001
    if fault == "path":
        payload["artifact_path"] = "http://attacker.test/file"
    with pytest.raises((ValueError, ConsumerProtocolError)):
        validate_request(payload)


def test_contract_discovery_rejects_remote_references() -> None:
    payload, _, artifact = fixture()

    def mutate(files: dict[str, Any]) -> None:
        files[PRODUCTS["bocsar-crime"][2]]["$ref"] = "http://attacker.test/schema"

    with (
        serve_origin(producer_app(payload, artifact, mutate)) as origin,
        httpx.Client() as client,
        pytest.raises(ValueError, match="external_schema"),
    ):
        contract_validators(client, origin, PublicationRequest.model_validate(payload))
    assert references([{"$ref": "#/local"}, 1]) == ["#/local"]


def test_transport_limits_and_correlation() -> None:
    with (
        httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"too big"))
        ) as client,
        pytest.raises(ValueError, match="capacity"),
    ):
        bounded_get(client, ORIGIN, 2)
    assert correlation({})["request_id"]
    assert correlation({"HTTP_X_REQUEST_ID": "test"})["request_id"] == "test"
    assert access_policy(ORIGIN).max_compressed_bytes >= 499_760_265


def test_public_callback_status_read_routes_and_explicit_retry(database: Imports) -> None:
    payload, _, artifact = fixture()
    with (
        serve(create_app(database.repository)) as store,
        serve(create_backend(store, store, HttpClient(ORIGIN))) as backend,
        httpx.Client() as client,
    ):
        path = backend.base_url + "/api/data-import/v1/propertyscope-releases"
        assert client.post(path, json=payload).status_code == 422
        response = client.post(
            path,
            json=payload,
            headers={
                "Idempotency-Key": payload["idempotency_key"],
                "X-Request-ID": "test-request",
            },
        )
        assert response.status_code == 202
        operation = response.json()["consumer_operation_id"]
        assert client.get(path + "/" + operation).json()["status"] == "queued"
        for route in ("sources", "suburbs", "context?locality=Parramatta"):
            assert (
                client.get(
                    backend.base_url + "/api/suburb-analytics/v1/published/" + route
                ).status_code
                == 200
            )
        consumer = Ingestion(store, ORIGIN)
        with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503))) as failed:
            consumer.run_once(failed)
        assert database.status(operation)["status"] == "failed"
        retry = client.post(
            backend.base_url + f"/api/suburb-analytics/v1/data-imports/{operation}/retry"
        )
        assert retry.status_code == 202
        retry_operation = retry.json()["consumer_operation_id"]
        assert retry_operation != operation
        with serve_origin(producer_app(payload, artifact)) as origin, httpx.Client() as valid:
            Ingestion(store, origin).run_once(valid)
        assert database.status(retry_operation)["status"] == "accepted"
        assert database.status(operation)["status"] == "failed"
        assert database.retry(operation)["consumer_operation_id"] == retry_operation
        with pytest.raises(ValueError, match="retry_conflict"):
            database.retry(retry_operation)


def test_transport_retry_is_bounded_and_fresh_key_preserves_failed_receipt(
    database: Imports,
) -> None:
    payload, _, _ = fixture()
    ack = database.enqueue({"request": payload, "correlation": CORRELATION})
    operation = ack["consumer_operation_id"]
    for attempt in range(1, 6):
        with database.repository.connect() as db:
            db.execute("UPDATE source_imports SET next_attempt_at=0 WHERE id=?", (operation,))
        job = database.claim()
        receipt = {
            k: payload[k]
            for k in (
                "release_id",
                "dataset_id",
                "schema_version",
                "content_sha256",
                "record_count",
            )
        }
        receipt.update(
            target="feature-3",
            consumer_operation_id=operation,
            status="failed",
            rows_received=0,
            rows_accepted=0,
            rows_rejected=0,
            error={
                "code": "artifact_transport_failed",
                "message": "Interrupted",
                "retryable": True,
            },
        )
        database.apply(operation, "fail", {"token": job["token"], "receipt": receipt})
        assert database.status(operation)["status"] == ("queued" if attempt < 5 else "failed")
    assert database.enqueue({"request": payload, "correlation": CORRELATION})["status"] == "failed"
    fresh = deepcopy(payload)
    fresh["idempotency_key"] = "fresh-delivery"
    retried = database.enqueue({"request": fresh, "correlation": CORRELATION})
    assert retried["consumer_operation_id"] != operation
    assert retried["status"] == "queued"
    assert database.status(operation)["status"] == "failed"
    assert (
        database.enqueue({"request": payload, "correlation": CORRELATION})["consumer_operation_id"]
        == operation
    )
    alias = deepcopy(fresh)
    alias["idempotency_key"] = "another-browser"
    assert database.enqueue({"request": alias, "correlation": CORRELATION}) == retried
    with database.repository.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM source_attempt_receipts").fetchone()[0] == 4


def test_locality_index_upgrade_preserves_rows_and_bounds_ordered_lookup(database: Imports) -> None:
    with database.repository.connect() as db:
        db.execute("DROP INDEX source_locality_record")
        db.execute("CREATE INDEX source_locality ON source_records(operation_id,locality)")
        db.executemany(
            "INSERT INTO source_records VALUES (?,?,?,?,?)",
            [
                (
                    "index-fixture",
                    index,
                    f"key-{index:04}",
                    "PARRAMATTA" if index in {7, 13, 311} else "OTHER",
                    "{}",
                )
                for index in range(1_000)
            ],
        )
    Imports(database.repository)
    with database.repository.connect() as db:
        query = (
            "SELECT record_key FROM source_records WHERE operation_id=? AND locality=? "
            "ORDER BY record_key LIMIT 501"
        )
        parameters = ("index-fixture", "PARRAMATTA")
        assert [row[0] for row in db.execute(query, parameters)] == [
            "key-0007",
            "key-0013",
            "key-0311",
        ]
        assert db.execute("SELECT count(*) FROM source_records").fetchone()[0] == 1_000
        plan = " ".join(row[3] for row in db.execute("EXPLAIN QUERY PLAN " + query, parameters))
        assert "operation_id=? AND locality=?" in plan
        assert "TEMP B-TREE" not in plan


def test_legacy_import_migration_preserves_failed_operation(database: Imports) -> None:
    payload, _, _ = fixture()
    ack = database.enqueue({"request": payload, "correlation": CORRELATION})
    with database.repository.connect() as db:
        db.execute("ALTER TABLE source_imports DROP COLUMN attempt_number")
        db.execute("ALTER TABLE source_imports DROP COLUMN next_attempt_at")
    migrated = Imports(database.repository)
    assert migrated.status(ack["consumer_operation_id"]) == ack
    assert migrated.claim()["id"] == ack["consumer_operation_id"]


def test_sync_keeps_population_target_and_requires_accepted_lookup(
    database: Imports,
) -> None:
    payload, _, artifact = fixture("abs-seifa-2021")
    with (
        serve(create_app(database.repository)) as store,
        serve_origin(producer_app(payload, artifact)) as origin,
    ):
        consumer = Ingestion(store, origin)
        ack = consumer.sync("abs-seifa-2021", CORRELATION)
        assert ack["target"] == "feature-1"
        with httpx.Client() as client:
            consumer.run_once(client)
        assert database.status(ack["consumer_operation_id"])["status"] == "accepted"
        with pytest.raises(ValueError, match="unsupported"):
            consumer.sync("unknown", CORRELATION)
        with pytest.raises(ValueError, match="idempotency"):
            consumer.enqueue(payload, CORRELATION, "wrong", callback=False)


def test_lost_commit_response_reconciles_without_deleting_accepted_data(database: Imports) -> None:
    payload, records, artifact = fixture(count=51)

    class LostReply(HttpClient):
        def request(
            self, method: str, path: str, payload: dict[str, Any] | None = None
        ) -> dict[str, Any]:
            result = super().request(method, path, payload)
            if path.endswith("/commit"):
                raise ServiceError(503, {"code": "simulated_lost_reply"})
            return result

    with (
        serve(create_app(database.repository)) as store,
        serve_origin(producer_app(payload, artifact)) as origin,
    ):
        consumer = Ingestion(LostReply(store.base_url), origin)
        ack = consumer.enqueue(payload, CORRELATION, payload["idempotency_key"])
        with httpx.Client() as client:
            assert consumer.run_once(client)
            assert not consumer.run_once(client)
        assert database.status(ack["consumer_operation_id"])["status"] == "accepted"
        assert len(database.context("Parramatta")["crime"]) == len(records)


def test_background_reconciliation_continues_after_missing_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    consumer = Ingestion(HttpClient("http://store.test"), ORIGIN)
    calls: list[str] = []

    def sync(dataset: str, correlation: dict[str, Any]) -> dict[str, Any]:
        calls.append(dataset)
        assert correlation["request_id"]
        if dataset == "bocsar-crime":
            raise ValueError("source_unavailable")
        return {"status": "accepted"}

    monkeypatch.setattr(consumer, "sync", sync)
    consumer.reconcile_accepted()
    assert calls == list(PRODUCTS)
