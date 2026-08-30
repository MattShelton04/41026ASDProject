from __future__ import annotations

import gzip
import hashlib
import io
import json
import threading
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import httpx
import jsonschema
import pytest
from flask import Flask, Response, jsonify, request
from werkzeug.serving import BaseWSGIServer, make_server

from propertyscope_data_platform.app import create_app
from propertyscope_data_platform.artifacts import LocalArtifactStore
from propertyscope_data_platform.clients import (
    AiModeClient,
    ConsumerEndpoint,
    ConsumerImportClient,
    DataStoreClient,
)
from propertyscope_data_platform.domain import ConsumerPublicationRequest
from propertyscope_data_platform.release_builders import (
    BuildContext,
    default_release_builders,
    resolve_release_builder,
)
from propertyscope_data_platform.runner import AcquisitionRunner, RunnerSettings
from shared_consumer_protocol import (
    ArtifactAccessPolicy,
    CorrelationContext,
    ImportEvidence,
    ImportReceipt,
    PublicationRequest,
    ReleaseIdentity,
    consume_publication,
)

ROOT = Path(__file__).parents[2]
FIXED_TIME = datetime(2026, 8, 16, 1, 2, 3, tzinfo=UTC)


class _AtomicMemorySink:
    """Test consumer staging area that exposes records only at verified commit."""

    def __init__(self) -> None:
        self.identity: ReleaseIdentity | None = None
        self.consumer_operation_id: str | None = None
        self.staged: list[tuple[int, Mapping[str, Any]]] = []
        self.committed: tuple[Mapping[str, Any], ...] = ()
        self.evidence: ImportEvidence | None = None
        self.rolled_back = False

    def begin(self, identity: ReleaseIdentity, *, consumer_operation_id: str) -> None:
        self.identity = identity
        self.consumer_operation_id = consumer_operation_id

    def stage(self, record: Mapping[str, Any], *, ordinal: int) -> None:
        self.staged.append((ordinal, record))

    def commit(self, evidence: ImportEvidence) -> None:
        self.evidence = evidence
        self.committed = tuple(record for _, record in self.staged)

    def rollback(self) -> None:
        self.staged.clear()
        self.committed = ()
        self.rolled_back = True


def _consume_with_shared_protocol(
    publication: Mapping[str, Any],
    *,
    provider_origin: str,
    target: str,
    consumer_operation_id: str,
    record_schema: Mapping[str, Any],
) -> tuple[ImportReceipt, _AtomicMemorySink]:
    parsed = PublicationRequest.model_validate(publication)
    sink = _AtomicMemorySink()

    def validate_record(record: Mapping[str, Any], ordinal: int) -> None:
        assert ordinal >= 1
        jsonschema.validate(record, record_schema)

    with httpx.Client() as client:
        receipt = consume_publication(
            parsed,
            target=target,
            consumer_operation_id=consumer_operation_id,
            correlation=CorrelationContext(request_id=f"reference-{parsed.dataset_id}"),
            policy=ArtifactAccessPolicy(
                origin=provider_origin,
                artifact_path_template=(
                    "/api/data-platform/v1/dataset-releases/{release_id}/artifact"
                ),
                max_compressed_bytes=50_000_000,
                max_uncompressed_bytes=200_000_000,
                max_records=10_000_000,
                timeout_seconds=5,
            ),
            client=client,
            sink=sink,
            record_validator=validate_record,
        )
    return receipt, sink


def _builder(key: str) -> Any:
    registered = default_release_builders()[key]
    return resolve_release_builder(key, registered.spec.version)


