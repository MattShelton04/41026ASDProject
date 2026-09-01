"""Tests for migrations discovery, configuration and row serialisation helpers."""

from __future__ import annotations

import datetime as dt
import decimal
import uuid

import pytest

from propertyscope_due_diligence_store.configuration import StoreSettings
from propertyscope_due_diligence_store.migrations import iter_migrations, migrate
from propertyscope_due_diligence_store.repository import _json_safe, _row


def test_iter_migrations_is_sorted_and_complete():
    names = [name for name, _ in iter_migrations()]
    assert names == sorted(names)
    assert "001_initial.sql" in names
    assert "002_seed.sql" in names
    for _, sql in iter_migrations():
        assert sql.strip()


def test_seed_migration_declares_ten_rows_per_table():
    seed = dict(iter_migrations())["002_seed.sql"]
    assert seed.count("generate_series(1, 10)") == 3


def test_json_safe_converts_scalar_types():
    identifier = uuid.UUID("d4000000-0000-0000-0000-000000000001")
    assert _json_safe(identifier) == "d4000000-0000-0000-0000-000000000001"
    assert _json_safe(dt.date(2026, 1, 1)) == "2026-01-01"
    assert _json_safe(dt.datetime(2026, 1, 1, 12, 0)) == "2026-01-01T12:00:00"
    assert _json_safe(decimal.Decimal("0.980")) == pytest.approx(0.98)
    assert _json_safe("value") == "value"


def test_row_serialises_every_column():
    row = _row({"id": uuid.UUID(int=1), "confidence": decimal.Decimal("0.5"), "notes": "x"})
    assert isinstance(row["id"], str)
    assert row["confidence"] == pytest.approx(0.5)
    assert row["notes"] == "x"


def test_settings_from_environment(monkeypatch):
    monkeypatch.setenv("PROPERTYSCOPE_DUE_DILIGENCE_DATABASE_URL", "postgresql://db")
    monkeypatch.setenv("PROPERTYSCOPE_INTERNAL_TOKEN", "tok")
    monkeypatch.setenv("PROPERTYSCOPE_AUTO_MIGRATE", "false")
    settings = StoreSettings.from_environment()
    assert settings.database_url == "postgresql://db"
    assert settings.internal_token == "tok"
    assert settings.auto_migrate is False


def test_settings_requires_database_url(monkeypatch):
    monkeypatch.delenv("PROPERTYSCOPE_DUE_DILIGENCE_DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError):
        StoreSettings.from_environment()


class _FakeTransaction:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConnection:
    """Minimal stand-in that returns dict rows, matching the psycopg dict_row factory."""

    def __init__(self, applied_versions):
        self._applied = [{"version": version} for version in applied_versions]
        self.statements: list[str] = []

    def execute(self, sql, params=None):
        self.statements.append(sql)
        if "SELECT version FROM due_diligence.schema_migration" in sql:
            return self._applied
        return []

    def transaction(self):
        return _FakeTransaction()


def _recorded_inserts(connection):
    return sum(
        1 for sql in connection.statements if "INSERT INTO due_diligence.schema_migration" in sql
    )


def test_migrate_applies_pending_migrations_on_a_fresh_database():
    connection = _FakeConnection([])
    migrate(connection)
    assert _recorded_inserts(connection) == 2


def test_migrate_skips_already_applied_migrations_using_dict_rows():
    # Regression guard: rows come back as dicts, so version access must be by key, not
    # index. An index access (row[0]) raises KeyError once the ledger has rows.
    connection = _FakeConnection(["001_initial.sql", "002_seed.sql"])
    migrate(connection)
    assert _recorded_inserts(connection) == 0
