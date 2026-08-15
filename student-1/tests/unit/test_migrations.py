from __future__ import annotations

import hashlib
from importlib.resources import files
from typing import Any, cast

import pytest

from propertyscope_data_store.migrations import MIGRATION_PACKAGE, migrate, schema_fingerprint


class ExistingMigrationConnection:
    def __init__(self, *, tampered: str | None = None) -> None:
        root = files(MIGRATION_PACKAGE)
        self.checksums = {
            resource.name: hashlib.sha256(resource.read_bytes()).hexdigest()
            for resource in root.iterdir()
            if resource.name.endswith(".sql")
        }
        if tampered:
            self.checksums[tampered] = "0" * 64
        self.current: dict[str, str] | None = None
        self.committed = False

    def execute(
        self, query: str, parameters: tuple[object, ...] | None = None
    ) -> ExistingMigrationConnection:
        if "SELECT checksum" in query:
            assert parameters is not None
            self.current = {"checksum": self.checksums[str(parameters[0])]}
        else:
            self.current = None
        return self

    def fetchone(self) -> dict[str, str] | None:
        return self.current

    def commit(self) -> None:
        self.committed = True


def test_existing_dict_row_migration_history_restarts_cleanly() -> None:
    connection = ExistingMigrationConnection()

    migrate(cast(Any, connection))

    assert connection.committed is True


def test_changed_applied_migration_is_rejected() -> None:
    first = sorted(ExistingMigrationConnection().checksums)[0]
    connection = ExistingMigrationConnection(tampered=first)

    with pytest.raises(RuntimeError, match="migration checksum changed"):
        migrate(cast(Any, connection))


class SchemaConnection:
    def __init__(self) -> None:
        self.rows: list[tuple[str, ...]] = []

    def execute(self, query: str) -> SchemaConnection:
        self.rows = (
            [("ops", "run_task", "id", "uuid", "NO", "")]
            if "information_schema.columns" in query
            else [("ops", "run_task", "run_task_pkey", "CREATE UNIQUE INDEX ...")]
        )
        return self

    def fetchall(self) -> list[tuple[str, ...]]:
        return self.rows


def test_schema_fingerprint_covers_columns_and_indexes() -> None:
    value = schema_fingerprint(cast(Any, SchemaConnection()))

    assert len(value) == 64
    assert value == schema_fingerprint(cast(Any, SchemaConnection()))


def test_accepted_release_manifest_migration_removes_candidate_only_wording() -> None:
    migration = (
        files(MIGRATION_PACKAGE).joinpath("013_accepted_release_manifest.sql").read_text("utf-8")
    )

    assert "WHERE status = 'accepted'" in migration
    assert "Bounded accepted release" in migration
    assert "Candidate evidence; not accepted product data" in migration


def test_registered_job_scope_migration_exposes_bounded_live_defaults() -> None:
    migration = (
        files(MIGRATION_PACKAGE).joinpath("014_registered_job_scopes.sql").read_text("utf-8")
    )

    assert '"geography_values":["2000","2007","2010"]' in migration
    assert '"years":[2025]' in migration
    assert '"maximum_records":50000' in migration