def _download_contract_package(provider_origin: str) -> dict[str, Mapping[str, Any]]:
    metadata_response = httpx.get(
        f"{provider_origin}/api/data-platform/v1/product-contracts/v1", timeout=5
    )
    metadata_response.raise_for_status()
    metadata = metadata_response.json()
    artifact_path = metadata["artifact_path"]
    assert artifact_path.startswith(
        "/api/data-platform/v1/product-contracts/v1/sha256/"
    )
    artifact_response = httpx.get(f"{provider_origin}{artifact_path}", timeout=5)
    artifact_response.raise_for_status()
    content = artifact_response.content
    assert len(content) == metadata["byte_count"]
    assert hashlib.sha256(content).hexdigest() == metadata["content_sha256"]
    with ZipFile(io.BytesIO(content)) as archive:
        return {
            filename: json.loads(archive.read(filename))
            for filename in archive.namelist()
        }


@contextmanager
def _serve(app: Flask) -> Iterator[str]:
    server: BaseWSGIServer = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _context(*, dataset_id: str, target: str, profile: str, policy: str) -> BuildContext:
    return BuildContext(
        release_id=uuid.UUID("60000000-0000-0000-0000-000000000099"),
        release_version="release-http-v1",
        dataset_id=dataset_id,
        target_feature=target,
        candidate_generation_id=uuid.UUID("60000000-0000-0000-0000-000000000099"),
        import_profile=profile,
        normalisation_version="1.0.0",
        publisher="PropertyScope deterministic test",
        source="Synthetic HTTP integration source",
        source_release="fixture-v1",
        source_licence="synthetic-test-data",
        licence_url="https://creativecommons.org/publicdomain/zero/1.0/",
        redistribution_policy=policy,
        scope={"maximum_records": 20},
    )


def _product_case(name: str) -> tuple[str, BuildContext, list[dict[str, Any]]]:
    provenance = {"normalisation_version": "1.0.0"}
    if name in {"fixture-property", "gnaf-nsw"}:
        profile = "property-fixture" if name == "fixture-property" else "gnaf-nsw"
        policy = (
            "committed-synthetic-fixture" if profile == "property-fixture" else "licence-controlled"
        )
        row = {
            "source_address_id": "FIX-HTTP-001"
            if profile == "property-fixture"
            else "GNAF-HTTP-001",
            "property_ref": None,
            "address_display": "1 HTTP STREET PARRAMATTA NSW 2150",
            "flat_type": None,
            "unit_number": None,
            "street_number_first": 1,
            "street_number_suffix": None,
            "street_number_last": None,
            "street_name": "HTTP",
            "street_type": "STREET",
            "locality": "PARRAMATTA",
            "postcode": "2150",
            "source_status": "CURRENT",
            "geocode_type": "ADDRESS",
            "source_crs": "EPSG:4326",
            "geometry": {"type": "Point", "coordinates": [151.0011, -33.8151]},
            "source_row_sha256": hashlib.sha256(name.encode()).hexdigest(),
            **provenance,
        }
        return (
            "property-snapshot",
            _context(dataset_id=name, target="feature-1", profile=profile, policy=policy),
            [row],
        )
    if name == "nsw-psi-sales":
        row = {
            "source_business_key": "001:P1:HTTP",
            "source_revision": 2,
            "source_era": "post-2001",
            "district_code": "001",
            "property_id": "P1",
            "dealing_id": None,
            "contract_date": None,
            "settlement_date": "2025-02-01",
            "price_aud": None,
            "area_original": "1.50",
            "area_unit": "H",
            "area_square_metres": "15000.00",
            "property_ref": None,
            "match_tier": "MISS",
            "match_confidence": "0.0000",
            "geographic_precision": "unmatched",
            "source_row_sha256": "b" * 64,
            **provenance,
        }
        return (
            "property-sales",
            _context(
                dataset_id=name,
                target="feature-2",
                profile="psi-sales",
                policy="bounded-derived-release",
            ),
            [row],
        )
    if name == "bocsar-crime":
        months = ("2025-01-01", "2025-02-01")
        completeness = hashlib.sha256(
            json.dumps(months, separators=(",", ":")).encode()
        ).hexdigest()
        common = {
            "geography_kind": "postcode",
            "geography_value": "2000",
            "source_category_key": "http-category",
            **provenance,
        }
        return (
            "crime-series",
            _context(
                dataset_id=name,
                target="feature-3",
                profile="bocsar-sparse",
                policy="approved-bounded-extract",
            ),
            [
                {
                    **common,
                    "record_kind": "coverage",
                    "observed_months": list(months),
                    "first_month": months[0],
                    "last_month": months[-1],
                    "month_count": 2,
                    "blank_means_observed_zero": True,
                    "completeness_sha256": completeness,
                    "source_row_sha256": "c" * 64,
                },
                {
                    **common,
                    "record_kind": "observation",
                    "month": months[0],
                    "count": 3,
                    "offence_label": "Fixture offence",
                    "subcategory_label": None,
                    "source_row_sha256": "d" * 64,
                },
            ],
        )
    row = {
        "school_code": "S-HTTP-1",
        "school_name": "HTTP Public School",
        "school_type": "Primary",
        "status": "Closed",
        "locality_original": "Parramatta",
        "locality_normalised": "PARRAMATTA",
        "lga_name": "Parramatta",
        "geometry": {"type": "Point", "coordinates": [151.01, -33.81]},
        "source_row_sha256": "e" * 64,
        **provenance,
    }
    return (
        "school-points",
        _context(
            dataset_id=name,
            target="feature-3",
            profile="schools-master",
            policy="approved-bounded-extract",
        ),
        [row],
    )


