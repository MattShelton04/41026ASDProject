"""Opt-in PostgreSQL proof for import rollback and exact-connection cancellation.

Set PROPERTYSCOPE_TEST_POSTGRES_URL to an administrator URL for a disposable local
PostgreSQL server.  Every test creates and drops its own database; the retained ps-dev
database must never be supplied here.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from importlib.resources import files
from typing import Any, cast

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from propertyscope_data_store import import_profiles
from propertyscope_data_store._consumer_import_operations import _ConsumerImportOperations
from propertyscope_data_store.errors import ConflictError, NotFoundError
from propertyscope_data_store.import_profiles import iter_ndjson_import
from propertyscope_data_store.query_specs import release_export_query
from propertyscope_data_store.repository import PropertyScopeStore
from propertyscope_data_store.source_materialisation import (
    BOCSAR_COPY_SQL,
    BOCSAR_STAGE_SQL,
    BOCSAR_STREAM_COLUMNS,
    PSI_COPY_SQL,
    PSI_STAGE_SQL,
    PSI_STREAM_COLUMNS,
)

ADMIN_URL = os.getenv("PROPERTYSCOPE_TEST_POSTGRES_URL", "").strip()
pytestmark = pytest.mark.skipif(
    not ADMIN_URL,
    reason="set PROPERTYSCOPE_TEST_POSTGRES_URL to a disposable PostgreSQL administrator URL",
)


def _database_url(database: str) -> str:
    values = conninfo_to_dict(ADMIN_URL)
    values["dbname"] = database
    return make_conninfo(**cast(Any, values))


@pytest.fixture()
def isolated_postgres() -> Iterator[psycopg.Connection[dict[str, object]]]:
    database = f"propertyscope_reliability_{uuid.uuid4().hex}"
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    try:
        with psycopg.connect(_database_url(database), row_factory=dict_row) as connection:
            _create_minimal_import_schema(connection)
            yield connection
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname=%s AND pid<>pg_backend_pid()",
                (database,),
            )
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))


def _create_minimal_import_schema(connection: psycopg.Connection[Any]) -> None:
    connection.execute(
        """
        CREATE SCHEMA registry;
        CREATE SCHEMA warehouse;
        CREATE SCHEMA serving;
        CREATE TABLE registry.property (
            property_ref UUID PRIMARY KEY, postcode TEXT, locality TEXT, street_name TEXT,
            street_type TEXT, street_number_first INTEGER, street_number_last INTEGER,
            street_number_suffix TEXT, unit_number TEXT,
            address_display TEXT, flat_type TEXT, state TEXT, address_search TEXT, geom TEXT,
            resolution_status TEXT, created_at TIMESTAMPTZ, updated_at TIMESTAMPTZ, version INTEGER
        );
        CREATE TABLE registry.property_identifier (
            id UUID PRIMARY KEY, property_ref UUID REFERENCES registry.property(property_ref),
            scheme TEXT NOT NULL, identifier_value TEXT NOT NULL, source_release_id UUID NOT NULL,
            is_current BOOLEAN, valid_from DATE, valid_to DATE, match_method TEXT,
            match_confidence NUMERIC, evidence_json JSONB, created_at TIMESTAMPTZ,
            UNIQUE (scheme,identifier_value,source_release_id)
        );
        CREATE TABLE warehouse.psi_sale (
            dataset_release_id UUID NOT NULL, source_business_key TEXT NOT NULL,
            source_revision INTEGER NOT NULL, source_era TEXT NOT NULL,
            source_partition_year INTEGER, district_code TEXT, property_id TEXT, dealing_id TEXT,
            source_system TEXT, valuation_number TEXT, source_downloaded_at TIMESTAMP,
            property_name TEXT, unit_number TEXT, house_number TEXT,
            street_number_first INTEGER, street_number_last INTEGER, street_number_suffix TEXT,
            street_name TEXT, street_name_normalised TEXT, street_type TEXT, locality TEXT,
            postcode TEXT, land_description TEXT, dimensions TEXT, zoning_code TEXT,
            nature_code TEXT, primary_purpose TEXT, strata_lot_number TEXT, component_code TEXT,
            sale_code TEXT, interest_of_sale TEXT, contract_date DATE, settlement_date DATE,
            price_aud BIGINT, area_original NUMERIC, area_unit TEXT, area_square_metres NUMERIC,
            property_ref UUID REFERENCES registry.property(property_ref),
            match_tier TEXT NOT NULL, match_confidence NUMERIC NOT NULL,
            geographic_precision TEXT NOT NULL, source_row_sha256 TEXT NOT NULL,
            normalisation_version TEXT NOT NULL, artifact_record_id UUID NOT NULL,
            ingestion_run_id UUID NOT NULL, created_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (dataset_release_id, source_business_key, source_revision)
        );
        CREATE TABLE warehouse.gnaf_address (
            dataset_release_id UUID NOT NULL,
            gnaf_pid TEXT NOT NULL,
            property_ref UUID,
            postcode TEXT NOT NULL,
            locality TEXT NOT NULL,
            street_name TEXT,
            street_type TEXT,
            street_number_first INTEGER,
            street_number_last INTEGER,
            street_number_suffix TEXT,
            unit_number TEXT,
            published BOOLEAN NOT NULL,
            address_display TEXT DEFAULT '10 EXAMPLE STREET SYDNEY NSW 2000',
            flat_type TEXT, geom TEXT DEFAULT 'POINT(151 -33)',
            source_status TEXT DEFAULT 'CURRENT', geocode_type TEXT DEFAULT 'PC',
            source_crs TEXT DEFAULT 'GDA2020'
        );
        CREATE TABLE warehouse.bocsar_observation (
            dataset_release_id UUID NOT NULL, geography_kind TEXT NOT NULL,
            geography_value TEXT NOT NULL, source_category_key TEXT NOT NULL,
            offence_label TEXT NOT NULL, subcategory_label TEXT NOT NULL, month DATE NOT NULL,
            count INTEGER NOT NULL, source_row_sha256 TEXT NOT NULL,
            normalisation_version TEXT NOT NULL, artifact_record_id UUID NOT NULL,
            ingestion_run_id UUID NOT NULL, created_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (
                dataset_release_id,geography_kind,geography_value,source_category_key,month
            )
        );
        CREATE TABLE warehouse.bocsar_coverage (
            dataset_release_id UUID NOT NULL, geography_kind TEXT NOT NULL,
            geography_value TEXT NOT NULL, source_category_key TEXT NOT NULL,
            observed_months DATE[] NOT NULL, first_month DATE NOT NULL, last_month DATE NOT NULL,
            month_count INTEGER NOT NULL, blank_means_observed_zero BOOLEAN NOT NULL,
            completeness_sha256 TEXT NOT NULL, source_row_sha256 TEXT NOT NULL,
            normalisation_version TEXT NOT NULL, artifact_record_id UUID NOT NULL,
            ingestion_run_id UUID NOT NULL, created_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (dataset_release_id,geography_kind,geography_value,source_category_key)
        );
        CREATE TABLE serving.accepted_generation (
            dataset_id TEXT PRIMARY KEY, dataset_release_id UUID NOT NULL
        );
        """
    )
    connection.commit()


def _psi_row(
    *, key: str, street_number_first: int = 10, house_number: str = "10"
) -> dict[str, object]:
    return {
        "source_business_key": key,
        "source_revision": 1,
        "source_era": "modern",
        "source_partition_year": 2026,
        "district_code": None,
        "property_id": None,
        "dealing_id": None,
        "source_system": None,
        "valuation_number": None,
        "source_downloaded_at": None,
        "property_name": None,
        "unit_number": None,
        "house_number": house_number,
        "street_number_first": street_number_first,
        "street_number_last": None,
        "street_number_suffix": None,
        "street_name": "Example",
        "street_name_normalised": "EXAMPLE",
        "street_type": "ST",
        "locality": "SYDNEY",
        "postcode": "2000",
        "land_description": None,
        "dimensions": None,
        "zoning_code": None,
        "nature_code": None,
        "primary_purpose": None,
        "strata_lot_number": None,
        "component_code": None,
        "sale_code": None,
        "interest_of_sale": None,
        "contract_date": "2026-01-01",
        "settlement_date": None,
        "price_aud": 1_000_000,
        "area_original": None,
        "area_unit": None,
        "area_square_metres": None,
        "property_ref": None,
        "match_tier": "MISS",
        "match_confidence": "0",
        "geographic_precision": "unmatched",
        "source_row_sha256": "0" * 64,
    }


def _accepted_pointer(connection: psycopg.Connection[dict[str, object]]) -> uuid.UUID:
    row = connection.execute(
        "SELECT dataset_release_id FROM serving.accepted_generation WHERE dataset_id='psi'"
    ).fetchone()
    assert row is not None
    return uuid.UUID(str(row["dataset_release_id"]))


def _stage_typed_psi_rows(
    connection: psycopg.Connection[dict[str, object]], rows: list[dict[str, object]]
) -> None:
    connection.execute(PSI_STAGE_SQL)
    with connection.cursor().copy(PSI_COPY_SQL) as copy:
        for ordinal, row in enumerate(rows, start=1):
            copy.write_row(
                (
                    ordinal,
                    *(row[field] for field in PSI_STREAM_COLUMNS[1:]),
                )
            )
    connection.execute("ANALYZE propertyscope_psi_import_stage")


def _stage_typed_bocsar_rows(
    connection: psycopg.Connection[dict[str, object]], rows: list[dict[str, object]]
) -> None:
    connection.execute(BOCSAR_STAGE_SQL)
    with connection.cursor().copy(BOCSAR_COPY_SQL) as copy:
        for ordinal, row in enumerate(rows, start=1):
            values = {**row, "ordinal": ordinal}
            copy.write_row(tuple(values.get(field) for field in BOCSAR_STREAM_COLUMNS))
    connection.execute("ANALYZE propertyscope_bocsar_import_stage")


class _SingleConnectionStore(PropertyScopeStore):
    """Expose the real repository probe against the fixture-owned connection."""

    def __init__(self, connection: psycopg.Connection[dict[str, object]]) -> None:
        self._test_connection = connection

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection[dict[str, object]]]:
        yield self._test_connection


def test_postgres_reports_positive_data_and_wal_filesystem_capacity(
    isolated_postgres: psycopg.Connection[dict[str, object]],
) -> None:
    store = _SingleConnectionStore(isolated_postgres)

    assert store.database_filesystem_available_bytes() > 0


def test_cancel_intent_update_is_not_blocked_by_import_foreign_key_share(
    isolated_postgres: psycopg.Connection[dict[str, object]],
) -> None:
    connection = isolated_postgres
    run_id = uuid.uuid4()
    connection.execute(
        """
        CREATE SCHEMA ops;
        CREATE TABLE ops.ingestion_run (
            id UUID PRIMARY KEY,status TEXT NOT NULL,cancel_requested_at TIMESTAMPTZ
        );
        CREATE TABLE warehouse.cancel_probe (
            id UUID PRIMARY KEY,ingestion_run_id UUID NOT NULL REFERENCES ops.ingestion_run(id)
        );
        """
    )
    connection.execute("INSERT INTO ops.ingestion_run VALUES (%s,'staging',NULL)", (run_id,))
    connection.commit()
    blocker = psycopg.connect(_database_url(str(connection.info.dbname)), row_factory=dict_row)
    canceller = psycopg.connect(_database_url(str(connection.info.dbname)), row_factory=dict_row)
    try:
        blocker.execute("INSERT INTO warehouse.cancel_probe VALUES (%s,%s)", (uuid.uuid4(), run_id))
        canceller.execute("SET LOCAL statement_timeout='1s'")
        started = time.monotonic()
        row = canceller.execute(
            """UPDATE ops.ingestion_run SET cancel_requested_at=clock_timestamp()
            WHERE id=%s AND status NOT IN ('succeeded','failed','cancelled') RETURNING *""",
            (run_id,),
        ).fetchone()
        canceller.commit()
        assert row is not None and row["cancel_requested_at"] is not None
        assert time.monotonic() - started < 1
    finally:
        blocker.rollback()
        blocker.close()
        canceller.close()


def test_lightweight_activation_claim_skips_index_builds_and_live_leases(
    isolated_postgres: psycopg.Connection[dict[str, object]],
) -> None:
    connection = isolated_postgres
    connection.execute("""
        CREATE SCHEMA ops;
        CREATE TABLE ops.dataset_release (id UUID PRIMARY KEY,dataset_id TEXT NOT NULL);
        CREATE TABLE ops.release_activation (
            id UUID PRIMARY KEY,dataset_release_id UUID NOT NULL,status TEXT NOT NULL,
            attempt_number INTEGER DEFAULT 1,finished_at TIMESTAMPTZ,error_json JSONB,
            lease_owner TEXT,lease_token TEXT,lease_expires_at TIMESTAMPTZ,
            heartbeat_at TIMESTAMPTZ,started_at TIMESTAMPTZ,
            requested_at TIMESTAMPTZ DEFAULT clock_timestamp(),version INTEGER DEFAULT 1
        );
    """)
    identifiers = {
        dataset: uuid.uuid4() for dataset in ("gnaf-nsw", "fixture-property", "bocsar-crime")
    }
    for dataset, identity in identifiers.items():
        connection.execute("INSERT INTO ops.dataset_release VALUES (%s,%s)", (identity, dataset))
        connection.execute(
            "INSERT INTO ops.release_activation (id,dataset_release_id,status) "
            "VALUES (%s,%s,'queued')",
            (identity, identity),
        )
    connection.commit()

    class Store(PropertyScopeStore):
        def __init__(self) -> None:
            pass

        @contextmanager
        def connection(self) -> Iterator[psycopg.Connection[dict[str, object]]]:
            yield connection

    store = Store()
    claimed = store.claim_release_activation(
        worker_id="lightweight", lease_seconds=120, lightweight_only=True
    )
    assert claimed is not None and claimed["dataset_release_id"] == str(identifiers["bocsar-crime"])
    assert (
        store.claim_release_activation(
            worker_id="another-lightweight", lease_seconds=120, lightweight_only=True
        )
        is None
    )
    bulk = store.claim_release_activation(worker_id="serial-bulk", lease_seconds=120)
    assert bulk is not None and bulk["dataset_release_id"] == str(identifiers["gnaf-nsw"])


def test_concurrent_consumer_import_creation_coalesces_one_release_identity(
    isolated_postgres: psycopg.Connection[dict[str, object]],
) -> None:
    connection = isolated_postgres
    release_id = uuid.uuid4()
    connection.execute(
        """
        CREATE SCHEMA ops;
        CREATE TABLE ops.dataset_release (id UUID PRIMARY KEY);
        CREATE TABLE ops.publication_receipt (id UUID PRIMARY KEY);
        CREATE TABLE ops.release_activation (id UUID PRIMARY KEY);
        """
    )
    initial = (
        files("propertyscope_data_store.sql")
        .joinpath("040_async_consumer_import_operations.sql")
        .read_text("utf-8")
    )
    extension = (
        files("propertyscope_data_store.sql")
        .joinpath("041_consumer_import_activation_monitoring.sql")
        .read_text("utf-8")
    )
    connection.execute(initial)
    connection.execute(extension)
    connection.execute("INSERT INTO ops.dataset_release VALUES (%s)", (release_id,))
    connection.commit()
    first = psycopg.connect(_database_url(str(connection.info.dbname)), row_factory=dict_row)
    second = psycopg.connect(_database_url(str(connection.info.dbname)), row_factory=dict_row)
    insert = """INSERT INTO ops.consumer_import_operation (
        id,dataset_release_id,dataset_id,target_feature,schema_version,content_sha256,
        record_count,manifest_json,artifact_path,expected_release_version,review_comment,
        idempotency_key,status,phase_key,attempt_number,next_attempt_at,request_id,
        requested_at,version
    ) VALUES (%s,%s,'bocsar-crime','feature-3','crime-series.v1',%s,3,'{}',%s,2,
        'Reviewed',%s,'queued','connect',1,clock_timestamp(),%s,clock_timestamp(),1)"""
    path = f"/api/data-platform/v1/dataset-releases/{release_id}/artifact"
    first.execute(insert, (uuid.uuid4(), release_id, "a" * 64, path, "delivery-one", "request-one"))
    started = threading.Event()
    errors_seen: list[type[BaseException]] = []

    def competing_insert() -> None:
        try:
            started.set()
            second.execute(
                insert,
                (uuid.uuid4(), release_id, "a" * 64, path, "delivery-two", "request-two"),
            )
            second.commit()
        except Exception as exc:
            second.rollback()
            errors_seen.append(type(exc))

    worker = threading.Thread(target=competing_insert)
    try:
        worker.start()
        assert started.wait(timeout=1)
        time.sleep(0.1)
        assert worker.is_alive()
        first.commit()
        worker.join(timeout=2)
        assert errors_seen == [psycopg.errors.UniqueViolation]
    finally:
        first.rollback()
        second.rollback()
        first.close()
        second.close()


def test_consumer_operation_identity_cannot_cross_release_boundaries(
    isolated_postgres: psycopg.Connection[dict[str, object]],
) -> None:
    connection = isolated_postgres
    first_release_id = uuid.uuid4()
    second_release_id = uuid.uuid4()
    connection.execute(
        """
        CREATE SCHEMA ops;
        CREATE TABLE ops.dataset_release (id UUID PRIMARY KEY);
        CREATE TABLE ops.publication_receipt (id UUID PRIMARY KEY);
        CREATE TABLE ops.release_activation (id UUID PRIMARY KEY);
        """
    )
    initial = (
        files("propertyscope_data_store.sql")
        .joinpath("040_async_consumer_import_operations.sql")
        .read_text("utf-8")
    )
    extension = (
        files("propertyscope_data_store.sql")
        .joinpath("041_consumer_import_activation_monitoring.sql")
        .read_text("utf-8")
    )
    connection.execute(initial)
    connection.execute(extension)
    connection.execute(
        "INSERT INTO ops.dataset_release VALUES (%s),(%s)",
        (first_release_id, second_release_id),
    )
    insert = """INSERT INTO ops.consumer_import_operation (
        id,dataset_release_id,dataset_id,target_feature,schema_version,content_sha256,
        record_count,manifest_json,artifact_path,expected_release_version,review_comment,
        idempotency_key,consumer_operation_id,status,phase_key,attempt_number,next_attempt_at,
        request_id,requested_at,version
    ) VALUES (%s,%s,'bocsar-crime','feature-3','crime-series.v1',%s,3,'{}',%s,2,
        'Reviewed',%s,'consumer-owned-42','polling','poll',1,clock_timestamp(),%s,
        clock_timestamp(),1)"""
    connection.execute(
        insert,
        (
            uuid.uuid4(),
            first_release_id,
            "a" * 64,
            f"/api/data-platform/v1/dataset-releases/{first_release_id}/artifact",
            "delivery-one",
            "request-one",
        ),
    )

    with pytest.raises(psycopg.errors.UniqueViolation):
        connection.execute(
            insert,
            (
                uuid.uuid4(),
                second_release_id,
                "b" * 64,
                f"/api/data-platform/v1/dataset-releases/{second_release_id}/artifact",
                "delivery-two",
                "request-two",
            ),
        )
    connection.rollback()


def test_durable_consumer_import_progresses_and_retries_activation_without_redownload(
    isolated_postgres: psycopg.Connection[dict[str, object]],
) -> None:
    connection = isolated_postgres
    release_id = uuid.uuid4()
    second_release_id = uuid.uuid4()
    receipt_id = uuid.uuid4()
    first_activation_id = uuid.uuid4()
    second_activation_id = uuid.uuid4()
    digest = "c" * 64
    connection.execute(
        """
        CREATE SCHEMA ops;
        CREATE TABLE ops.dataset_release (
            id UUID PRIMARY KEY,dataset_id TEXT NOT NULL,target_feature TEXT NOT NULL,
            schema_version TEXT NOT NULL,content_sha256 TEXT NOT NULL,record_count BIGINT NOT NULL,
            manifest_json JSONB NOT NULL,status TEXT NOT NULL,version INTEGER NOT NULL
        );
        CREATE TABLE ops.publication_receipt (
            id UUID PRIMARY KEY,dataset_release_id UUID NOT NULL,target_feature TEXT NOT NULL,
            consumer_operation_id TEXT NOT NULL,status TEXT NOT NULL,schema_version TEXT NOT NULL,
            content_sha256 TEXT NOT NULL,rows_received BIGINT NOT NULL,
            rows_accepted BIGINT NOT NULL,
            rows_rejected BIGINT NOT NULL,completed_at TIMESTAMPTZ NOT NULL,error_json JSONB
        );
        CREATE TABLE ops.release_activation (
            id UUID PRIMARY KEY,dataset_release_id UUID NOT NULL,
            publication_receipt_id UUID NOT NULL,
            expected_release_version INTEGER NOT NULL,status TEXT NOT NULL,error_json JSONB
        );
        """
    )
    for migration_name in (
        "040_async_consumer_import_operations.sql",
        "041_consumer_import_activation_monitoring.sql",
        "042_consumer_import_delivery_aliases.sql",
        "051_independent_producer_publication.sql",
    ):
        connection.execute(
            files("propertyscope_data_store.sql").joinpath(migration_name).read_text("utf-8")
        )
    release_row = (
        release_id,
        "bocsar-crime",
        "feature-3",
        "crime-series.v1",
        digest,
        3,
        Jsonb({"target_feature": "feature-3"}),
        "awaiting_review",
        2,
    )
    connection.execute(
        "INSERT INTO ops.dataset_release VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", release_row
    )
    connection.execute(
        "INSERT INTO ops.dataset_release VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (second_release_id, *release_row[1:]),
    )
    connection.commit()

    class Owner:
        @contextmanager
        def connection(self) -> Iterator[psycopg.Connection[dict[str, object]]]:
            yield connection

        def _fetch_one(self, query: str, params: object) -> dict[str, object] | None:
            return connection.execute(query, cast(Any, params)).fetchone()

        def _required(self, query: str, params: object) -> dict[str, object]:
            row = self._fetch_one(query, params)
            if row is None:
                raise NotFoundError("row missing")
            return row

    operations = _ConsumerImportOperations(cast(Any, Owner()))
    artifact_path = f"/api/data-platform/v1/dataset-releases/{release_id}/artifact"
    values = {
        "dataset_id": "bocsar-crime",
        "target_feature": "feature-3",
        "schema_version": "crime-series.v1",
        "content_sha256": digest,
        "record_count": 3,
        "artifact_path": artifact_path,
        "expected_release_version": 2,
        "comment": "Reviewed",
        "idempotency_key": "delivery-one",
        "request_id": "request-one",
    }
    operation, created = operations.create(release_id, values)
    assert created is True and operation["status"] == "queued"
    operation_id = uuid.UUID(str(operation["id"]))
    claimed = operations.claim(worker_id="runner-one", lease_seconds=30)
    assert claimed is not None
    acknowledged = operations.acknowledge(
        operation_id,
        worker_id="runner-one",
        lease_token=str(claimed["lease_token"]),
        consumer_operation_id="consumer-owned-42",
        remote_status="accepted",
        result={
            "consumer_operation_id": "consumer-owned-42",
            "status": "accepted",
            "schema_version": "crime-series.v1",
            "content_sha256": digest,
            "rows_received": 3,
            "rows_accepted": 3,
            "rows_rejected": 0,
            "error": None,
        },
        poll_seconds=1,
    )
    assert acknowledged["phase_key"] == "record_receipt"

    # A fresh repository instance resumes from the committed acknowledgement after a crash.
    operations = _ConsumerImportOperations(cast(Any, Owner()))
    claimed = operations.claim(worker_id="runner-two", lease_seconds=30)
    assert claimed is not None and claimed["phase_key"] == "record_receipt"
    connection.execute(
        """INSERT INTO ops.publication_receipt VALUES
        (%s,%s,'feature-3','consumer-owned-42','accepted','crime-series.v1',%s,3,3,0,now(),NULL)""",
        (receipt_id, release_id, digest),
    )
    connection.commit()
    linked = operations.attach_receipt(
        operation_id,
        worker_id="runner-two",
        lease_token=str(claimed["lease_token"]),
        receipt_id=receipt_id,
        receipt_status="accepted",
    )
    assert linked["phase_key"] == "queue_activation"
    claimed = operations.claim(worker_id="runner-three", lease_seconds=30)
    assert claimed is not None
    connection.execute(
        "INSERT INTO ops.release_activation VALUES (%s,%s,%s,2,'queued',NULL)",
        (first_activation_id, release_id, receipt_id),
    )
    connection.commit()
    operations.attach_activation(
        operation_id,
        worker_id="runner-three",
        lease_token=str(claimed["lease_token"]),
        activation_id=first_activation_id,
    )
    connection.execute(
        "UPDATE ops.consumer_import_operation SET next_attempt_at=clock_timestamp() WHERE id=%s",
        (operation_id,),
    )
    connection.execute(
        "UPDATE ops.release_activation SET status='failed',error_json=%s WHERE id=%s",
        (Jsonb({"code": "pointer_retry_required"}), first_activation_id),
    )
    connection.commit()
    claimed = operations.claim(worker_id="runner-four", lease_seconds=30)
    assert claimed is not None
    failed = operations.record_activation_outcome(
        operation_id,
        worker_id="runner-four",
        lease_token=str(claimed["lease_token"]),
        activation_status="failed",
        error={"code": "pointer_retry_required", "message": "Retry pointer activation"},
        poll_seconds=1,
    )
    assert failed["status"] == "failed"

    connection.execute("UPDATE ops.dataset_release SET version=3 WHERE id=%s", (release_id,))
    connection.commit()
    retry_values = {
        **values,
        "expected_release_version": 3,
        "comment": "Approved after version-conflict reconciliation",
        "idempotency_key": "delivery-two",
        "request_id": "request-two-version-three",
    }
    retried, created = operations.create(
        release_id,
        retry_values,
    )
    assert created is False
    assert retried["id"] == operation["id"]
    assert retried["phase_key"] == "queue_activation"
    assert retried["activation_attempt"] == 2
    durable_retry = connection.execute(
        """SELECT expected_release_version,review_comment,request_id
        FROM ops.consumer_import_operation WHERE id=%s""",
        (operation_id,),
    ).fetchone()
    assert durable_retry == {
        "expected_release_version": 3,
        "review_comment": "Approved after version-conflict reconciliation",
        "request_id": "request-two-version-three",
    }
    alias_count = connection.execute(
        "SELECT count(*) AS count FROM ops.consumer_import_delivery_alias"
    ).fetchone()
    assert alias_count is not None and alias_count["count"] == 2

    claimed = operations.claim(worker_id="runner-five", lease_seconds=30)
    assert claimed is not None
    connection.execute(
        "INSERT INTO ops.release_activation VALUES (%s,%s,%s,3,'interrupted',NULL)",
        (second_activation_id, release_id, receipt_id),
    )
    connection.commit()
    operations.attach_activation(
        operation_id,
        worker_id="runner-five",
        lease_token=str(claimed["lease_token"]),
        activation_id=second_activation_id,
    )
    connection.execute(
        "UPDATE ops.consumer_import_operation SET next_attempt_at=clock_timestamp() WHERE id=%s",
        (operation_id,),
    )
    connection.commit()
    claimed = operations.claim(worker_id="runner-six", lease_seconds=30)
    assert claimed is not None
    interrupted = operations.record_activation_outcome(
        operation_id,
        worker_id="runner-six",
        lease_token=str(claimed["lease_token"]),
        activation_status="interrupted",
        error={"code": "activation_interrupted", "retryable": True},
        poll_seconds=0,
    )
    assert interrupted["status"] == "activation_queued"
    assert interrupted["phase_key"] == "wait_activation"
    assert interrupted["activation_attempt"] == 2
    assert interrupted["attempt_number"] == 1
    assert interrupted["lease_owner"] is None
    assert interrupted["lease_token"] is None

    connection.execute(
        "UPDATE ops.release_activation SET status='succeeded' WHERE id=%s",
        (second_activation_id,),
    )
    connection.commit()
    claimed = operations.claim(worker_id="runner-seven", lease_seconds=30)
    assert claimed is not None
    published = operations.record_activation_outcome(
        operation_id,
        worker_id="runner-seven",
        lease_token=str(claimed["lease_token"]),
        activation_status="succeeded",
        error=None,
        poll_seconds=1,
    )
    assert published["status"] == "published"

    with pytest.raises(ConflictError, match="idempotency key arguments do not match"):
        operations.create(
            second_release_id,
            {
                **values,
                "artifact_path": (
                    f"/api/data-platform/v1/dataset-releases/{second_release_id}/artifact"
                ),
            },
        )

    bounded_values = {
        **values,
        "artifact_path": (f"/api/data-platform/v1/dataset-releases/{second_release_id}/artifact"),
        "idempotency_key": "bounded-retry-delivery",
        "request_id": "bounded-retry-request",
    }
    bounded, created = operations.create(second_release_id, bounded_values)
    assert created is True
    bounded_id = uuid.UUID(str(bounded["id"]))
    claimed = operations.claim(worker_id="retry-runner-four", lease_seconds=30)
    assert claimed is not None and claimed["id"] == bounded["id"]
    connection.execute(
        "UPDATE ops.consumer_import_operation SET attempt_number=4 WHERE id=%s",
        (bounded_id,),
    )
    connection.commit()
    scheduled = operations.retry(
        bounded_id,
        worker_id="retry-runner-four",
        lease_token=str(claimed["lease_token"]),
        error={"code": "consumer_unavailable", "retryable": True},
        retry_seconds=0,
    )
    assert scheduled["status"] == "interrupted"
    assert scheduled["attempt_number"] == 5

    claimed = operations.claim(worker_id="retry-runner-five", lease_seconds=30)
    assert claimed is not None and claimed["id"] == bounded["id"]
    terminal = operations.retry(
        bounded_id,
        worker_id="retry-runner-five",
        lease_token=str(claimed["lease_token"]),
        error={"code": "consumer_still_unavailable", "retryable": True},
        retry_seconds=0,
    )
    assert terminal["status"] == "failed"
    assert terminal["phase_key"] == "complete"
    assert terminal["attempt_number"] == 5

    # A closed failed remote receipt permits a new delivery, while the original
    # idempotency key and receipt remain immutable historical evidence.
    failed_receipt_id = uuid.uuid4()
    connection.execute(
        """INSERT INTO ops.publication_receipt VALUES
        (%s,%s,'feature-3','failed-remote','failed','crime-series.v1',%s,1,0,0,
         clock_timestamp(),'{"code":"artifact_transport_failed","retryable":true}')""",
        (failed_receipt_id, second_release_id, digest),
    )
    connection.execute(
        """UPDATE ops.consumer_import_operation SET consumer_operation_id='failed-remote',
        publication_receipt_id=%s WHERE id=%s""",
        (failed_receipt_id, bounded_id),
    )
    connection.commit()
    replay, created = operations.create(second_release_id, bounded_values)
    assert not created and str(replay["id"]) == bounded["id"] and replay["status"] == "failed"
    fresh_values = {**bounded_values, "idempotency_key": "fresh-after-failed-receipt"}
    fresh, created = operations.create(second_release_id, fresh_values)
    assert created and fresh["id"] != bounded["id"] and fresh["phase_key"] == "connect"
    assert str(operations.get(bounded_id)["publication_receipt_id"]) == str(failed_receipt_id)
    coalesced, created = operations.create(
        second_release_id, {**fresh_values, "idempotency_key": "another-browser-retry"}
    )
    assert not created and coalesced["id"] == fresh["id"]


def test_unusable_psi_address_number_does_not_abort_or_move_accepted_pointer(
    isolated_postgres: psycopg.Connection[dict[str, object]],
) -> None:
    connection = isolated_postgres
    predecessor = uuid.uuid4()
    connection.execute("INSERT INTO serving.accepted_generation VALUES ('psi',%s)", (predecessor,))
    connection.commit()
    valid = _psi_row(key="valid")
    invalid_address = _psi_row(
        key="invalid-address",
        street_number_first=6_711_011_622,
        house_number="6711011622",
    )

    validated = list(
        iter_ndjson_import(
            (json.dumps(item).encode() + b"\n" for item in (valid, invalid_address)),
            profile="psi-sales",
        )
    )
    assert validated[1]["house_number"] == "6711011622"
    assert validated[1]["street_number_first"] is None
    _stage_typed_psi_rows(connection, validated)

    staged = connection.execute(
        "SELECT count(*) AS count FROM propertyscope_psi_import_stage"
    ).fetchone()
    assert staged is not None and staged["count"] == 2
    connection.rollback()

    count = connection.execute("SELECT count(*) AS count FROM warehouse.psi_sale").fetchone()
    assert count is not None and count["count"] == 0
    assert _accepted_pointer(connection) == predecessor
    temporary = connection.execute(
        "SELECT to_regclass('pg_temp.propertyscope_import_stage') AS relation"
    ).fetchone()
    assert temporary is not None and temporary["relation"] is None


def test_address_resolution_does_not_leak_from_eligible_to_ineligible_row(
    isolated_postgres: psycopg.Connection[dict[str, object]],
) -> None:
    connection = isolated_postgres
    property_ref = uuid.uuid4()
    connection.execute(
        "INSERT INTO registry.property (property_ref,postcode,locality,street_name,street_type,"
        "street_number_first,street_number_last,street_number_suffix,unit_number) "
        "VALUES (%s,'2000','SYDNEY','EXAMPLE','ST',10,NULL,NULL,NULL)",
        (property_ref,),
    )
    _stage_typed_psi_rows(
        connection,
        [_psi_row(key="eligible"), _psi_row(key="ineligible", house_number="LOT 10")],
    )

    accepted = import_profiles._insert_psi_rows(
        connection.cursor(),
        release_id=uuid.uuid4(),
        artifact_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        phase_rows=2,
        phase_callback=None,
    )

    rows = connection.execute(
        "SELECT source_business_key,property_ref FROM warehouse.psi_sale "
        "ORDER BY source_business_key"
    ).fetchall()
    assert accepted == 2
    assert rows == [
        {"source_business_key": "eligible", "property_ref": property_ref},
        {"source_business_key": "ineligible", "property_ref": None},
    ]


def test_psi_links_accepted_gnaf_virtual_identity_and_retains_foreign_key(
    isolated_postgres: psycopg.Connection[dict[str, object]],
) -> None:
    connection = isolated_postgres
    accepted_gnaf_release = uuid.uuid4()
    registry_ref = uuid.uuid4()
    connection.execute(
        "INSERT INTO serving.accepted_generation VALUES ('gnaf-nsw',%s)",
        (accepted_gnaf_release,),
    )
    connection.execute(
        "INSERT INTO registry.property (property_ref,postcode,locality,street_name,street_type,"
        "street_number_first,street_number_last,street_number_suffix,unit_number) "
        "VALUES (%s,'2000','SYDNEY','EXAMPLE','ST',10,NULL,NULL,NULL)",
        (registry_ref,),
    )
    connection.execute(
        "INSERT INTO warehouse.gnaf_address (dataset_release_id,gnaf_pid,property_ref,postcode,"
        "locality,street_name,street_type,street_number_first,street_number_last,"
        "street_number_suffix,unit_number,published) VALUES "
        "(%s,'unregistered-gnaf',NULL,'2000','SYDNEY','EXAMPLE','STREET',10,NULL,NULL,NULL,TRUE)",
        (accepted_gnaf_release,),
    )
    _stage_typed_psi_rows(connection, [_psi_row(key="accepted-gnaf")])
    release_id, artifact_id, run_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    accepted = import_profiles._insert_psi_rows(
        connection.cursor(),
        release_id=release_id,
        artifact_id=artifact_id,
        run_id=run_id,
        phase_rows=1,
        phase_callback=None,
    )

    row = connection.execute(
        "SELECT property_ref,match_tier,geographic_precision FROM warehouse.psi_sale"
    ).fetchone()
    assert accepted == 1
    expected_ref = uuid.UUID(hashlib.md5(b"propertyscope-gnaf:unregistered-gnaf").hexdigest())
    assert row == {
        "property_ref": expected_ref,
        "match_tier": "A",
        "geographic_precision": "exact_address",
    }
    identifier = connection.execute(
        "SELECT scheme,identifier_value,source_release_id,evidence_json "
        "FROM registry.property_identifier WHERE property_ref=%s",
        (expected_ref,),
    ).fetchone()
    assert identifier is not None
    assert identifier["scheme"] == "gnaf_pid"
    assert identifier["identifier_value"] == "unregistered-gnaf"
    assert identifier["source_release_id"] == accepted_gnaf_release
    anchor_evidence = identifier["evidence_json"]
    assert isinstance(anchor_evidence, dict)
    assert anchor_evidence["identity_anchor"] == "psi-accepted-gnaf"
    assert connection.execute("SELECT count(*) AS count FROM registry.property").fetchone() == {
        "count": 2
    }
    connection.commit()
    anchors_before = connection.execute(
        "SELECT * FROM registry.property ORDER BY property_ref"
    ).fetchall()
    _stage_typed_psi_rows(connection, [_psi_row(key="accepted-gnaf")])
    assert (
        import_profiles._insert_psi_rows(
            connection.cursor(),
            release_id=release_id,
            artifact_id=artifact_id,
            run_id=run_id,
            phase_rows=1,
            phase_callback=None,
        )
        == 1
    )
    assert (
        connection.execute("SELECT * FROM registry.property ORDER BY property_ref").fetchall()
        == anchors_before
    )
    assert connection.execute(
        "SELECT count(*) AS count FROM registry.property_identifier"
    ).fetchone() == {"count": 1}


def test_psi_anchor_and_provenance_roll_back_with_failed_sale_insert(
    isolated_postgres: psycopg.Connection[dict[str, object]],
) -> None:
    connection = isolated_postgres
    accepted_release = uuid.uuid4()
    connection.execute(
        "INSERT INTO serving.accepted_generation VALUES ('gnaf-nsw',%s)",
        (accepted_release,),
    )
    connection.execute(
        "INSERT INTO warehouse.gnaf_address (dataset_release_id,gnaf_pid,postcode,locality,"
        "street_name,street_type,street_number_first,published) "
        "VALUES (%s,'rollback-anchor','2000','SYDNEY','EXAMPLE','STREET',10,TRUE)",
        (accepted_release,),
    )
    connection.commit()
    _stage_typed_psi_rows(
        connection,
        [
            _psi_row(key="valid"),
            {**_psi_row(key="invalid-reference"), "property_ref": uuid.uuid4()},
        ],
    )
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        import_profiles._insert_psi_rows(
            connection.cursor(),
            release_id=uuid.uuid4(),
            artifact_id=uuid.uuid4(),
            run_id=uuid.uuid4(),
            phase_rows=2,
            phase_callback=None,
        )
    connection.rollback()
    for table in ("registry.property", "registry.property_identifier", "warehouse.psi_sale"):
        assert connection.execute(
            sql.SQL("SELECT count(*) AS count FROM {}").format(sql.SQL(table))
        ).fetchone() == {"count": 0}
    assert connection.execute(
        "SELECT dataset_release_id FROM serving.accepted_generation WHERE dataset_id='gnaf-nsw'"
    ).fetchone() == {"dataset_release_id": accepted_release}


def test_psi_materialises_anchors_only_for_rows_without_supplied_property_references(
    isolated_postgres: psycopg.Connection[dict[str, object]],
) -> None:
    connection = isolated_postgres
    accepted_release, supplied_ref = uuid.uuid4(), uuid.uuid4()
    connection.execute(
        "INSERT INTO serving.accepted_generation VALUES ('gnaf-nsw',%s)",
        (accepted_release,),
    )
    connection.execute("INSERT INTO registry.property (property_ref) VALUES (%s)", (supplied_ref,))
    with connection.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO warehouse.gnaf_address (dataset_release_id,gnaf_pid,postcode,"
            "locality,street_name,street_type,street_number_first,published) "
            "VALUES (%s,%s,'2000','SYDNEY','EXAMPLE','STREET',%s,TRUE)",
            [(accepted_release, "supplied-only", 10), (accepted_release, "mixed", 20)],
        )
    rows = [
        {**_psi_row(key="supplied-only"), "property_ref": supplied_ref},
        {
            **_psi_row(key="mixed-supplied", street_number_first=20, house_number="20"),
            "property_ref": supplied_ref,
        },
        _psi_row(key="mixed-unresolved", street_number_first=20, house_number="20"),
    ]
    _stage_typed_psi_rows(connection, rows)
    import_profiles._insert_psi_rows(
        connection.cursor(),
        release_id=uuid.uuid4(),
        artifact_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        phase_rows=len(rows),
        phase_callback=None,
    )
    expected_ref = uuid.UUID(hashlib.md5(b"propertyscope-gnaf:mixed").hexdigest())
    persisted = connection.execute(
        "SELECT source_business_key,property_ref FROM warehouse.psi_sale"
    ).fetchall()
    assert {row["source_business_key"]: row["property_ref"] for row in persisted} == {
        "supplied-only": supplied_ref,
        "mixed-supplied": supplied_ref,
        "mixed-unresolved": expected_ref,
    }
    assert connection.execute(
        "SELECT identifier_value FROM registry.property_identifier"
    ).fetchall() == [{"identifier_value": "mixed"}]
    assert connection.execute("SELECT count(*) AS count FROM registry.property").fetchone() == {
        "count": 2
    }


def test_psi_matches_only_unambiguous_accepted_published_gnaf_addresses(
    isolated_postgres: psycopg.Connection[dict[str, object]],
) -> None:
    connection = isolated_postgres
    accepted_release, prior_release = uuid.uuid4(), uuid.uuid4()
    connection.execute(
        "INSERT INTO serving.accepted_generation VALUES ('gnaf-nsw',%s)",
        (accepted_release,),
    )
    with connection.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO warehouse.gnaf_address (dataset_release_id,gnaf_pid,postcode,"
            "locality,street_name,street_type,street_number_first,published) "
            "VALUES (%s,%s,'2000','SYDNEY','EXAMPLE','STREET',%s,%s)",
            [
                (accepted_release, "current", 10, True),
                (accepted_release, "ambiguous-a", 20, True),
                (accepted_release, "ambiguous-b", 20, True),
                (accepted_release, "unpublished", 30, False),
                (prior_release, "superseded", 40, True),
                (accepted_release, "ineligible-number", 50, True),
            ],
        )
    registry_ref = uuid.uuid4()
    connection.execute(
        "INSERT INTO registry.property (property_ref,postcode,locality,street_name,"
        "street_type,street_number_first) VALUES (%s,'2000','SYDNEY','EXAMPLE','ST',20)",
        (registry_ref,),
    )
    rows = [
        _psi_row(key=f"sale-{number}", street_number_first=number, house_number=str(number))
        for number in (10, 20, 30, 40, 50)
    ]
    rows[-1]["house_number"] = "LOT 50"
    _stage_typed_psi_rows(connection, rows)
    import_profiles._insert_psi_rows(
        connection.cursor(),
        release_id=uuid.uuid4(),
        artifact_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        phase_rows=len(rows),
        phase_callback=None,
    )

    linked = connection.execute(
        "SELECT source_business_key FROM warehouse.psi_sale WHERE property_ref IS NOT NULL"
    ).fetchall()
    assert linked == [{"source_business_key": "sale-10"}]
    anchors = connection.execute(
        "SELECT identifier_value FROM registry.property_identifier"
    ).fetchall()
    assert anchors == [{"identifier_value": "current"}]


def test_psi_accepts_registered_street_type_equivalences_without_changing_source_facts(
    isolated_postgres: psycopg.Connection[dict[str, object]],
) -> None:
    connection = isolated_postgres
    accepted_release = uuid.uuid4()
    connection.execute(
        "INSERT INTO serving.accepted_generation VALUES ('gnaf-nsw',%s)",
        (accepted_release,),
    )
    street_types = {
        "AV": "AVENUE",
        "CL": "CLOSE",
        "CT": "COURT",
        "CR": "CRESCENT",
        "DR": "DRIVE",
        "HWY": "HIGHWAY",
        "LANE": "LANE",
        "PDE": "PARADE",
        "PL": "PLACE",
        "RD": "ROAD",
        "ST": "STREET",
        "TCE": "TERRACE",
    }
    rows = []
    for number, (abbreviation, full_name) in enumerate(street_types.items(), start=10):
        connection.execute(
            "INSERT INTO warehouse.gnaf_address (dataset_release_id,gnaf_pid,postcode,"
            "locality,street_name,street_type,street_number_first,published) "
            "VALUES (%s,%s,'2000','SYDNEY','EXAMPLE',%s,%s,TRUE)",
            (accepted_release, f"gnaf-{number}", full_name, number),
        )
        rows.append(
            {
                **_psi_row(key=abbreviation, street_number_first=number, house_number=str(number)),
                "street_type": abbreviation,
            }
        )
    _stage_typed_psi_rows(connection, rows)
    import_profiles._insert_psi_rows(
        connection.cursor(),
        release_id=uuid.uuid4(),
        artifact_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        phase_rows=len(rows),
        phase_callback=None,
    )
    persisted = connection.execute(
        "SELECT source_business_key,street_type FROM warehouse.psi_sale "
        "WHERE property_ref IS NOT NULL"
    ).fetchall()
    assert {row["source_business_key"]: row["street_type"] for row in persisted} == {
        abbreviation: abbreviation for abbreviation in street_types
    }


def test_psi_cached_match_repairs_type_and_spacing_without_crossing_property_components(
    isolated_postgres: psycopg.Connection[dict[str, object]],
) -> None:
    connection = isolated_postgres
    accepted = uuid.uuid4()
    connection.execute(
        "INSERT INTO serving.accepted_generation VALUES ('gnaf-nsw',%s)", (accepted,)
    )
    for pid, number, last, suffix, unit in [
        ("plain", 10, None, None, None),
        ("suffix", 10, None, "A", None),
        ("range", 20, 24, None, None),
        ("unit", 30, None, None, "2"),
        ("duplicate-a", 40, None, None, None),
        ("duplicate-b", 40, None, None, None),
    ]:
        connection.execute(
            "INSERT INTO warehouse.gnaf_address (dataset_release_id,gnaf_pid,postcode,"
            "locality,street_name,street_type,street_number_first,street_number_last,"
            "street_number_suffix,unit_number,published) "
            "VALUES (%s,%s,'2000','SYDNEY','EXAMPLE','CIRCUIT',%s,%s,%s,%s,true)",
            (accepted, pid, number, last, suffix, unit),
        )
    cases = [
        ("plain", "10", 10, None, None, "plain"),
        ("suffix", "10 A", 10, None, None, "suffix"),
        ("range", "20 - 24", 20, 24, None, "range"),
        ("unit", "30", 30, None, "2", "unit"),
        ("ambiguous", "40", 40, None, None, None),
        ("lot", "LOT 10", 10, None, None, None),
        ("digit-gap", "1 0", 10, None, None, None),
        ("last-suffix", "20-24A", 20, 24, None, None),
        ("no-unit", "30", 30, None, None, None),
        ("wrong-range", "20-22", 20, 22, None, None),
        ("wrong-first", "10", 11, None, None, None),
        ("wrong-last-component", "20-24", 20, 22, None, None),
    ]
    rows = [
        {
            **_psi_row(key=key, house_number=house, street_number_first=first),
            "street_number_last": last,
            "unit_number": unit,
            "street_name": "EXAMPLE CCT",
            "street_name_normalised": "EXAMPLE CCT",
            "street_type": None,
        }
        for key, house, first, last, unit, _expected in cases
    ]
    _stage_typed_psi_rows(connection, rows)
    import_profiles._insert_psi_rows(
        connection.cursor(),
        release_id=uuid.uuid4(),
        artifact_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        phase_rows=len(rows),
        phase_callback=None,
    )
    persisted = connection.execute(
        "SELECT source_business_key,property_ref,house_number,street_type,source_row_sha256 "
        "FROM warehouse.psi_sale"
    ).fetchall()
    expected_refs = {
        key: uuid.UUID(hashlib.md5(f"propertyscope-gnaf:{pid}".encode()).hexdigest())
        if pid
        else None
        for key, _house, _first, _last, _unit, pid in cases
    }
    assert {row["source_business_key"]: row["property_ref"] for row in persisted} == expected_refs
    assert all(row["street_type"] is None for row in persisted)
    assert {row["source_business_key"]: row["house_number"] for row in persisted} == {
        row["source_business_key"]: row["house_number"] for row in rows
    }
    assert {row["source_business_key"]: row["source_row_sha256"] for row in persisted} == {
        row["source_business_key"]: row["source_row_sha256"] for row in rows
    }


def test_psi_linkage_regression_only_compares_identical_accepted_source_revisions(
    isolated_postgres: psycopg.Connection[dict[str, object]],
) -> None:
    from propertyscope_data_store.psi_matching import PSI_LINKAGE_COUNTS_SQL

    connection = isolated_postgres
    first_ref, other_ref, previous, candidate = [uuid.uuid4() for _ in range(4)]
    connection.execute(
        "INSERT INTO registry.property(property_ref) VALUES (%s),(%s)", (first_ref, other_ref)
    )
    keys = ["same", "lost", "changed", "different-hash", "different-revision"]
    for release in (previous, candidate):
        rows = [{**_psi_row(key=key), "property_ref": first_ref} for key in keys]
        _stage_typed_psi_rows(connection, rows)
        import_profiles._insert_psi_rows(
            connection.cursor(),
            release_id=release,
            artifact_id=uuid.uuid4(),
            run_id=uuid.uuid4(),
            phase_rows=len(rows),
            phase_callback=None,
        )
        connection.commit()
    connection.execute(
        "INSERT INTO serving.accepted_generation VALUES ('nsw-psi-sales',%s)", (previous,)
    )
    connection.execute(
        "UPDATE warehouse.psi_sale SET property_ref=NULL WHERE dataset_release_id=%s "
        "AND source_business_key IN ('lost','different-hash','different-revision')",
        (candidate,),
    )
    connection.execute(
        "UPDATE warehouse.psi_sale SET property_ref=%s WHERE dataset_release_id=%s "
        "AND source_business_key='changed'",
        (other_ref, candidate),
    )
    connection.execute(
        "UPDATE warehouse.psi_sale SET source_row_sha256=%s WHERE dataset_release_id=%s "
        "AND source_business_key='different-hash'",
        ("1" * 64, candidate),
    )
    connection.execute(
        "UPDATE warehouse.psi_sale SET source_revision=2 WHERE dataset_release_id=%s "
        "AND source_business_key='different-revision'",
        (candidate,),
    )
    assert connection.execute(PSI_LINKAGE_COUNTS_SQL, (candidate,)).fetchone() == {
        "count": 2,
        "previously_linked": 3,
        "lost_links": 1,
        "changed_links": 1,
    }


def test_psi_batch_match_keeps_alias_ambiguity_and_full_name_direction(
    isolated_postgres: psycopg.Connection[dict[str, object]],
) -> None:
    connection = isolated_postgres
    accepted_release = uuid.uuid4()
    connection.execute(
        "INSERT INTO serving.accepted_generation VALUES ('gnaf-nsw',%s)",
        (accepted_release,),
    )
    connection.execute(
        "INSERT INTO warehouse.gnaf_address (dataset_release_id,gnaf_pid,postcode,"
        "locality,street_name,street_type,street_number_first,published) VALUES "
        "(%s,'full','2000','SYDNEY','EXAMPLE','STREET',10,TRUE),"
        "(%s,'short','2000','SYDNEY','EXAMPLE','ST',10,TRUE)",
        (accepted_release, accepted_release),
    )
    # An abbreviation accepts either spelling, making this address ambiguous.
    # The full spelling only accepts itself, as in the original matching policy.
    _stage_typed_psi_rows(
        connection,
        [_psi_row(key="short"), {**_psi_row(key="full"), "street_type": "STREET"}],
    )
    import_profiles._insert_psi_rows(
        connection.cursor(),
        release_id=uuid.uuid4(),
        artifact_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        phase_rows=2,
        phase_callback=None,
    )
    expected_ref = uuid.UUID(hashlib.md5(b"propertyscope-gnaf:full").hexdigest())
    rows = connection.execute(
        "SELECT source_business_key,property_ref FROM warehouse.psi_sale "
        "ORDER BY source_business_key"
    ).fetchall()
    assert rows == [
        {"source_business_key": "full", "property_ref": expected_ref},
        {"source_business_key": "short", "property_ref": None},
    ]


def test_psi_does_not_reuse_stale_gnaf_anchor_after_accepted_generation_changes(
    isolated_postgres: psycopg.Connection[dict[str, object]],
) -> None:
    connection = isolated_postgres
    old_release, new_release = uuid.uuid4(), uuid.uuid4()
    connection.execute(
        "INSERT INTO serving.accepted_generation VALUES ('gnaf-nsw',%s)",
        (old_release,),
    )
    connection.execute(
        "INSERT INTO warehouse.gnaf_address (dataset_release_id,gnaf_pid,postcode,locality,"
        "street_name,street_type,street_number_first,published) "
        "VALUES (%s,'withdrawn','2000','SYDNEY','EXAMPLE','ST',10,TRUE)",
        (old_release,),
    )
    _stage_typed_psi_rows(connection, [_psi_row(key="first-import")])
    import_profiles._insert_psi_rows(
        connection.cursor(),
        release_id=uuid.uuid4(),
        artifact_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        phase_rows=1,
        phase_callback=None,
    )
    connection.commit()
    connection.execute(
        "UPDATE serving.accepted_generation SET dataset_release_id=%s WHERE dataset_id='gnaf-nsw'",
        (new_release,),
    )
    _stage_typed_psi_rows(connection, [_psi_row(key="second-import")])
    import_profiles._insert_psi_rows(
        connection.cursor(),
        release_id=uuid.uuid4(),
        artifact_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        phase_rows=1,
        phase_callback=None,
    )
    row = connection.execute(
        "SELECT property_ref FROM warehouse.psi_sale WHERE source_business_key='second-import'"
    ).fetchone()
    assert row == {"property_ref": None}
    assert connection.execute("SELECT count(*) AS count FROM registry.property").fetchone() == {
        "count": 1
    }


def test_psi_retransmissions_revisions_and_exact_address_cardinality(
    isolated_postgres: psycopg.Connection[dict[str, object]],
) -> None:
    connection = isolated_postgres
    single_ref, ambiguous_a, ambiguous_b, supplied_ref = (
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
    )
    with connection.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO registry.property (property_ref,postcode,locality,street_name,"
            "street_type,street_number_first,street_number_last,street_number_suffix,unit_number) "
            "VALUES (%s,%s,%s,%s,%s,%s,NULL,NULL,NULL)",
            [
                (single_ref, "2000", "SYDNEY", "EXAMPLE", "ST", 10),
                (ambiguous_a, "2000", "SYDNEY", "MULTI", "ST", 20),
                (ambiguous_b, "2000", "SYDNEY", "MULTI", "ST", 20),
                (supplied_ref, "2000", "SYDNEY", "SUPPLIED", "ST", 30),
            ],
        )
    first = {**_psi_row(key="revision"), "price_aud": 100, "source_row_sha256": "1" * 64}
    retransmission = {**first, "price_aud": 999}
    changed = {**first, "price_aud": 200, "source_row_sha256": "2" * 64}
    unmatched = {
        **_psi_row(key="unmatched"),
        "postcode": "2001",
        "source_row_sha256": "3" * 64,
    }
    unique = {**_psi_row(key="unique"), "source_row_sha256": "4" * 64}
    ambiguous = {
        **_psi_row(key="ambiguous", street_number_first=20, house_number="20"),
        "street_name": "Multi",
        "street_name_normalised": "MULTI",
        "source_row_sha256": "5" * 64,
    }
    supplied = {
        **_psi_row(key="supplied"),
        "property_ref": supplied_ref,
        "source_row_sha256": "6" * 64,
    }
    _stage_typed_psi_rows(
        connection,
        [first, retransmission, changed, unmatched, unique, ambiguous, supplied],
    )
    release_id = uuid.uuid4()

    accepted = import_profiles._insert_psi_rows(
        connection.cursor(),
        release_id=release_id,
        artifact_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        phase_rows=7,
        phase_callback=None,
    )

    rows = connection.execute(
        "SELECT source_business_key,source_revision,price_aud,property_ref "
        "FROM warehouse.psi_sale WHERE dataset_release_id=%s "
        "ORDER BY source_business_key,source_revision",
        (release_id,),
    ).fetchall()
    assert accepted == 6
    # The next worker can export immediately after commit, before autovacuum runs.
    statistics = connection.execute(
        "SELECT most_common_freqs FROM pg_stats WHERE schemaname='warehouse' "
        "AND tablename='psi_sale' AND attname='dataset_release_id'"
    ).fetchone()
    assert statistics is not None
    assert statistics["most_common_freqs"] == [1.0]
    assert [row for row in rows if row["source_business_key"] == "revision"] == [
        {
            "source_business_key": "revision",
            "source_revision": 1,
            "price_aud": 100,
            "property_ref": single_ref,
        },
        {
            "source_business_key": "revision",
            "source_revision": 2,
            "price_aud": 200,
            "property_ref": single_ref,
        },
    ]
    refs = {str(row["source_business_key"]): row["property_ref"] for row in rows}
    assert refs["unmatched"] is None
    assert refs["unique"] == single_ref
    assert refs["ambiguous"] is None
    assert refs["supplied"] == supplied_ref


def test_bocsar_earliest_duplicate_zero_missing_coverage_and_replay_semantics(
    isolated_postgres: psycopg.Connection[dict[str, object]],
) -> None:
    connection = isolated_postgres
    observation = {
        "record_kind": "observation",
        "geography_kind": "postcode",
        "geography_value": "2000",
        "source_category_key": "assault",
        "offence_label": "Assault",
        "subcategory_label": "Total",
        "month": "2026-01-01",
        "count": 5,
        "source_row_sha256": "a" * 64,
    }
    later_duplicate = {**observation, "count": 9, "source_row_sha256": "b" * 64}
    coverage = {
        "record_kind": "coverage",
        "geography_kind": "postcode",
        "geography_value": "2000",
        "source_category_key": "assault",
        "observed_months": ["2026-01-01", "2026-02-01"],
        "first_month": "2026-01-01",
        "last_month": "2026-02-01",
        "month_count": 2,
        "blank_means_observed_zero": True,
        "completeness_sha256": "c" * 64,
        "source_row_sha256": "d" * 64,
    }
    later_coverage = {
        **coverage,
        "observed_months": ["2026-01-01"],
        "last_month": "2026-01-01",
        "month_count": 1,
        "blank_means_observed_zero": False,
        "source_row_sha256": "e" * 64,
    }
    _stage_typed_bocsar_rows(connection, [observation, later_duplicate, coverage, later_coverage])
    release_id, artifact_id, run_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    accepted = import_profiles._insert_bocsar_rows(
        connection.cursor(),
        release_id=release_id,
        artifact_id=artifact_id,
        run_id=run_id,
        phase_rows=4,
        phase_callback=None,
    )

    fact = connection.execute(
        "SELECT count,source_row_sha256 FROM warehouse.bocsar_observation "
        "WHERE dataset_release_id=%s",
        (release_id,),
    ).fetchone()
    retained_coverage = connection.execute(
        "SELECT observed_months,month_count,blank_means_observed_zero,source_row_sha256 "
        "FROM warehouse.bocsar_coverage WHERE dataset_release_id=%s",
        (release_id,),
    ).fetchone()
    assert accepted == 2
    assert fact == {"count": 5, "source_row_sha256": "a" * 64}
    assert retained_coverage is not None
    observed_months = cast(list[date], retained_coverage["observed_months"])
    assert [value.isoformat() for value in observed_months] == [
        "2026-01-01",
        "2026-02-01",
    ]
    assert retained_coverage["month_count"] == 2
    assert retained_coverage["blank_means_observed_zero"] is True
    assert retained_coverage["source_row_sha256"] == "d" * 64
    # February is an observed blank and therefore zero; March is outside coverage and missing.
    semantic = connection.execute(
        "SELECT "
        "('2026-02-01'::date=ANY(observed_months) AND NOT EXISTS ("
        " SELECT 1 FROM warehouse.bocsar_observation o"
        " WHERE o.dataset_release_id=c.dataset_release_id"
        " AND o.geography_kind=c.geography_kind AND o.geography_value=c.geography_value"
        " AND o.source_category_key=c.source_category_key AND o.month='2026-02-01')) AS zero,"
        "('2026-03-01'::date<>ALL(observed_months)) AS missing "
        "FROM warehouse.bocsar_coverage c WHERE dataset_release_id=%s",
        (release_id,),
    ).fetchone()
    assert semantic == {"zero": True, "missing": True}

    replayed = import_profiles._insert_bocsar_rows(
        connection.cursor(),
        release_id=release_id,
        artifact_id=artifact_id,
        run_id=run_id,
        phase_rows=4,
        phase_callback=None,
    )
    assert replayed == 2
    counts = connection.execute(
        "SELECT (SELECT count(*) FROM warehouse.bocsar_observation) AS observations,"
        "(SELECT count(*) FROM warehouse.bocsar_coverage) AS coverage"
    ).fetchone()
    assert counts == {"observations": 1, "coverage": 1}

    export = release_export_query("bocsar-sparse", release_id, limit=500, cursor=None)
    series = connection.execute(export.select_sql, export.select_params).fetchone()
    assert series is not None
    assert series["offence_label"] == "Assault"
    assert series["subcategory_label"] == "Total"
    assert series["observations"] == [
        {"month": "2026-01-01", "count": 5, "source_row_sha256": "a" * 64}
    ]
    connection.execute("DELETE FROM warehouse.bocsar_observation")
    empty = connection.execute(export.select_sql, export.select_params).fetchone()
    assert empty is not None
    assert empty["offence_label"] is None and empty["subcategory_label"] is None
    assert empty["observations"] == []
    assert empty["observed_months"] == series["observed_months"]


@pytest.mark.parametrize(
    "cancelled_phase",
    ["identity_revision_derivation", "address_resolution", "target_materialisation"],
)
def test_each_real_psi_phase_cancels_its_exact_connection_and_rolls_back(
    isolated_postgres: psycopg.Connection[dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
    cancelled_phase: str,
) -> None:
    connection = isolated_postgres
    predecessor = uuid.uuid4()
    connection.execute("INSERT INTO serving.accepted_generation VALUES ('psi',%s)", (predecessor,))
    connection.commit()
    _stage_typed_psi_rows(connection, [_psi_row(key="one")])
    replacement: list[tuple[str, str]] = []
    for phase, statement in import_profiles._PSI_PHASE_SQL:
        if phase == cancelled_phase:
            parameters = ",%s::uuid,%s::uuid,%s::uuid" if phase == "target_materialisation" else ""
            statement = f"SELECT pg_sleep(5){parameters}"
        replacement.append((phase, statement))
    monkeypatch.setattr(import_profiles, "_PSI_PHASE_SQL", tuple(replacement))
    canceller: threading.Thread | None = None

    def phase_started(phase: str, _rows: int) -> None:
        nonlocal canceller
        if phase == cancelled_phase:

            def cancel_active_statement() -> None:
                time.sleep(0.15)
                connection.cancel()

            canceller = threading.Thread(target=cancel_active_statement, daemon=True)
            canceller.start()

    with pytest.raises(psycopg.errors.QueryCanceled):
        import_profiles._insert_psi_rows(
            connection.cursor(),
            release_id=uuid.uuid4(),
            artifact_id=uuid.uuid4(),
            run_id=uuid.uuid4(),
            phase_rows=1,
            phase_callback=phase_started,
        )
    if canceller is not None:
        canceller.join(timeout=2)
    connection.rollback()

    count = connection.execute("SELECT count(*) AS count FROM warehouse.psi_sale").fetchone()
    assert count is not None and count["count"] == 0
    assert _accepted_pointer(connection) == predecessor
    temporary = connection.execute(
        "SELECT to_regclass('pg_temp.propertyscope_psi_identity_stage') AS relation"
    ).fetchone()
    assert temporary is not None and temporary["relation"] is None


@pytest.mark.parametrize("consumer_status", ["accepted", "failed"])
def test_producer_publication_commits_outbox_atomically_and_survives_downstream_failure(
    isolated_postgres: psycopg.Connection[dict[str, object]],
    consumer_status: str,
) -> None:
    connection = isolated_postgres
    connection.execute("""
        CREATE SCHEMA ops;
        CREATE TABLE ops.dataset_release (
            id UUID PRIMARY KEY,dataset_id TEXT NOT NULL,target_feature TEXT NOT NULL,
            schema_version TEXT NOT NULL,content_sha256 TEXT NOT NULL,record_count BIGINT NOT NULL,
            manifest_json JSONB NOT NULL,status TEXT NOT NULL,version INTEGER NOT NULL,
            coverage_json JSONB,review_comment TEXT,accepted_at TIMESTAMPTZ,
            supersedes_release_id UUID,updated_at TIMESTAMPTZ
        );
        CREATE TABLE ops.publication_receipt (
            id UUID PRIMARY KEY,dataset_release_id UUID NOT NULL,target_feature TEXT NOT NULL,
            consumer_operation_id TEXT NOT NULL,status TEXT NOT NULL,schema_version TEXT NOT NULL,
            content_sha256 TEXT NOT NULL,rows_received BIGINT NOT NULL,
            rows_accepted BIGINT NOT NULL,
            rows_rejected BIGINT NOT NULL,completed_at TIMESTAMPTZ NOT NULL,error_json JSONB,
            request_id TEXT NOT NULL
        );
        ALTER TABLE serving.accepted_generation DROP CONSTRAINT accepted_generation_pkey;
        ALTER TABLE serving.accepted_generation
            ADD COLUMN target_feature TEXT NOT NULL DEFAULT 'feature-2',
            ADD COLUMN activated_at TIMESTAMPTZ,
            ADD COLUMN activated_by TEXT,
            ADD COLUMN version INTEGER NOT NULL DEFAULT 1,
            ADD PRIMARY KEY (dataset_id,target_feature);
    """)
    for name in (
        "026_async_release_activation.sql",
        "040_async_consumer_import_operations.sql",
        "041_consumer_import_activation_monitoring.sql",
        "042_consumer_import_delivery_aliases.sql",
        "051_independent_producer_publication.sql",
    ):
        connection.execute(files("propertyscope_data_store.sql").joinpath(name).read_text("utf-8"))
    release_id, receipt_id, activation_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    count, digest = 7_402_643, "a" * 64
    connection.execute(
        """INSERT INTO ops.dataset_release
        (id,dataset_id,target_feature,schema_version,content_sha256,record_count,manifest_json,
         status,version) VALUES (%s,'nsw-psi-sales','feature-2','property-sales.v3',%s,%s,'{}',
         'awaiting_review',4)""",
        (release_id, digest, count),
    )
    connection.execute(
        """INSERT INTO ops.publication_receipt VALUES
        (%s,%s,'feature-1','feature-1-local:verified','accepted','property-sales.v3',%s,
         %s,%s,0,now(),NULL,'publication-request')""",
        (receipt_id, release_id, digest, count, count),
    )
    connection.execute(
        """INSERT INTO ops.release_activation
        (id,dataset_release_id,publication_receipt_id,expected_release_version,review_comment,
         status,idempotency_key,lease_owner,lease_token,lease_expires_at,requested_at,materialized_at)
        VALUES (%s,%s,%s,4,'Reviewed full release','running','publish-key','loader','lease',
                now()+interval '5 minutes',now(),now())""",
        (activation_id, release_id, receipt_id),
    )
    # Force an outbox persistence failure to prove there is no publication-without-delivery gap.
    connection.execute("""CREATE FUNCTION ops.reject_outbox() RETURNS trigger LANGUAGE plpgsql AS
        $$ BEGIN RAISE EXCEPTION 'outbox unavailable'; END $$;
        CREATE TRIGGER reject_outbox BEFORE INSERT ON ops.consumer_import_operation
        FOR EACH ROW EXECUTE FUNCTION ops.reject_outbox();""")
    connection.commit()
    store = PropertyScopeStore(
        _database_url(connection.info.dbname), runtime_registry=cast(Any, None)
    )
    with pytest.raises(psycopg.errors.RaiseException, match="outbox unavailable"):
        store.finish_release_activation(
            activation_id, worker_id="loader", lease_token="lease", status="succeeded", error=None
        )
    assert connection.execute(
        "SELECT status FROM ops.dataset_release WHERE id=%s", (release_id,)
    ).fetchone() == {"status": "awaiting_review"}
    assert connection.execute(
        "SELECT count(*) AS n FROM serving.accepted_generation"
    ).fetchone() == {"n": 0}
    connection.execute("DROP TRIGGER reject_outbox ON ops.consumer_import_operation")
    connection.commit()
    for _ in range(2):
        result = store.finish_release_activation(
            activation_id, worker_id="loader", lease_token="lease", status="succeeded", error=None
        )
        assert result["status"] == "succeeded"
    deliveries = store.release_consumer_imports(release_id)
    assert len(deliveries) == 1
    delivery = deliveries[0]
    assert delivery["delivery_only"] is True
    assert delivery["record_count"] == count
    assert delivery["request_id"] == "publication-request"
    operation_id = uuid.UUID(str(delivery["id"]))
    claimed = store.claim_consumer_import(worker_id="runner", lease_seconds=30)
    assert claimed is not None
    accepted = count if consumer_status == "accepted" else 0
    result_json = {
        "consumer_operation_id": "genuine-consumer-id",
        "status": consumer_status,
        "schema_version": "property-sales.v3",
        "content_sha256": digest,
        "rows_received": count,
        "rows_accepted": accepted,
        "rows_rejected": count - accepted,
        "error": None if accepted else {"code": "consumer_capacity", "message": "5000 row limit"},
    }
    store.acknowledge_consumer_import(
        operation_id,
        worker_id="runner",
        lease_token=str(claimed["lease_token"]),
        consumer_operation_id="genuine-consumer-id",
        remote_status=consumer_status,
        result=result_json,
        poll_seconds=1,
    )
    downstream_receipt = uuid.uuid4()
    connection.execute(
        """INSERT INTO ops.publication_receipt VALUES
        (%s,%s,'feature-2','genuine-consumer-id',%s,'property-sales.v3',%s,%s,%s,%s,
         now(),%s,'delivery-request')""",
        (
            downstream_receipt,
            release_id,
            consumer_status,
            digest,
            count,
            accepted,
            count - accepted,
            Jsonb(result_json["error"]),
        ),
    )
    connection.commit()
    claimed = store.claim_consumer_import(worker_id="runner", lease_seconds=30)
    assert claimed is not None
    completed = store.attach_consumer_import_receipt(
        operation_id,
        worker_id="runner",
        lease_token=str(claimed["lease_token"]),
        receipt_id=downstream_receipt,
        receipt_status=consumer_status,
    )
    assert completed["status"] == ("delivered" if accepted else "failed")
    assert completed["phase_key"] == "complete" and completed["finished_at"] is not None
    assert completed["release_activation_id"] is None
    assert store.claim_consumer_import(worker_id="runner", lease_seconds=30) is None
    assert connection.execute(
        "SELECT dataset_release_id FROM serving.accepted_generation"
    ).fetchone() == {
        "dataset_release_id": release_id,
    }
    assert connection.execute(
        "SELECT status,version FROM ops.dataset_release WHERE id=%s", (release_id,)
    ).fetchone() == {"status": "accepted", "version": 5}

    retried, created = store.create_consumer_import(
        release_id,
        {
            "dataset_id": "nsw-psi-sales",
            "target_feature": "feature-2",
            "schema_version": "property-sales.v3",
            "content_sha256": digest,
            "record_count": count,
            "artifact_path": f"/api/data-platform/v1/dataset-releases/{release_id}/artifact",
            "expected_release_version": 5,
            "comment": "Retry downstream only",
            "idempotency_key": "retry-delivery-key",
            "request_id": "delivery-retry",
        },
    )
    assert retried["delivery_only"] is True
    assert retried["status"] == ("delivered" if accepted else "queued")
    assert created is not bool(accepted)
