"""Accepted-generation visibility using an isolated, fully migrated PostgreSQL database.

Requires PROPERTYSCOPE_TEST_POSTGRES_URL for a disposable administrator server.
Never point it at the retained application database.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

from propertyscope_data_store._property_reads import _CanonicalPropertyReads
from propertyscope_data_store.errors import NotFoundError
from propertyscope_data_store.import_profiles import execute_stream_import
from propertyscope_data_store.migrations import migrate
from propertyscope_data_store.repository import PropertyScopeStore

ADMIN_URL = os.getenv("PROPERTYSCOPE_TEST_POSTGRES_URL", "").strip()
pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="requires disposable PostgreSQL test URL")


class ReadOwner:
    def __init__(self, connection: psycopg.Connection[dict[str, Any]]) -> None:
        self.connection = connection

    def _fetch_one(self, query: str, params: Sequence[Any]) -> dict[str, Any] | None:
        return self.connection.execute(query, params).fetchone()

    def _fetch_all(self, query: str, params: Sequence[Any]) -> list[dict[str, Any]]:
        return self.connection.execute(query, params).fetchall()

    def _required(self, query: str, params: Sequence[Any]) -> dict[str, Any]:
        row = self._fetch_one(query, params)
        if row is None:
            raise NotFoundError("record does not exist")
        return row


@pytest.fixture
def identity_database() -> Iterator[psycopg.Connection[dict[str, Any]]]:
    database = f"propertyscope_identity_{uuid.uuid4().hex}"
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    try:
        with psycopg.connect(
            make_conninfo(ADMIN_URL, dbname=database), row_factory=dict_row
        ) as conn:
            migrate(conn)
            yield conn
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))


def test_retryable_task_failure_does_not_wait_for_import_provenance_lock(
    identity_database: psycopg.Connection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = identity_database
    task = connection.execute("SELECT id,ingestion_run_id FROM ops.run_task LIMIT 1").fetchone()
    assert task is not None
    connection.execute(
        "CREATE TABLE warehouse.failure_probe (run_id UUID REFERENCES ops.ingestion_run(id))"
    )
    connection.execute(
        "UPDATE ops.ingestion_run SET status='staging',cancel_requested_at=NULL WHERE id=%s",
        (task["ingestion_run_id"],),
    )
    connection.execute(
        """UPDATE ops.run_task SET status='running',lease_owner='probe',lease_token='probe',
        lease_expires_at=now()+interval '2 minutes' WHERE id=%s""",
        (task["id"],),
    )
    connection.commit()
    url = make_conninfo(ADMIN_URL, dbname=str(connection.info.dbname))

    @contextmanager
    def finishing_connection() -> Iterator[psycopg.Connection[dict[str, Any]]]:
        with psycopg.connect(url, row_factory=dict_row) as finisher:
            finisher.execute("SET LOCAL statement_timeout='1s'")
            yield finisher

    store = PropertyScopeStore.__new__(PropertyScopeStore)
    monkeypatch.setattr(store, "connection", finishing_connection)
    with psycopg.connect(url) as loader:
        # Model the long COPY transaction's real FK KEY SHARE lock, while a
        # separate control connection reports a transient failure for its task.
        loader.execute(
            "INSERT INTO warehouse.failure_probe VALUES (%s)", (task["ingestion_run_id"],)
        )
        result = store.fail_task(
            task["id"],
            worker_id="probe",
            lease_token="probe",
            error={"code": "dependency_unavailable"},
            retryable=True,
        )
        assert result["status"] == "retry_wait"
        loader.rollback()
    assert connection.execute(
        "SELECT status FROM ops.ingestion_run WHERE id=%s", (task["ingestion_run_id"],)
    ).fetchone() == {"status": "interrupted"}


def test_run_activity_is_bounded_durable_and_excludes_private_fields(
    identity_database: psycopg.Connection[dict[str, Any]],
) -> None:
    conn = identity_database
    task = conn.execute("SELECT id,ingestion_run_id FROM ops.run_task LIMIT 1").fetchone()
    assert task is not None
    run_id = task["ingestion_run_id"]
    original_count = conn.execute(
        "SELECT count(*) AS count FROM ops.run_activity WHERE ingestion_run_id=%s", (run_id,)
    ).fetchone()
    assert original_count is not None
    conn.execute(
        "UPDATE ops.run_task SET heartbeat_at=now(),lease_token='private-token' WHERE id=%s",
        (task["id"],),
    )
    heartbeat_count = conn.execute(
        "SELECT count(*) AS count FROM ops.run_activity WHERE ingestion_run_id=%s", (run_id,)
    ).fetchone()
    assert heartbeat_count == original_count
    for number in range(1005):
        conn.execute(
            "UPDATE ops.run_task SET progress_rows=%s,progress_phase='COPY' WHERE id=%s",
            (number, task["id"]),
        )
    conn.execute(
        """UPDATE ops.run_task SET error_json=
        '{"code":"source_failed","message":"private-database-message"}' WHERE id=%s""",
        (task["id"],),
    )
    conn.commit()
    events = conn.execute(
        "SELECT * FROM ops.run_activity WHERE ingestion_run_id=%s ORDER BY id", (run_id,)
    ).fetchall()
    assert len(events) == 1000
    assert events[-1]["rows_processed"] == 1004
    assert events[-1]["error_code"] == "source_failed"
    assert "private-token" not in str(events)
    assert "private-database-message" not in str(events)
    assert len({event["id"] for event in events}) == 1000


def test_resuming_resets_attempt_display_and_retains_previous_activity(
    identity_database: psycopg.Connection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = identity_database
    task = conn.execute("SELECT * FROM ops.run_task LIMIT 1").fetchone()
    assert task is not None
    conn.execute(
        """UPDATE ops.ingestion_run SET status='interrupted',requested_scope_json=
        '{"profile":"full-data","all_records":true}' WHERE id=%s""",
        (task["ingestion_run_id"],),
    )
    conn.execute(
        """UPDATE ops.run_task SET status='interrupted',started_at=now(),finished_at=now(),
        progress_rows=123,progress_phase='COPY' WHERE id=%s""",
        (task["id"],),
    )
    conn.commit()

    @contextmanager
    def connected() -> Iterator[psycopg.Connection[dict[str, Any]]]:
        yield conn

    store = PropertyScopeStore.__new__(PropertyScopeStore)
    monkeypatch.setattr(store, "connection", connected)
    run = store.get_run(task["ingestion_run_id"])
    assert run["job_name"] and run["source_name"]
    notifications = store.operator_notifications()
    assert any(item["kind"] == "run" for item in notifications)
    assert any(item["kind"] == "publication" for item in notifications)
    assert len(notifications) <= 100
    assert all(
        "manifest_json" not in item and "source_snapshot_json" not in item for item in notifications
    )
    store.resume_run(task["ingestion_run_id"])
    resumed = conn.execute("SELECT * FROM ops.run_task WHERE id=%s", (task["id"],)).fetchone()
    assert resumed is not None
    assert resumed["status"] == "pending"
    assert resumed["started_at"] is None and resumed["finished_at"] is None
    assert resumed["progress_rows"] == 0
    events = store.run_activity(task["ingestion_run_id"], limit=100, offset=0)
    assert any(
        event["status"] == "interrupted" and event["rows_processed"] == 123 for event in events
    )
    assert any(event["status"] == "pending" and event["rows_processed"] == 0 for event in events)


def test_gnaf_anchor_cannot_outlive_accepted_identity(
    identity_database: psycopg.Connection[dict[str, Any]],
) -> None:
    connection = identity_database
    reads = _CanonicalPropertyReads(ReadOwner(connection))
    property_ref = uuid.UUID("a0000000-0000-0000-0000-000000000001")
    release_id = uuid.UUID("60000000-0000-0000-0000-000000000001")
    connection.execute(
        "UPDATE registry.property_identifier SET scheme='gnaf_pid' WHERE property_ref=%s",
        (property_ref,),
    )
    connection.execute(
        """UPDATE registry.property SET address_display='999 Stale Anchor Street',
        address_search='999 stale anchor street',locality='STALE LOCALITY'
        WHERE property_ref=%s""",
        (property_ref,),
    )
    connection.execute(
        """UPDATE warehouse.gnaf_address SET address_display='123 Current Lane, Sydney NSW 2000',
        locality='SYDNEY',published=true WHERE property_ref=%s""",
        (property_ref,),
    )
    assert reads.property_snapshot(property_ref)["property"]["locality"] == "SYDNEY"
    assert reads.property_seifa(property_ref)["locality"] == "SYDNEY"
    assert reads.property_map_context(property_ref)["address_display"].startswith("123 Current")
    assert reads.property_coverage(property_ref)
    assert reads.property_sale_history(property_ref, limit=10)["count"] >= 0
    assert not reads.search_properties("999 stale anchor", state="NSW", limit=25).items
    assert any(
        item["property_ref"] == property_ref
        for item in reads.search_properties("123 current lane", state="NSW", limit=25).items
    )

    # Keep the anchor's source and aliases accepted under the existing pointer. A
    # withdrawn warehouse identity must still never fall back to its stored snapshot.
    connection.execute(
        "UPDATE warehouse.gnaf_address SET published=false WHERE property_ref=%s",
        (property_ref,),
    )
    assert not reads.search_properties("11 example st", state="NSW", limit=25).items
    for read in (
        reads.property_snapshot,
        reads.property_map_context,
        reads.property_coverage,
        reads.property_seifa,
        lambda ref: reads.property_sale_history(ref, limit=10),
    ):
        with pytest.raises(NotFoundError):
            read(property_ref)
    assert reads._seifa_coverage(property_ref) is None

    # A later accepted generation can reintroduce the same stable reference with
    # changed fields; its canonical data wins over the unchanged registry anchor.
    next_release = uuid.uuid4()
    connection.execute(
        "UPDATE ops.dataset_release SET status='superseded' WHERE id=%s", (release_id,)
    )
    connection.execute(
        """INSERT INTO ops.dataset_release SELECT (jsonb_populate_record(
            NULL::ops.dataset_release,to_jsonb(release) || jsonb_build_object(
                'id',%s::text,'release_version','identity-switch-test','status','accepted'
            ))).* FROM ops.dataset_release release WHERE id=%s""",
        (next_release, release_id),
    )
    connection.execute(
        """INSERT INTO warehouse.gnaf_address SELECT (jsonb_populate_record(
            NULL::warehouse.gnaf_address,to_jsonb(address) || jsonb_build_object(
                'dataset_release_id',%s::text,'locality','PARRAMATTA',
                'address_display','456 Replacement Road, Parramatta NSW 2150','published',true
            ))).* FROM warehouse.gnaf_address address WHERE property_ref=%s""",
        (next_release, property_ref),
    )
    connection.execute(
        "UPDATE serving.accepted_generation SET dataset_release_id=%s WHERE dataset_release_id=%s",
        (next_release, release_id),
    )
    assert reads.property_snapshot(property_ref)["property"]["locality"] == "PARRAMATTA"
    assert reads.property_seifa(property_ref)["locality"] == "PARRAMATTA"
    assert not reads.search_properties("123 current lane", state="NSW", limit=25).items
    assert not reads.search_properties("999 stale anchor", state="NSW", limit=25).items


def test_non_gnaf_registry_identity_keeps_compatibility_reads(
    identity_database: psycopg.Connection[dict[str, Any]],
) -> None:
    property_ref = uuid.UUID("a0000000-0000-0000-0000-000000000011")
    identity_database.execute(
        "UPDATE registry.property_identifier SET scheme='fixture_pid' WHERE property_ref=%s",
        (property_ref,),
    )
    reads = _CanonicalPropertyReads(ReadOwner(identity_database))
    assert reads.property_snapshot(property_ref)["property"]["property_ref"] == property_ref
    assert reads.property_seifa(property_ref)["locality"] == "SYDNEY"
    assert reads.property_coverage(property_ref)
    assert reads.property_sale_history(property_ref, limit=10)["count"] >= 0
    assert any(
        item["property_ref"] == property_ref
        for item in reads.search_properties("21 example", state="NSW", limit=25).items
    )


def test_search_pages_bound_and_order_accepted_suburb_and_street_matches(
    identity_database: psycopg.Connection[dict[str, Any]],
) -> None:
    conn = identity_database
    conn.execute(
        """INSERT INTO warehouse.gnaf_address SELECT (jsonb_populate_record(
            NULL::warehouse.gnaf_address,to_jsonb(address) || jsonb_build_object(
                'gnaf_pid','API-PAGE-' || lpad(number::text,4,'0'),
                'property_ref',NULL,'locality','GLEBE','street_name','NORTH',
                'postcode',CASE WHEN number<=600 THEN '2037' ELSE '2999' END,
                'street_number_first',number,
                'address_display',number::text || ' North Street, Glebe NSW 2037',
                'published',number<=610
            ))).* FROM (SELECT * FROM warehouse.gnaf_address
                WHERE dataset_release_id='60000000-0000-0000-0000-000000000001'
                LIMIT 1) address CROSS JOIN generate_series(1,620) number"""
    )
    reads = _CanonicalPropertyReads(ReadOwner(conn))
    first = reads.search_properties("Glebe NSW 2037", state="NSW", limit=25)
    second = reads.search_properties("Glebe NSW 2037", state="NSW", limit=25, offset=25)
    repeated = reads.search_properties("Glebe NSW 2037", state="NSW", limit=25)
    assert first.total == 500 and first.total_is_lower_bound
    assert len(first.items) == len(second.items) == 25
    assert first.items == repeated.items
    assert {row["property_ref"] for row in first.items}.isdisjoint(
        row["property_ref"] for row in second.items
    )
    assert all(row["postcode"] == "2037" for row in first.items + second.items)
    assert reads.search_properties("North", state="NSW", limit=25).total_is_lower_bound
    assert reads.search_properties("137 North Street", state="NSW", limit=25).total == 1
    assert reads.search_properties("Glebe 2999", state="NSW", limit=25).total == 10
    assert not reads.search_properties("Glebe 2000", state="NSW", limit=25).items


def test_interactive_timeout_cancels_sql_and_resets_the_pooled_connection(
    identity_database: psycopg.Connection[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from propertyscope_data_store import read_budget
    from propertyscope_data_store.errors import ReadBudgetExceededError
    from propertyscope_data_store.runtime_registry import load_runtime_registry

    store = PropertyScopeStore(
        make_conninfo(ADMIN_URL, dbname=identity_database.info.dbname),
        runtime_registry=load_runtime_registry(
            Path(__file__).resolve().parents[2] / "config" / "job-profiles"
        ),
    )
    monkeypatch.setattr(read_budget, "INTERACTIVE_READ_SECONDS", 0.1)
    try:
        with (
            pytest.raises(ReadBudgetExceededError),
            read_budget.interactive_read(),
            store.connection() as connection,
        ):
            connection.execute("SELECT pg_sleep(1)")
        with store.connection() as connection:
            assert connection.execute("SHOW statement_timeout").fetchone() == {
                "statement_timeout": "0"
            }
            assert connection.execute("SELECT 1 AS usable").fetchone() == {"usable": 1}
    finally:
        store.close()


def test_bulk_provenance_migration_retains_existing_references(
    identity_database: psycopg.Connection[dict[str, Any]],
) -> None:
    conn = identity_database
    missing = conn.execute("""SELECT count(*) AS count FROM warehouse.gnaf_address fact
        WHERE NOT EXISTS (SELECT 1 FROM warehouse.import_batch batch
            WHERE (batch.dataset_release_id,batch.artifact_record_id,batch.ingestion_run_id)=
                  (fact.dataset_release_id,fact.artifact_record_id,fact.ingestion_run_id))""").fetchone()
    assert missing is not None and missing["count"] == 0
    constraints = conn.execute("""SELECT conrelid::regclass::text AS relation,
        confrelid::regclass::text AS parent FROM pg_constraint WHERE contype='f'
        AND connamespace='warehouse'::regnamespace""").fetchall()
    assert all(
        item["relation"] == "warehouse.import_batch"
        for item in constraints
        if item["parent"].startswith("ops.")
    )
    assert any(item["parent"] == "registry.property" for item in constraints)
    assert {
        item["parent"] for item in constraints if item["relation"] == "warehouse.import_batch"
    } == {"ops.dataset_release", "ops.artifact_record", "ops.ingestion_run"}


def test_bulk_import_checks_provenance_before_consuming_rows(
    identity_database: psycopg.Connection[dict[str, Any]],
) -> None:
    def forbidden_rows() -> Iterator[dict[str, Any]]:
        yield pytest.fail("invalid provenance must fail before COPY")

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        execute_stream_import(
            identity_database,
            {
                "candidate_release_id": uuid.uuid4(),
                "artifact_record_id": uuid.uuid4(),
                "ingestion_run_id": uuid.uuid4(),
            },
            profile="gnaf-nsw",
            rows=forbidden_rows(),
        )
    identity_database.rollback()


def test_bulk_rows_and_provenance_roll_back_together(
    identity_database: psycopg.Connection[dict[str, Any]],
) -> None:
    conn = identity_database
    original = conn.execute(
        "SELECT * FROM ops.dataset_release WHERE dataset_id='gnaf-nsw' LIMIT 1"
    ).fetchone()
    assert original is not None
    release_id = uuid.uuid4()
    conn.execute(
        """INSERT INTO ops.dataset_release SELECT (jsonb_populate_record(
        NULL::ops.dataset_release,to_jsonb(release) || jsonb_build_object(
            'id',%s::text,'release_version','bulk-rollback-test','status','draft'
        ))).* FROM ops.dataset_release release WHERE id=%s""",
        (release_id, original["id"]),
    )
    conn.commit()
    row = conn.execute("""SELECT *, ST_X(geom) AS longitude,ST_Y(geom) AS latitude
        FROM warehouse.gnaf_address LIMIT 1""").fetchone()
    assert row is not None
    row.update(gnaf_pid="bulk-rollback-test", source_crs=4326)
    result = execute_stream_import(
        conn,
        {
            "candidate_release_id": release_id,
            "artifact_record_id": original["artifact_record_id"],
            "ingestion_run_id": original["ingestion_run_id"],
        },
        profile="gnaf-nsw",
        rows=[row],
    )
    assert result.rows_accepted == 1
    assert (
        conn.execute(
            "SELECT 1 FROM warehouse.import_batch WHERE dataset_release_id=%s", (release_id,)
        ).fetchone()
        is not None
    )
    conn.rollback()
    for table in ("import_batch", "gnaf_address"):
        assert (
            conn.execute(
                sql.SQL("SELECT 1 FROM warehouse.{} WHERE dataset_release_id=%s").format(
                    sql.Identifier(table)
                ),
                (release_id,),
            ).fetchone()
            is None
        )