@pytest.mark.parametrize(
    "dataset_id",
    [
        "fixture-property",
        "gnaf-nsw",
        "nsw-psi-sales",
        "bocsar-crime",
        "nsw-government-schools",
    ],
)
def test_runner_constructs_every_registered_export_over_real_http(
    dataset_id: str, tmp_path: Path
) -> None:
    builder_key, context, rows = _product_case(dataset_id)
    export_rows = rows
    if builder_key == "crime-series":
        coverage = next(row for row in rows if row["record_kind"] == "coverage")
        observations = [row for row in rows if row["record_kind"] == "observation"]
        export_rows = [
            {
                **coverage,
                "offence_label": observations[0]["offence_label"],
                "subcategory_label": observations[0]["subcategory_label"],
                "observations": [
                    {
                        "month": row["month"],
                        "count": row["count"],
                        "source_row_sha256": row["source_row_sha256"],
                    }
                    for row in observations
                ],
            }
        ]
    release_id = str(context.release_id)
    run_id = "50000000-0000-0000-0000-000000000099"
    task_id = "40000000-0000-0000-0000-000000000099"
    observed: dict[str, Any] = {}
    control = Flask(f"runner-control-{dataset_id}")

    @control.get("/internal/data-platform/v1/worker/runs/<request_run_id>/release-build-context")
    def build_context(request_run_id: str) -> Any:
        assert request_run_id == run_id
        builder = _builder(builder_key)
        return jsonify(
            {
                "context": context.model_dump(mode="json"),
                "builder": {"key": builder_key, "version": builder.spec.version},
                "target_contract": builder.spec.contract,
                "release_id": release_id,
            }
        )

    @control.get("/internal/data-platform/v1/worker/releases/<request_release_id>/product-records")
    def product_records(request_release_id: str) -> Any:
        assert request_release_id == release_id
        return jsonify(
            {
                "release_id": release_id,
                "candidate_generation_id": release_id,
                "items": export_rows,
                "count": len(export_rows),
                "total": len(export_rows),
                "next_cursor": None,
            }
        )

    @control.post("/internal/data-platform/v1/worker/tasks/<request_task_id>/artifacts")
    def register_artifact(request_task_id: str) -> Any:
        assert request_task_id == task_id
        observed["artifact"] = request.get_json()
        return jsonify(
            {
                "artifact": {
                    "id": "70000000-0000-0000-0000-000000000099",
                    **observed["artifact"],
                },
                "created": True,
            }
        ), 201

    @control.post("/internal/data-platform/v1/worker/runs/<request_run_id>/finalize-release")
    def finalize(request_run_id: str) -> Any:
        assert request_run_id == run_id
        observed["binding"] = request.get_json()
        return jsonify({"release": {"id": release_id, "status": "candidate"}})

    with _serve(control) as control_url:
        runner = AcquisitionRunner(
            RunnerSettings(
                backend_url=control_url,
                token="runner-secret",
                artifact_root=tmp_path,
                worker_id="runner-http",
                poll_seconds=0.01,
                lease_seconds=30,
            ),
            clock=lambda: FIXED_TIME,
        )
        rows_in, rows_out = runner._execute(
            {
                "id": task_id,
                "ingestion_run_id": run_id,
                "stage": "build_release",
                "logical_key": "06/build_release",
            }
        )

    binding = observed["binding"]
    artifact = observed["artifact"]
    content = (tmp_path / artifact["storage_key"]).read_bytes()
    assert rows_in == len(export_rows)
    assert rows_out == binding["record_count"]
    assert artifact["artifact_kind"] == "release_export"
    assert artifact["schema_version"] == _builder(builder_key).spec.contract
    assert hashlib.sha256(content).hexdigest() == binding["content_sha256"]
    contract_set = json.loads(
        (ROOT / "contracts" / "product-contract-set.v1.json").read_text("utf-8")
    )
    registration = next(
        item
        for item in contract_set["contracts"]
        if item["schema_version"] == artifact["schema_version"]
    )
    assert binding["manifest"]["media_type"] == registration["media_type"]
    assert binding["manifest"]["content_encoding"] == registration["content_encoding"]
    schema = json.loads((ROOT / "contracts" / registration["schema_path"]).read_text("utf-8"))
    records = [json.loads(line) for line in gzip.decompress(content).splitlines()]
    assert len(records) == len(export_rows)
    for record in records:
        jsonschema.validate(record, schema)
    assert all(record["provenance"]["release_id"] == release_id for record in records)

    if context.redistribution_policy == "licence-controlled":
        assert dataset_id == "gnaf-nsw"
        return

    artifact_path = f"/api/data-platform/v1/dataset-releases/{release_id}/artifact"
    provider = Flask(f"runner-artifact-{dataset_id}")

    @provider.get(artifact_path)
    def runner_artifact() -> Response:
        return Response(content, status=200, content_type="application/gzip")

    delivery_key = f"runner-delivery-{dataset_id}"
    operation_id = f"runner-consumer-operation-{dataset_id}"
    publication = {
        "release_id": release_id,
        "dataset_id": dataset_id,
        "schema_version": artifact["schema_version"],
        "content_sha256": binding["content_sha256"],
        "record_count": binding["record_count"],
        "manifest": binding["manifest"],
        "artifact_path": artifact_path,
        "idempotency_key": delivery_key,
    }
    with _serve(provider) as provider_url:
        receipt, sink = _consume_with_shared_protocol(
            publication,
            provider_origin=provider_url,
            target=context.target_feature,
            consumer_operation_id=operation_id,
            record_schema=schema,
        )

    assert receipt.consumer_operation_id == operation_id
    assert receipt.consumer_operation_id != delivery_key
    assert receipt.status == "accepted"
    assert sink.rolled_back is False
    assert sink.evidence is not None
    assert sink.evidence.content_sha256 == binding["content_sha256"]
    assert list(sink.committed) == records


