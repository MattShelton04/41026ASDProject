"""Schema, referential-integrity, and deterministic seed tests."""

from __future__ import annotations

import sqlite3

import pytest
from propertyscope_buyer_store.migrations import seed
from propertyscope_buyer_store.repository import BuyerStore


def _rows(connection: sqlite3.Connection, table: str) -> list[tuple[object, ...]]:
    return [tuple(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY id")]


def test_seed_has_required_deterministic_counts(store: BuyerStore) -> None:
    assert store.seed_report() == {
        "tables": {
            "buyer_case": 10,
            "case_property": 12,
            "case_note": 11,
            "case_task": 12,
        },
        "minimum_required": 10,
        "minimum_satisfied": True,
    }


def test_seed_rerun_does_not_duplicate_or_modify_rows(store: BuyerStore) -> None:
    connection = store.connect()
    before = {
        table: _rows(connection, table)
        for table in ("buyer_case", "case_property", "case_note", "case_task")
    }
    seed(connection)
    seed(connection)
    after = {table: _rows(connection, table) for table in before}
    connection.close()
    assert after == before


def test_initialize_does_not_restore_a_deleted_seed_case(store: BuyerStore) -> None:
    case_id = "b5000000-0000-4000-8000-000000000001"
    assert store.delete_case("release0-demo-owner", case_id)
    store.initialize()
    assert store.get_case("release0-demo-owner", case_id) is None


def test_schema_contains_expected_indexes_triggers_and_foreign_keys(store: BuyerStore) -> None:
    connection = store.connect()
    objects = {
        (row[0], row[1])
        for row in connection.execute(
            "SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
        )
    }
    property_fks = list(connection.execute("PRAGMA foreign_key_list(case_property)"))
    note_fks = list(connection.execute("PRAGMA foreign_key_list(case_note)"))
    connection.close()
    assert ("index", "idx_buyer_case_owner_updated") in objects
    assert ("index", "idx_case_task_case_completion_due") in objects
    assert ("trigger", "trg_case_note_property_same_case_insert") in objects
    assert ("trigger", "trg_case_task_property_same_case_update") in objects
    assert any(row[2] == "buyer_case" and row[6] == "CASCADE" for row in property_fks)
    assert any(row[2] == "case_property" and row[6] == "SET NULL" for row in note_fks)


def test_every_repository_connection_enables_foreign_keys(store: BuyerStore) -> None:
    first = store.connect()
    second = store.connect()
    assert first.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert second.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    first.close()
    second.close()


def test_database_constraints_reject_invalid_values(store: BuyerStore) -> None:
    connection = store.connect()
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            UPDATE buyer_case SET status = 'draft'
            WHERE id = 'b5000000-0000-4000-8000-000000000001'
            """
        )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            UPDATE case_property SET rating = 7
            WHERE id = 'c5000000-0000-4000-8000-000000000001'
            """
        )
    connection.close()


def test_schema_fingerprint_is_stable_and_versioned(store: BuyerStore) -> None:
    first = store.schema_fingerprint()
    store.initialize()
    second = store.schema_fingerprint()
    assert first == second
    assert first["algorithm"] == "sha256"
    assert first["schema_version"] == 2
    assert len(str(first["fingerprint"])) == 64
