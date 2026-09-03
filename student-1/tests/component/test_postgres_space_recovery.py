"""Opt-in PostgreSQL proof for bounded exact-relation import space recovery."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any, cast

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

import propertyscope_data_store._import_operations as import_operations
from propertyscope_data_store._import_operations import (
    _RegisteredImportOperations,
    _requires_atomic_reindex,
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
def recovery_database() -> Iterator[psycopg.Connection[dict[str, object]]]:
    database = f"propertyscope_recovery_{uuid.uuid4().hex}"
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    try:
        with psycopg.connect(_database_url(database), row_factory=dict_row) as connection:
            connection.execute(
                """CREATE SCHEMA registry;
                CREATE TABLE registry.property (id BIGINT PRIMARY KEY,padding TEXT DEFAULT '')
                    WITH (autovacuum_enabled=false);
                CREATE TABLE registry.property_identifier (
                    id BIGINT PRIMARY KEY,padding TEXT DEFAULT '')
                    WITH (autovacuum_enabled=false);"""
            )
            connection.commit()
            yield connection
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname=%s AND pid<>pg_backend_pid()",
                (database,),
            )
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))


class _Owner:
    def __init__(self, connection: psycopg.Connection[dict[str, object]]) -> None:
        self._connection = connection

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection[dict[str, object]]]:
        yield self._connection

    def get_import(self, operation_id: uuid.UUID) -> dict[str, Any]:
        row = self._connection.execute(
            "SELECT * FROM ops.import_operation WHERE id=%s", (operation_id,)
        ).fetchone()
        assert row is not None
        return dict(row)

    def _fetch_one(self, _query: str, _params: Sequence[Any]) -> dict[str, Any] | None:
        raise AssertionError("not used")

    def _required(self, _query: str, _params: Sequence[Any]) -> dict[str, Any]:
        raise AssertionError("not used")

    def import_cancel_requested(self, _operation_id: uuid.UUID) -> bool:
        return False


def test_failed_import_vacuums_only_registered_relations_and_records_measurements(
    recovery_database: psycopg.Connection[dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = recovery_database
    operation_id = uuid.uuid4()
    connection.execute(
        """
        CREATE SCHEMA ops;
        CREATE SCHEMA warehouse;
        CREATE TABLE warehouse.psi_sale (id BIGINT PRIMARY KEY,padding TEXT NOT NULL)
            WITH (autovacuum_enabled=false);
        CREATE TABLE warehouse.unrelated (id BIGINT PRIMARY KEY,padding TEXT NOT NULL)
            WITH (autovacuum_enabled=false);
        CREATE TABLE ops.import_operation (
            id UUID PRIMARY KEY,import_profile_key TEXT NOT NULL,status TEXT NOT NULL,
            space_recovery_status TEXT NOT NULL,space_recovery_policy_json JSONB NOT NULL,
            version INTEGER NOT NULL DEFAULT 1
        );
        """
    )
    connection.execute(
        "INSERT INTO warehouse.psi_sale SELECT i,repeat('x',200) FROM generate_series(1,2000) i"
    )
    connection.execute(
        "INSERT INTO warehouse.unrelated SELECT i,repeat('x',200) FROM generate_series(1,2000) i"
    )
    connection.execute(
        "INSERT INTO registry.property SELECT i,repeat('x',200) FROM generate_series(1,2000) i"
    )
    connection.execute(
        "INSERT INTO registry.property_identifier "
        "SELECT i,repeat('x',200) FROM generate_series(1,2000) i"
    )
    connection.commit()
    connection.execute("DELETE FROM warehouse.psi_sale")
    connection.execute("DELETE FROM warehouse.unrelated")
    connection.execute("DELETE FROM registry.property_identifier")
    connection.execute("DELETE FROM registry.property")
    connection.commit()
    connection.execute("SELECT pg_stat_force_next_flush()")
    connection.execute("ANALYZE warehouse.psi_sale")
    connection.execute("ANALYZE warehouse.unrelated")
    connection.execute("ANALYZE registry.property_identifier")
    connection.execute("ANALYZE registry.property")
    connection.execute(
        """INSERT INTO ops.import_operation
        (id,import_profile_key,status,space_recovery_status,space_recovery_policy_json)
        VALUES (%s,'psi-sales','cancelled','needed',%s)""",
        (
            operation_id,
            Jsonb(
                {
                    "policy": "measure_then_target_exact_relations",
                    "relations": [
                        "warehouse.psi_sale",
                        "registry.property",
                        "registry.property_identifier",
                    ],
                }
            ),
        ),
    )
    connection.commit()
    monkeypatch.setattr(import_operations, "SPACE_RECOVERY_REINDEX_MIN_DEAD_TUPLES", 1)
    monkeypatch.setattr(import_operations, "SPACE_RECOVERY_REINDEX_MIN_INDEX_BYTES", 1)

    result = _RegisteredImportOperations(cast(Any, _Owner(connection))).recover_import_space(
        operation_id
    )

    policy = result["space_recovery_policy_json"]
    assert result["space_recovery_status"] == "completed"
    assert policy["operation"] == "vacuum_and_atomic_reindex"
    expected_relations = ["warehouse.psi_sale", "registry.property", "registry.property_identifier"]
    assert policy["relations_reindexed"] == expected_relations
    assert [item["relation"] for item in policy["measured_before"]] == expected_relations
    assert [item["relation"] for item in policy["measured_after"]] == expected_relations
    assert all(item["n_dead_tup"] == 0 for item in policy["measured_after"])
    maintenance = connection.execute(
        "SELECT relname,last_vacuum FROM pg_stat_user_tables "
        "WHERE schemaname='warehouse' ORDER BY relname"
    ).fetchall()
    assert maintenance == [
        {"relname": "psi_sale", "last_vacuum": maintenance[0]["last_vacuum"]},
        {"relname": "unrelated", "last_vacuum": None},
    ]
    assert maintenance[0]["last_vacuum"] is not None
    anchor_maintenance = connection.execute(
        "SELECT last_vacuum FROM pg_stat_user_tables WHERE schemaname='registry'"
    ).fetchall()
    assert len(anchor_maintenance) == 2
    assert all(item["last_vacuum"] is not None for item in anchor_maintenance)

    replay = _RegisteredImportOperations(cast(Any, _Owner(connection))).recover_import_space(
        operation_id
    )
    assert replay["space_recovery_status"] == "completed"


def test_rolled_back_psi_identity_allocations_are_recovered_with_sale_rows(
    recovery_database: psycopg.Connection[dict[str, object]],
) -> None:
    connection = recovery_database
    operation_id = uuid.uuid4()
    connection.execute(
        """CREATE SCHEMA ops;
        CREATE SCHEMA warehouse;
        CREATE TABLE warehouse.psi_sale (id BIGINT PRIMARY KEY,padding TEXT NOT NULL)
            WITH (autovacuum_enabled=false);
        CREATE TABLE ops.import_operation (
            id UUID PRIMARY KEY,import_profile_key TEXT NOT NULL,status TEXT NOT NULL,
            space_recovery_status TEXT NOT NULL,space_recovery_policy_json JSONB NOT NULL,
            version INTEGER NOT NULL DEFAULT 1
        );"""
    )
    connection.commit()
    relations = ["warehouse.psi_sale", "registry.property", "registry.property_identifier"]
    for relation in relations:
        connection.execute(
            sql.SQL(
                "INSERT INTO {} SELECT i,repeat('x',200) FROM generate_series(1,2000) i"
            ).format(sql.Identifier(*relation.split(".")))
        )
    connection.rollback()
    connection.execute("SELECT pg_stat_force_next_flush()")
    for relation in relations:
        connection.execute(sql.SQL("ANALYZE {}").format(sql.Identifier(*relation.split("."))))
        assert connection.execute(
            sql.SQL("SELECT count(*) AS count FROM {}").format(sql.Identifier(*relation.split(".")))
        ).fetchone() == {"count": 0}
    connection.execute(
        """INSERT INTO ops.import_operation
        (id,import_profile_key,status,space_recovery_status,space_recovery_policy_json)
        VALUES (%s,'psi-sales','failed','needed',%s)""",
        (operation_id, Jsonb({"destination_may_have_been_touched": True})),
    )
    connection.commit()

    result = _RegisteredImportOperations(cast(Any, _Owner(connection))).recover_import_space(
        operation_id
    )
    policy = result["space_recovery_policy_json"]
    assert result["space_recovery_status"] == "completed"
    assert policy["relations_recovered"] == relations
    assert [item["relation"] for item in policy["measured_before"]] == relations
    assert all(item["n_dead_tup"] == 0 for item in policy["measured_after"])
    assert policy["relations_pending_reindex"] == []


def test_failed_import_with_no_dead_tuples_skips_vacuum(
    recovery_database: psycopg.Connection[dict[str, object]],
) -> None:
    connection = recovery_database
    operation_id = uuid.uuid4()
    connection.execute(
        """
        CREATE SCHEMA ops;
        CREATE SCHEMA warehouse;
        CREATE TABLE warehouse.psi_sale (id BIGINT PRIMARY KEY);
        CREATE TABLE ops.import_operation (
            id UUID PRIMARY KEY,import_profile_key TEXT NOT NULL,status TEXT NOT NULL,
            space_recovery_status TEXT NOT NULL,space_recovery_policy_json JSONB NOT NULL,
            version INTEGER NOT NULL DEFAULT 1
        );
        INSERT INTO ops.import_operation
        (id,import_profile_key,status,space_recovery_status,space_recovery_policy_json)
        VALUES ('00000000-0000-0000-0000-000000000000','psi-sales','failed','needed','{}');
        """
    )
    connection.execute(
        "UPDATE ops.import_operation SET id=%s WHERE id='00000000-0000-0000-0000-000000000000'",
        (operation_id,),
    )
    connection.execute(
        "UPDATE ops.import_operation SET space_recovery_policy_json="
        "'{\"destination_may_have_been_touched\":false}' WHERE id=%s",
        (operation_id,),
    )
    connection.commit()

    result = _RegisteredImportOperations(cast(Any, _Owner(connection))).recover_import_space(
        operation_id
    )

    policy = result["space_recovery_policy_json"]
    assert result["space_recovery_status"] == "completed"
    assert policy["operation"] == "not_required_before_target_materialisation"
    assert policy["relations_recovered"] == []
    last_vacuum = connection.execute(
        "SELECT last_vacuum FROM pg_stat_user_tables "
        "WHERE schemaname='warehouse' AND relname='psi_sale'"
    ).fetchone()
    assert last_vacuum == {"last_vacuum": None}


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        ({"n_dead_tup": 9_796_443, "n_live_tup": 10}, {"index_bytes": 1_779_228_672}, True),
        ({"n_dead_tup": 99_999, "n_live_tup": 10}, {"index_bytes": 1_779_228_672}, False),
        ({"n_dead_tup": 100_000, "n_live_tup": 1_000_000}, {"index_bytes": 1_779_228_672}, False),
        ({"n_dead_tup": 9_796_443, "n_live_tup": 10}, {"index_bytes": 16_384}, False),
    ],
)
def test_atomic_reindex_requires_measured_source_scale_bloat(
    before: dict[str, int], after: dict[str, int], expected: bool
) -> None:
    assert _requires_atomic_reindex(cast(Any, before), cast(Any, after)) is expected


def test_atomic_reindex_timeout_leaves_original_indexes_and_retries(
    recovery_database: psycopg.Connection[dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = recovery_database
    operation_id = uuid.uuid4()
    connection.execute(
        """
        CREATE SCHEMA ops;
        CREATE SCHEMA warehouse;
        CREATE TABLE warehouse.psi_sale (id BIGINT PRIMARY KEY,padding TEXT NOT NULL)
            WITH (autovacuum_enabled=false);
        CREATE TABLE ops.import_operation (
            id UUID PRIMARY KEY,import_profile_key TEXT NOT NULL,status TEXT NOT NULL,
            space_recovery_status TEXT NOT NULL,space_recovery_policy_json JSONB NOT NULL,
            version INTEGER NOT NULL DEFAULT 1
        );
        INSERT INTO warehouse.psi_sale
            SELECT i,repeat('x',200) FROM generate_series(1,2000) i;
        """
    )
    connection.commit()
    connection.execute("DELETE FROM warehouse.psi_sale")
    connection.commit()
    connection.execute("SELECT pg_stat_force_next_flush()")
    connection.execute("ANALYZE warehouse.psi_sale")
    connection.execute(
        """INSERT INTO ops.import_operation
        (id,import_profile_key,status,space_recovery_status,space_recovery_policy_json)
        VALUES (%s,'psi-sales','failed','needed',%s)""",
        (operation_id, Jsonb({"destination_may_have_been_touched": True})),
    )
    connection.commit()
    monkeypatch.setattr(import_operations, "SPACE_RECOVERY_REINDEX_MIN_DEAD_TUPLES", 1)
    monkeypatch.setattr(import_operations, "SPACE_RECOVERY_REINDEX_MIN_INDEX_BYTES", 1)
    monkeypatch.setattr(import_operations, "SPACE_RECOVERY_REINDEX_TIMEOUT_SECONDS", 0.1)

    blocker = psycopg.connect(_database_url(str(connection.info.dbname)), row_factory=dict_row)
    try:
        blocker.execute("SELECT 1 FROM warehouse.psi_sale LIMIT 1")
        with pytest.raises(psycopg.errors.QueryCanceled):
            _RegisteredImportOperations(cast(Any, _Owner(connection))).recover_import_space(
                operation_id
            )
    finally:
        blocker.rollback()
        blocker.close()

    pending = connection.execute(
        "SELECT space_recovery_status FROM ops.import_operation WHERE id=%s", (operation_id,)
    ).fetchone()
    assert pending == {"space_recovery_status": "needed"}
    indexes = connection.execute(
        """SELECT index_class.relname,index.indisvalid
        FROM pg_index index JOIN pg_class index_class ON index_class.oid=index.indexrelid
        JOIN pg_class table_class ON table_class.oid=index.indrelid
        JOIN pg_namespace namespace ON namespace.oid=table_class.relnamespace
        WHERE namespace.nspname='warehouse' AND table_class.relname='psi_sale'"""
    ).fetchall()
    assert indexes == [{"relname": "psi_sale_pkey", "indisvalid": True}]

    monkeypatch.setattr(import_operations, "SPACE_RECOVERY_REINDEX_TIMEOUT_SECONDS", 60)
    retried = _RegisteredImportOperations(cast(Any, _Owner(connection))).recover_import_space(
        operation_id
    )
    assert retried["space_recovery_status"] == "completed"
    assert retried["space_recovery_policy_json"]["operation"] == "vacuum_and_atomic_reindex"


def test_recovery_resumes_durable_reindex_evidence_after_vacuum_crash(
    recovery_database: psycopg.Connection[dict[str, object]],
) -> None:
    connection = recovery_database
    operation_id = uuid.uuid4()
    connection.execute(
        """
        CREATE SCHEMA ops;
        CREATE SCHEMA warehouse;
        CREATE TABLE warehouse.psi_sale (id BIGINT PRIMARY KEY);
        CREATE TABLE ops.import_operation (
            id UUID PRIMARY KEY,import_profile_key TEXT NOT NULL,status TEXT NOT NULL,
            space_recovery_status TEXT NOT NULL,space_recovery_policy_json JSONB NOT NULL,
            version INTEGER NOT NULL DEFAULT 1
        );
        """
    )
    connection.execute(
        """INSERT INTO ops.import_operation
        (id,import_profile_key,status,space_recovery_status,space_recovery_policy_json)
        VALUES (%s,'psi-sales','failed','needed',%s)""",
        (
            operation_id,
            Jsonb(
                {
                    "destination_may_have_been_touched": True,
                    "relations_pending_reindex": ["warehouse.psi_sale"],
                    "reindex_evidence_phase": "before_vacuum",
                }
            ),
        ),
    )
    connection.commit()

    result = _RegisteredImportOperations(cast(Any, _Owner(connection))).recover_import_space(
        operation_id
    )

    policy = result["space_recovery_policy_json"]
    assert result["space_recovery_status"] == "completed"
    assert policy["operation"] == "vacuum_and_atomic_reindex"
    assert policy["relations_reindexed"] == ["warehouse.psi_sale"]
    assert policy["relations_pending_reindex"] == []