@pytest.mark.parametrize(
    "dataset_id",
    [
        "fixture-property",
        "gnaf-nsw",
        "nsw-psi-sales",
        "bocsar-crime",
        "nsw-government-schools",
    ],
)
def test_every_registered_product_publishes_with_policy_over_real_http(
    dataset_id: str, tmp_path: Path
) -> None:
    builder_key, context, rows = _product_case(dataset_id)
    builder = _builder(builder_key)
    product = builder.build(context, rows, created_at=FIXED_TIME)
    artifact = LocalArtifactStore(tmp_path).put(
        [product.content], max_bytes=50_000_000, media_type=builder.spec.media_type
    )
    assert product.manifest.media_type == builder.spec.media_type
    assert product.manifest.content_encoding == builder.spec.content_encoding
    assert product.manifest.content_sha256 == artifact.sha256
    assert product.manifest.byte_count == artifact.bytes
    release = {
        "id": str(context.release_id),
        "dataset_id": dataset_id,
        "target_feature": context.target_feature,
        "schema_version": builder.spec.contract,
        "content_sha256": artifact.sha256,
        "record_count": product.manifest.record_count,
        "manifest_json": product.manifest.model_dump(mode="json"),
        "status": "awaiting_review",
        "version": 2,
        "release_version": context.release_version,
        "accepted_at": None,
    }
    receipts: list[dict[str, Any]] = []
    activations: list[dict[str, Any]] = []
    consumer_imports: list[dict[str, Any]] = []
    database = Flask(f"database-{dataset_id}")

    @database.get("/internal/data-platform/v1/releases/<release_id>")
    def get_release(release_id: str) -> Any:
        assert release_id == release["id"]
        return jsonify(
            {
                "release": release,
                "receipts": receipts,
                "activations": activations,
                "consumer_imports": consumer_imports,
            }
        )

    @database.get("/internal/data-platform/v1/releases/<release_id>/artifact")
    def get_artifact(release_id: str) -> Any:
        assert release_id == release["id"]
        return jsonify(
            {
                "artifact": {
                    "release_status": release["status"],
                    "redistribution_policy": context.redistribution_policy,
                    "artifact_kind": "release_export",
                    "bytes": artifact.bytes,
                    "storage_key": artifact.storage_key,
                    "content_sha256": artifact.sha256,
                    "media_type": artifact.media_type,
                    "content_encoding": builder.spec.content_encoding,
                }
            }
        )

    @database.post("/internal/data-platform/v1/releases/<release_id>/receipts")
    def record_receipt(release_id: str) -> Any:
        body = request.get_json()
        receipt = {"id": f"receipt-{dataset_id}", **body}
        receipts.append(receipt)
        return jsonify({"receipt": receipt, "created": True}), 201

    @database.post("/internal/data-platform/v1/releases/<release_id>/consumer-imports")
    def create_consumer_import(release_id: str) -> Any:
        assert release_id == release["id"]
        body = request.get_json()
        existing = next(
            (
                item
                for item in consumer_imports
                if item["idempotency_key"] == body["idempotency_key"]
            ),
            None,
        )
        if existing is not None:
            return jsonify({"operation": existing, "created": False}), 200
        operation = {
            "id": "72000000-0000-0000-0000-000000000099",
            "dataset_release_id": release_id,
            "dataset_id": body["dataset_id"],
            "target_feature": body["target_feature"],
            "schema_version": body["schema_version"],
            "content_sha256": body["content_sha256"],
            "record_count": body["record_count"],
            "idempotency_key": body["idempotency_key"],
            "status": "queued",
            "phase_key": "connect",
            "remote_status": None,
            "consumer_operation_id": None,
            "publication_receipt_id": None,
            "release_activation_id": None,
            "attempt_number": 0,
            "requested_at": FIXED_TIME.isoformat(),
            "started_at": None,
            "finished_at": None,
            "error_json": None,
            "version": 1,
        }
        consumer_imports.append(operation)
        return jsonify({"operation": operation, "created": True}), 202

    @database.post("/internal/data-platform/v1/releases/<release_id>/activations")
    def queue_activation(release_id: str) -> Any:
        assert release_id == release["id"]
        body = request.get_json()
        assert receipts[-1]["status"] == "accepted"
        existing = next(
            (item for item in activations if item["idempotency_key"] == body["idempotency_key"]),
            None,
        )
        if existing is not None:
            return jsonify({"activation": existing, "created": False}), 202
        activation = {
            "id": f"70000000-0000-0000-0000-{len(activations) + 1:012d}",
            "dataset_release_id": release_id,
            "publication_receipt_id": body["publication_receipt_id"],
            "expected_release_version": body["expected_release_version"],
            "idempotency_key": body["idempotency_key"],
            "status": "queued",
            "attempt_number": 1,
            "requested_at": FIXED_TIME.isoformat(),
            "started_at": None,
            "materialized_at": None,
            "finished_at": None,
            "error_json": None,
            "version": 1,
        }
        activations.append(activation)
        return jsonify({"activation": activation, "created": True}), 202

    @database.get("/internal/data-platform/v1/releases")
    def list_releases() -> Any:
        items = [release] if release["status"] == "accepted" else []
        return jsonify({"items": items, "count": len(items), "next_cursor": None})

    provider_origin: dict[str, str] = {}
    consumer = Flask(f"consumer-{dataset_id}")

    @consumer.post("/api/data-import/v1/propertyscope-releases")
    def import_release() -> Any:
        publication = request.get_json()
        contracts = _download_contract_package(provider_origin["url"])
        publication_schema = contracts["consumer-publication-request.v1.schema.json"]
        jsonschema.validate(publication, publication_schema)
        contract_set = contracts["product-contract-set.v1.json"]
        registration = next(
            item
            for item in contract_set["contracts"]
            if item["schema_version"] == publication["schema_version"]
        )
        assert publication["manifest"]["media_type"] == registration["media_type"]
        assert publication["manifest"]["content_encoding"] == registration["content_encoding"]
        schema = contracts[registration["schema_path"]]
        consumer_operation_id = f"consumer-operation-{dataset_id}"
        receipt, sink = _consume_with_shared_protocol(
            publication,
            provider_origin=provider_origin["url"],
            target=context.target_feature,
            consumer_operation_id=consumer_operation_id,
            record_schema=schema,
        )
        assert consumer_operation_id != publication["idempotency_key"]
        assert sink.evidence is not None
        assert sink.evidence.rows_received == publication["record_count"]
        records = list(sink.committed)
        assert len(records) == publication["record_count"]
        if dataset_id == "nsw-psi-sales":
            assert records[0]["price_aud"] is None
            assert records[0]["area_original"] == "1.50"
        if dataset_id == "bocsar-crime":
            series = records[0]
            observed = {item["month"]: item["count"] for item in series["observations"]}
            assert observed.get("2025-02-01", 0) == 0
            assert "2025-03-01" not in series["observed_months"]
        if dataset_id == "nsw-government-schools":
            assert records[0]["operational_status"] == "Closed"
        receipt_payload = receipt.model_dump(mode="json")
        acknowledgement_schema = contracts["consumer-import-acknowledgement.v1.schema.json"]
        jsonschema.validate(receipt_payload, acknowledgement_schema)
        return jsonify(receipt_payload)

    with _serve(database) as database_url, _serve(consumer) as consumer_url:
        endpoints = {
            context.target_feature: ConsumerEndpoint(
                consumer_url, "/api/data-import/v1/propertyscope-releases"
            )
        }
        consumer_client = ConsumerImportClient(endpoints)
        backend = create_app(
            store_client=DataStoreClient(database_url, "secret"),
            ai_mode_client=AiModeClient("http://127.0.0.1:1"),
            consumer_client=consumer_client,
            artifact_root=tmp_path,
        )
        with _serve(backend) as backend_url:
            provider_origin["url"] = backend_url
            artifact_url = (
                f"{backend_url}/api/data-platform/v1/dataset-releases/{release['id']}/artifact"
            )
            before = httpx.get(artifact_url)
            if dataset_id == "gnaf-nsw":
                assert before.status_code == 403
                assert before.headers["content-type"].startswith("application/problem+json")
            else:
                assert before.status_code == 200
                assert before.headers["Cache-Control"] == "private, no-store"
            if context.target_feature != "feature-1":
                delivery_key = f"reference-delivery-{dataset_id}"
                outcome = consumer_client.connect(
                    context.target_feature,
                    ConsumerPublicationRequest(
                        release_id=release["id"],
                        dataset_id=dataset_id,
                        schema_version=release["schema_version"],
                        content_sha256=release["content_sha256"],
                        record_count=release["record_count"],
                        manifest=release["manifest_json"],
                        artifact_path=(
                            f"/api/data-platform/v1/dataset-releases/{release['id']}/artifact"
                        ),
                        idempotency_key=delivery_key,
                    ),
                    {"X-Request-ID": f"reference-connect-{dataset_id}"},
                )
                assert outcome.status == "accepted"
                assert outcome.receipt is not None
                assert outcome.consumer_operation_id == f"consumer-operation-{dataset_id}"
                assert outcome.consumer_operation_id != delivery_key
            publish = httpx.post(
                f"{backend_url}/api/data-platform/v1/dataset-releases/{release['id']}/publish",
                headers={"Idempotency-Key": f"publish-{dataset_id}"},
                json={"version": 2, "comment": "HTTP contract verified", "approved": True},
            )
            assert publish.status_code == 202
            assert release["status"] == "awaiting_review"
            if context.target_feature != "feature-1":
                operation = publish.json()["consumer_import"]
                assert operation["status"] == "queued"
                assert operation["phase_key"] == "connect"
                assert receipts == []
                assert activations == []
            else:
                assert publish.json()["activation"]["status"] == "queued"
            pending_replay = httpx.post(
                f"{backend_url}/api/data-platform/v1/dataset-releases/{release['id']}/publish",
                headers={"Idempotency-Key": f"publish-{dataset_id}"},
                json={"version": 2, "comment": "HTTP contract verified", "approved": True},
            )
            assert pending_replay.status_code == 202
            assert pending_replay.json()["replayed"] is True
            if context.target_feature != "feature-1":
                assert (
                    pending_replay.json()["consumer_import"]["id"]
                    == (publish.json()["consumer_import"]["id"])
                )
                assert len(consumer_imports) == 1
                assert receipts == []
                assert activations == []
                return
            assert pending_replay.json()["activation"]["id"] == (publish.json()["activation"]["id"])
            assert len(receipts) == 1
            assert len(activations) == 1

            activation = activations[0]
            activation.update(
                status="succeeded",
                started_at=FIXED_TIME.isoformat(),
                materialized_at=FIXED_TIME.isoformat(),
                finished_at=FIXED_TIME.isoformat(),
                version=2,
            )
            release.update(status="accepted", version=3, accepted_at=FIXED_TIME.isoformat())
            accepted = httpx.get(
                f"{backend_url}/api/data-platform/v1/data-products/{dataset_id}/accepted"
            )
            assert accepted.status_code == 200
            assert accepted.json()["release"]["content_sha256"] == artifact.sha256
            replay = httpx.post(
                f"{backend_url}/api/data-platform/v1/dataset-releases/{release['id']}/publish",
                headers={"Idempotency-Key": f"publish-{dataset_id}"},
                json={"version": 2, "comment": "HTTP contract verified", "approved": True},
            )
            assert replay.status_code == 200
            assert replay.json()["replayed"] is True
            assert len(receipts) == 1
            assert len(activations) == 1
            accepted_again = httpx.get(
                f"{backend_url}/api/data-platform/v1/data-products/{dataset_id}/accepted"
            )
            assert accepted_again.json() == accepted.json()
            after = httpx.get(artifact_url)
            if dataset_id == "gnaf-nsw":
                assert after.status_code == 403
            else:
                assert after.status_code == 200
                assert after.headers["Cache-Control"] == "public, max-age=31536000, immutable"
