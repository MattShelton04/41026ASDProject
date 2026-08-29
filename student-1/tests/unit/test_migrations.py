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


def test_complete_source_acquisition_updates_bocsar_capacity() -> None:
    migration = (
        files(MIGRATION_PACKAGE).joinpath("024_complete_source_acquisition.sql").read_text("utf-8")
    )

    assert "max_bytes=2500000000" in migration
    assert "timeout_seconds=86400" in migration


def test_current_bocsar_capacity_reconciles_the_durable_job() -> None:
    migration = (
        files(MIGRATION_PACKAGE)
        .joinpath("025_bocsar_current_source_capacity.sql")
        .read_text("utf-8")
    )

    assert "max_objects=4" in migration
    assert "max_bytes=5000000000" in migration
    assert "max_rows=15000000" in migration


def test_complete_import_policy_removes_operator_limits_and_saved_scopes() -> None:
    migration = (
        files(MIGRATION_PACKAGE)
        .joinpath("026_complete_imports_without_operator_limits.sql")
        .read_text("utf-8")
    )

    assert "DROP COLUMN scope_json" in migration
    assert "DROP COLUMN max_parallelism" in migration
    assert "DROP COLUMN max_objects" in migration
    assert "DROP COLUMN max_bytes" in migration
    assert "DROP COLUMN max_rows" in migration
    assert "DROP COLUMN timeout_seconds" in migration


def test_registered_runtime_versions_are_persisted_for_future_runs() -> None:
    migration = (
        files(MIGRATION_PACKAGE)
        .joinpath("030_persist_registered_runtime_versions.sql")
        .read_text("utf-8")
    )

    assert "ADD COLUMN adapter_version" in migration
    assert "ADD COLUMN release_builder_version" in migration
    assert "release_builder_version='2.0.0'" in migration
    assert "release_builder_key='property-sales'" in migration


def test_complete_release_operations_are_observable_and_lineage_safe() -> None:
    migration = (
        files(MIGRATION_PACKAGE).joinpath("031_complete_release_operations.sql").read_text("utf-8")
    )

    assert "'abandoned'" in migration
    assert "terminal_reason_json" in migration
    assert "progress_phase" in migration
    assert "progress_rows" in migration
    assert "DROP CONSTRAINT IF EXISTS artifact_record_content_sha256_artifact_kind_key" in migration
    assert "artifact_record_run_logical_kind_idx" in migration
    assert "artifact_record_storage_reference_idx" in migration


def test_gnaf_candidate_loads_do_not_maintain_serving_indexes() -> None:
    migration = (
        files(MIGRATION_PACKAGE)
        .joinpath("032_isolate_gnaf_candidate_indexes.sql")
        .read_text("utf-8")
    )

    assert "ADD COLUMN published BOOLEAN" in migration
    assert migration.count("WHERE published") >= 6
    assert "gnaf_address_lookup_idx" in migration
    assert "gnaf_address_geom_idx" in migration


def test_release_activation_migration_prevents_duplicate_nonterminal_work() -> None:
    migration = (
        files(MIGRATION_PACKAGE).joinpath("037_coalesce_release_activations.sql").read_text("utf-8")
    )

    assert "CREATE UNIQUE INDEX release_activation_nonterminal_release_version_uq" in migration
    assert "dataset_release_id, expected_release_version" in migration
    assert "'queued','claimed','running','interrupted'" in migration


def test_durable_jobs_select_the_complete_streaming_builders() -> None:
    migration = (
        files(MIGRATION_PACKAGE)
        .joinpath("033_register_streaming_release_builder_versions.sql")
        .read_text("utf-8")
    )

    assert "WHEN 'property-snapshot' THEN '2.0.0'" in migration
    assert "WHEN 'property-sales' THEN '3.0.0'" in migration
    assert "WHEN 'crime-series' THEN '2.0.0'" in migration
    assert "WHEN 'school-points' THEN '2.0.0'" in migration


def test_terminal_task_progress_reconciles_to_exact_output() -> None:
    migration = (
        files(MIGRATION_PACKAGE)
        .joinpath("034_reconcile_terminal_task_progress.sql")
        .read_text("utf-8")
    )

    assert "SET progress_rows = rows_out" in migration
    assert "progress_total_rows = COALESCE(progress_total_rows, rows_out)" in migration
    assert "WHERE status = 'succeeded'" in migration


def test_terminal_run_summary_uses_completed_acquisition_output() -> None:
    migration = (
        files(MIGRATION_PACKAGE)
        .joinpath("035_reconcile_terminal_acquisition_counts.sql")
        .read_text("utf-8")
    )

    assert "SET rows_discovered = completed.rows_out" in migration
    assert "stage = 'acquire' AND status = 'succeeded'" in migration
    assert "run.status IN ('cancelled', 'failed', 'interrupted')" in migration


def test_cached_reprocessing_reconciles_found_to_verified_rows() -> None:
    migration = (
        files(MIGRATION_PACKAGE)
        .joinpath("036_reconcile_cached_reprocess_counts.sql")
        .read_text("utf-8")
    )

    assert "run_mode = 'reprocess_cached'" in migration
    assert "SET rows_discovered = rows_staged" in migration
