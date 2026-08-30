"""Opt-in PostgreSQL proof for import rollback and exact-connection cancellation.

Set PROPERTYSCOPE_TEST_POSTGRES_URL to an administrator URL for a disposable local
PostgreSQL server.  Every test creates and drops its own database; the retained ps-dev
database must never be supplied here.
"""

from __future__ import annotations

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
from propertyscope_data_store import sql as migration_sql
from propertyscope_data_store._consumer_import_operations import _ConsumerImportOperations
from propertyscope_data_store.errors import ConflictError, NotFoundError
from propertyscope_data_store.import_profiles import ImportProfileError, iter_ndjson_import
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
            street_number_suffix TEXT, unit_number TEXT
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
            property_ref UUID, match_tier TEXT NOT NULL, match_confidence NUMERIC NOT NULL,
            geographic_precision TEXT NOT NULL, source_row_sha256 TEXT NOT NULL,
            normalisation_version TEXT NOT NULL, artifact_record_id UUID NOT NULL,
            ingestion_run_id UUID NOT NULL, created_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (dataset_release_id, source_business_key, source_revision)
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
        files(migration_sql).joinpath("040_async_consumer_import_operations.sql").read_text("utf-8")
    )
    extension = (
        files(migration_sql)
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
        files(migration_sql).joinpath("040_async_consumer_import_operations.sql").read_text("utf-8")
    )
    extension = (
        files(migration_sql)
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
            rows_rejected BIGINT NOT NULL,completed_at TIMESTAMPTZ NOT NULL
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
    ):
        connection.execute(files(migration_sql).joinpath(migration_name).read_text("utf-8"))
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
        (%s,%s,'feature-3','consumer-owned-42','accepted','crime-series.v1',%s,3,3,0,now())""",
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

    retried, created = operations.create(
        release_id,
        {**values, "idempotency_key": "delivery-two", "request_id": "request-two"},
    )
    assert created is False
    assert retried["id"] == operation["id"]
    assert retried["phase_key"] == "queue_activation"
    assert retried["activation_attempt"] == 2
    alias_count = connection.execute(
        "SELECT count(*) AS count FROM ops.consumer_import_delivery_alias"
    ).fetchone()
    assert alias_count is not None and alias_count["count"] == 2

    claimed = operations.claim(worker_id="runner-five", lease_seconds=30)
    assert claimed is not None
    connection.execute(
        "INSERT INTO ops.release_activation VALUES (%s,%s,%s,2,'succeeded',NULL)",
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
    published = operations.record_activation_outcome(
        operation_id,
        worker_id="runner-six",
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


def test_invalid_final_row_rolls_back_stage_and_preserves_predecessor(
    isolated_postgres: psycopg.Connection[dict[str, object]],
) -> None:
    connection = isolated_postgres
    predecessor = uuid.uuid4()
    connection.execute("INSERT INTO serving.accepted_generation VALUES ('psi',%s)", (predecessor,))
    connection.commit()
    valid = _psi_row(key="valid")
    invalid = _psi_row(key="invalid", street_number_first=6_711_011_622)

    with pytest.raises(ImportProfileError, match="record 2 street_number_first"):
        connection.execute(
            "CREATE TEMP TABLE propertyscope_import_stage "
            "(ordinal BIGINT PRIMARY KEY,payload JSONB NOT NULL) ON COMMIT DROP"
        )
        for ordinal, row in enumerate(
            iter_ndjson_import(
                (json.dumps(item).encode() + b"\n" for item in (valid, invalid)),
                profile="psi-sales",
            ),
            start=1,
        ):
            connection.execute(
                "INSERT INTO propertyscope_import_stage VALUES (%s,%s)",
                (ordinal, Jsonb(row)),
            )
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
        "INSERT INTO registry.property "
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
            "INSERT INTO registry.property VALUES (%s,%s,%s,%s,%s,%s,NULL,NULL,NULL)",
            [
                (single_ref, "2000", "SYDNEY", "EXAMPLE", "ST", 10),
                (ambiguous_a, "2000", "SYDNEY", "MULTI", "ST", 20),
                (ambiguous_b, "2000", "SYDNEY", "MULTI", "ST", 20),
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
