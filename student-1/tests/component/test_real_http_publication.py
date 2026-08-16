from __future__ import annotations

import base64
import hashlib
import json
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import jsonschema
import pytest
from flask import Flask, jsonify, request
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
from propertyscope_data_platform.release_builders import BuildContext, resolve_release_builder
from propertyscope_data_platform.runner import AcquisitionRunner, RunnerSettings

ROOT = Path(__file__).parents[2]
FIXED_TIME = datetime(2026, 8, 16, 1, 2, 3, tzinfo=UTC)


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
            "display_address": "1 HTTP STREET PARRAMATTA NSW 2150",
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
    release_id = str(context.release_id)
    run_id = "50000000-0000-0000-0000-000000000099"
    task_id = "40000000-0000-0000-0000-000000000099"
    observed: dict[str, Any] = {}
    control = Flask(f"runner-control-{dataset_id}")

    @control.get("/internal/data-platform/v1/worker/runs/<request_run_id>/release-build-context")
    def build_context(request_run_id: str) -> Any:
        assert request_run_id == run_id
        builder = resolve_release_builder(builder_key, "1.0.0")
        return jsonify(
            {
                "context": context.model_dump(mode="json"),
                "builder": {"key": builder_key, "version": "1.0.0"},
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
                "items": rows,
                "count": len(rows),
                "total": len(rows),
                "next_offset": None,
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
    assert rows_in == len(rows)
    assert rows_out == binding["record_count"]
    assert artifact["artifact_kind"] == "release_export"
    assert artifact["schema_version"] == resolve_release_builder(builder_key, "1.0.0").spec.contract
    assert hashlib.sha256(content).hexdigest() == binding["content_sha256"]
    assert json.loads(content)["schema_version"] == artifact["schema_version"]


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
    builder = resolve_release_builder(builder_key, "1.0.0")
    product = builder.build(context, rows, created_at=FIXED_TIME)
    artifact = LocalArtifactStore(tmp_path).put(
        [product.content], max_bytes=50_000_000, media_type="application/json"
    )
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
    database = Flask(f"database-{dataset_id}")

    @database.get("/internal/data-platform/v1/releases/<release_id>")
    def get_release(release_id: str) -> Any:
        assert release_id == release["id"]
        return jsonify({"release": release, "receipts": receipts})

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
                    "content_encoding": None,
                }
            }
        )

    @database.post("/internal/data-platform/v1/releases/<release_id>/receipts")
    def record_receipt(release_id: str) -> Any:
        body = request.get_json()
        receipt = {"id": f"receipt-{dataset_id}", **body}
        receipts.append(receipt)
        return jsonify({"receipt": receipt, "created": True}), 201

    @database.post("/internal/data-platform/v1/releases/<release_id>/transition")
    def transition_release(release_id: str) -> Any:
        body = request.get_json()
        assert body["target"] == "accepted"
        assert receipts[-1]["status"] == "accepted"
        release.update(status="accepted", version=3, accepted_at=FIXED_TIME.isoformat())
        return jsonify({"release": release})

    @database.get("/internal/data-platform/v1/releases")
    def list_releases() -> Any:
        items = [release] if release["status"] == "accepted" else []
        return jsonify({"items": items, "count": len(items), "next_cursor": None})

    provider_origin: dict[str, str] = {}
    consumer = Flask(f"consumer-{dataset_id}")

    @consumer.post("/api/data-import/v1/propertyscope-releases")
    def import_release() -> Any:
        publication = ConsumerPublicationRequest.model_validate(request.get_json())
        response = httpx.get(
            provider_origin["url"] + publication.artifact_path,
            follow_redirects=False,
            timeout=5,
        )
        assert response.status_code == 200
        assert hashlib.sha256(response.content).hexdigest() == publication.content_sha256
        expected_digest = base64.b64encode(bytes.fromhex(publication.content_sha256)).decode()
        assert response.headers["Digest"] == f"sha-256=:{expected_digest}:"
        payload = response.json()
        schema = json.loads(
            (ROOT / "contracts" / f"{builder_key}.v1.schema.json").read_text("utf-8")
        )
        jsonschema.validate(payload, schema)
        if dataset_id == "nsw-psi-sales":
            assert payload["records"][0]["price_aud"] is None
            assert payload["records"][0]["area_original"] == "1.50"
        if dataset_id == "bocsar-crime":
            series = payload["records"][0]
            observed = {item["month"]: item["count"] for item in series["observations"]}
            assert observed.get("2025-02-01", 0) == 0
            assert "2025-03-01" not in series["observed_months"]
        if dataset_id == "nsw-government-schools":
            assert payload["records"][0]["operational_status"] == "Closed"
        return jsonify(
            {
                "consumer_operation_id": publication.idempotency_key,
                "status": "accepted",
                "schema_version": publication.schema_version,
                "content_sha256": publication.content_sha256,
                "rows_received": publication.record_count,
                "rows_accepted": publication.record_count,
                "rows_rejected": 0,
                "error": None,
            }
        )

    with _serve(database) as database_url, _serve(consumer) as consumer_url:
        endpoints = {
            context.target_feature: ConsumerEndpoint(
                consumer_url, "/api/data-import/v1/propertyscope-releases"
            )
        }
        backend = create_app(
            store_client=DataStoreClient(database_url, "secret"),
            ai_mode_client=AiModeClient("http://127.0.0.1:1"),
            consumer_client=ConsumerImportClient(endpoints),
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
            publish = httpx.post(
                f"{backend_url}/api/data-platform/v1/dataset-releases/{release['id']}/publish",
                headers={"Idempotency-Key": f"publish-{dataset_id}"},
                json={"version": 2, "comment": "HTTP contract verified", "approved": True},
            )
            assert publish.status_code == 200
            assert release["status"] == "accepted"
            if context.target_feature != "feature-1":
                assert receipts[-1]["rows_accepted"] == len(json.loads(product.content)["records"])
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
