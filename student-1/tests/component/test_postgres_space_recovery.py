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

from propertyscope_data_store._import_operations import _RegisteredImportOperations

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
    connection.commit()
    connection.execute("DELETE FROM warehouse.psi_sale")
    connection.execute("DELETE FROM warehouse.unrelated")
    connection.execute("ANALYZE warehouse.psi_sale")
    connection.execute("ANALYZE warehouse.unrelated")
    connection.execute(
        """INSERT INTO ops.import_operation
        (id,import_profile_key,status,space_recovery_status,space_recovery_policy_json)
        VALUES (%s,'psi-sales','cancelled','needed',%s)""",
        (
            operation_id,
            Jsonb(
                {
                    "policy": "measure_then_target_exact_relations",
                    "relations": ["warehouse.psi_sale"],
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
    assert policy["operation"] == "vacuum_analyze_index_cleanup"
    assert [item["relation"] for item in policy["measured_before"]] == ["warehouse.psi_sale"]
    assert [item["relation"] for item in policy["measured_after"]] == ["warehouse.psi_sale"]
    assert policy["measured_after"][0]["n_dead_tup"] == 0
    maintenance = connection.execute(
        "SELECT relname,last_vacuum FROM pg_stat_user_tables "
        "WHERE schemaname='warehouse' ORDER BY relname"
    ).fetchall()
    assert maintenance == [
        {"relname": "psi_sale", "last_vacuum": maintenance[0]["last_vacuum"]},
        {"relname": "unrelated", "last_vacuum": None},
    ]
    assert maintenance[0]["last_vacuum"] is not None

    replay = _RegisteredImportOperations(cast(Any, _Owner(connection))).recover_import_space(
        operation_id
    )
    assert replay["space_recovery_status"] == "completed"
