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


def test_runtime_scopes_match_declarative_profiles_and_psi_partition_scope() -> None:
    migration = (
        files(MIGRATION_PACKAGE)
        .joinpath("017_release_scope_and_psi_revisions.sql")
        .read_text("utf-8")
    )

    assert "source_partition_year" in migration
    assert '"end_month":"2025-12"' in migration
    assert '"maximum_records":2500' in migration
    assert '"maximum_records":250000' in migration


def test_public_catalogue_migration_retires_padding_and_aligns_registered_products() -> None:
    migration = (
        files(MIGRATION_PACKAGE).joinpath("018_public_catalogue_consistency.sql").read_text("utf-8")
    )

    assert "Internal assessment fixture" in migration
    assert "SET status = 'retired'" in migration
    assert "SET status = 'superseded'" in migration
    assert "DELETE FROM serving.accepted_generation" in migration
    assert "THEN 'gnaf-nsw'" in migration
    assert "THEN '[\"feature-3\"]'::jsonb" in migration


def test_assessment_padding_is_removed_without_deleting_the_repeatable_fixture() -> None:
    migration = (
        files(MIGRATION_PACKAGE).joinpath("020_remove_assessment_padding.sql").read_text("utf-8")
    )

    assert "DELETE FROM ops.source_definition" in migration
    assert "DELETE FROM ops.job_definition" in migration
    assert "DELETE FROM ops.dataset_release" in migration
    assert "000000000010" not in migration


def test_property_geometry_constraint_includes_nsw_administered_islands() -> None:
    migration = (
        files(MIGRATION_PACKAGE).joinpath("022_include_nsw_island_geometry.sql").read_text("utf-8")
    )

    assert "DROP CONSTRAINT property_geom_check" in migration
    assert "ST_X(geom) BETWEEN 140 AND 160" in migration


def test_property_search_documents_ignore_display_punctuation() -> None:
    migration = (
        files(MIGRATION_PACKAGE).joinpath("023_property_search_documents.sql").read_text("utf-8")
    )

    assert "UPDATE registry.property" in migration
    assert "UPDATE registry.address_alias" in migration
    assert "[^a-z0-9]+" in migration
