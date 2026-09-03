from __future__ import annotations

import hashlib
from importlib.resources import files
from typing import Any, cast

import pytest

from propertyscope_data_platform.release_builders import default_release_builders
from propertyscope_data_store.migrations import (
    MIGRATION_PACKAGE,
    SCHEMA_FINGERPRINT_POLICY_VERSION,
    migrate,
    schema_fingerprint,
)


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


def test_supported_contract_migrations_align_every_registered_builder() -> None:
    established_sql = (
        files(MIGRATION_PACKAGE)
        .joinpath("043_align_supported_builder_contracts.sql")
        .read_text(encoding="utf-8")
    )
    seifa_sql = (
        files(MIGRATION_PACKAGE).joinpath("048_abs_seifa_2021.sql").read_text(encoding="utf-8")
    )
    expected_versions = {
        builder.spec.key: builder.spec.version for builder in default_release_builders().values()
    }
    for builder_key, version in expected_versions.items():
        migration = seifa_sql if builder_key == "seifa-area" else established_sql
        assert f"release_builder_key = '{builder_key}'" in migration
        assert f"release_builder_version <> '{version}'" in migration
        assert version in migration
    assert "ops.ingestion_run" not in established_sql


def test_interrupted_task_migration_repairs_existing_active_children() -> None:
    sql = (
        files(MIGRATION_PACKAGE)
        .joinpath("046_reconcile_interrupted_run_tasks.sql")
        .read_text(encoding="utf-8")
    )

    assert "'interrupted','skipped'" in sql
    assert "UPDATE ops.run_task task" in sql
    assert "run.status = 'interrupted'" in sql
    assert "task.status IN ('claimed', 'running')" in sql
    assert "lease_expires_at = NULL" in sql


def test_showcase_evidence_migration_uses_registered_contracts_and_real_counts() -> None:
    sql = (
        files(MIGRATION_PACKAGE)
        .joinpath("047_realistic_showcase_evidence.sql")
        .read_text(encoding="utf-8")
    )

    for schema in (
        "propertyscope.property-snapshot.v2",
        "propertyscope.property-sales.v3",
        "propertyscope.crime-series.v2",
        "propertyscope.school-points.v2",
    ):
        assert schema in sql
    assert "propertyscope.release-manifest.v2" in sql
    assert "'media_type','application/x-ndjson'" in sql
    assert "'content_encoding','gzip'" in sql
    assert "'synthetic',true" in sql
    assert "Synthetic showcase baseline; not complete publisher coverage." in sql
    assert "'propertyscope.crime-series.v2','crime-series','3.0.0','bocsar-sparse',10" in sql
    assert (
        "'propertyscope.property-snapshot.v2','property-snapshot','3.0.0','property-fixture',3"
        in sql
    )


class SchemaConnection:
    def __init__(
        self,
        *,
        mutation: tuple[str, str, object] | None = None,
        dict_rows: bool = False,
        reverse_relation_rows: bool = False,
    ) -> None:
        self.mutation = mutation
        self.dict_rows = dict_rows
        self.reverse_relation_rows = reverse_relation_rows
        self.rows: list[dict[str, object] | tuple[object, ...]] = []
        self.queries: list[str] = []

    @staticmethod
    def _datasets() -> list[tuple[str, dict[str, object]]]:
        return [
            (
                "relation",
                {
                    "schema_name": "ops",
                    "relation_name": "run_task",
                    "relation_kind": "r",
                    "persistence": "p",
                    "is_partition": False,
                },
            ),
            ("schema", {"schema_name": "ops"}),
            (
                "column",
                {
                    "schema_name": "ops",
                    "relation_name": "run_task",
                    "ordinal_position": 1,
                    "column_name": "id",
                    "data_type": "uuid",
                    "type_schema": "pg_catalog",
                    "type_name": "uuid",
                    "domain_schema": None,
                    "domain_name": None,
                    "character_maximum_length": None,
                    "numeric_precision": None,
                    "numeric_precision_radix": None,
                    "numeric_scale": None,
                    "datetime_precision": None,
                    "interval_type": None,
                    "interval_precision": None,
                    "collation_schema": None,
                    "collation_name": None,
                    "is_nullable": "NO",
                    "column_default": "gen_random_uuid()",
                    "is_identity": "NO",
                    "identity_generation": None,
                    "identity_start": None,
                    "identity_increment": None,
                    "identity_minimum": None,
                    "identity_maximum": None,
                    "identity_cycle": "NO",
                    "is_generated": "NEVER",
                    "generation_expression": None,
                    "spatial_type": None,
                    "spatial_srid": None,
                    "spatial_dimensions": None,
                },
            ),
            (
                "index",
                {
                    "schema_name": "ops",
                    "relation_name": "run_task",
                    "index_name": "run_task_pkey",
                    "access_method": "btree",
                    "is_unique": True,
                    "is_primary": True,
                    "is_valid": True,
                    "is_ready": True,
                    "is_clustered": False,
                    "is_replica_identity": False,
                    "key_attribute_count": 1,
                    "predicate": None,
                },
            ),
            (
                "index_attribute",
                {
                    "schema_name": "ops",
                    "relation_name": "run_task",
                    "index_name": "run_task_pkey",
                    "ordinal_position": 1,
                    "is_included": False,
                    "column_name": "id",
                    "expression": None,
                    "operator_class_schema": "pg_catalog",
                    "operator_class_name": "uuid_ops",
                    "collation_schema": None,
                    "collation_name": None,
                    "is_descending": False,
                    "nulls_first": False,
                },
            ),
            (
                "constraint",
                {
                    "schema_name": "ops",
                    "relation_name": "run_task",
                    "constraint_name": "run_task_pkey",
                    "constraint_type": "p",
                    "is_deferrable": False,
                    "initially_deferred": False,
                    "is_validated": True,
                    "no_inherit": True,
                    "referenced_schema": None,
                    "referenced_relation": None,
                    "foreign_key_match_type": " ",
                    "foreign_key_update_action": " ",
                    "foreign_key_delete_action": " ",
                    "check_expression": None,
                },
            ),
            (
                "constraint_attribute",
                {
                    "schema_name": "ops",
                    "relation_name": "run_task",
                    "constraint_name": "run_task_pkey",
                    "ordinal_position": 1,
                    "column_name": "id",
                    "referenced_column_name": None,
                    "exclusion_operator_schema": None,
                    "exclusion_operator_name": None,
                },
            ),
            (
                "view",
                {
                    "schema_name": "serving",
                    "relation_name": "accepted_property",
                    "relation_kind": "v",
                    "query_expression": "SELECT id FROM registry.property",
                },
            ),
            (
                "extension",
                {
                    "extension_name": "postgis",
                    "extension_version": "3.4.0",
                    "installed_schema": "public",
                },
            ),
        ]

    def execute(self, query: str) -> SchemaConnection:
        self.queries.append(query)
        category, row = self._datasets()[len(self.queries) - 1]
        if self.mutation is not None and self.mutation[0] == category:
            row[self.mutation[1]] = self.mutation[2]
        rows = [row]
        if category == "relation":
            rows.append(
                {
                    "schema_name": "registry",
                    "relation_name": "property",
                    "relation_kind": "r",
                    "persistence": "p",
                    "is_partition": False,
                }
            )
            if self.reverse_relation_rows:
                rows.reverse()
        materialized: list[dict[str, object] | tuple[object, ...]] = (
            list(rows) if self.dict_rows else [tuple(item.values()) for item in rows]
        )
        self.rows = materialized
        return self

    def fetchall(self) -> list[dict[str, object] | tuple[object, ...]]:
        return self.rows


def test_schema_fingerprint_v2_is_deterministic_and_uses_structured_catalogues() -> None:
    connection = SchemaConnection()

    value = schema_fingerprint(cast(Any, connection))

    assert len(value) == 64
    assert value == schema_fingerprint(cast(Any, SchemaConnection()))
    assert SCHEMA_FINGERPRINT_POLICY_VERSION == "propertyscope-postgresql-schema.v2"
    assert len(connection.queries) == 9
    assert all("pg_indexes" not in query for query in connection.queries)
    assert all("pg_get_constraintdef" not in query for query in connection.queries)


def test_schema_fingerprint_canonicalises_real_dict_rows() -> None:
    tuple_value = schema_fingerprint(cast(Any, SchemaConnection()))

    assert tuple_value == schema_fingerprint(cast(Any, SchemaConnection(dict_rows=True)))


def test_schema_fingerprint_is_independent_of_catalogue_row_order() -> None:
    ordered = schema_fingerprint(cast(Any, SchemaConnection()))
    reversed_relations = schema_fingerprint(cast(Any, SchemaConnection(reverse_relation_rows=True)))

    assert ordered == reversed_relations


@pytest.mark.parametrize(
    ("category", "field", "value"),
    [
        ("schema", "schema_name", "registry"),
        ("relation", "relation_kind", "m"),
        ("column", "numeric_precision", 12),
        ("column", "numeric_scale", 2),
        ("column", "column_default", "uuid_generate_v4()"),
        ("column", "is_nullable", "YES"),
        ("column", "spatial_srid", 4283),
        ("index", "predicate", "published"),
        ("index_attribute", "operator_class_name", "uuid_minmax_ops"),
        ("constraint", "constraint_type", "f"),
        ("constraint", "check_expression", "id IS NOT NULL"),
        ("constraint_attribute", "referenced_column_name", "id"),
        ("view", "relation_kind", "m"),
        ("view", "query_expression", "SELECT id, status FROM registry.property"),
        ("extension", "extension_version", "3.5.0"),
    ],
)
def test_schema_fingerprint_changes_for_every_v2_contract_category(
    category: str, field: str, value: object
) -> None:
    baseline = schema_fingerprint(cast(Any, SchemaConnection()))
    changed = schema_fingerprint(cast(Any, SchemaConnection(mutation=(category, field, value))))

    assert baseline != changed


def test_schema_fingerprint_normalises_only_unquoted_expression_whitespace() -> None:
    compact = schema_fingerprint(
        cast(Any, SchemaConnection(mutation=("column", "column_default", "now()")))
    )
    spaced = schema_fingerprint(
        cast(Any, SchemaConnection(mutation=("column", "column_default", "  now()  ")))
    )
    quoted_single_space = schema_fingerprint(
        cast(Any, SchemaConnection(mutation=("column", "column_default", "'a b'::text")))
    )
    quoted_double_space = schema_fingerprint(
        cast(Any, SchemaConnection(mutation=("column", "column_default", "'a  b'::text")))
    )

    assert compact == spaced
    assert quoted_single_space != quoted_double_space


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


def test_truthful_loader_phases_and_bounded_recovery_are_durable() -> None:
    migration = (
        files(MIGRATION_PACKAGE).joinpath("038_truthful_loader_phases.sql").read_text("utf-8")
    )

    assert migration.count("progress_phase_key") == 3
    assert "ALTER TABLE ops.release_activation" in migration
    assert "space_recovery_status" in migration
    assert "space_recovery_policy_json" in migration
    assert "\nVACUUM" not in migration
    assert "\nREINDEX" not in migration


def test_psi_exact_address_index_matches_null_equivalent_predicates() -> None:
    migration = (
        files(MIGRATION_PACKAGE)
        .joinpath("039_match_psi_exact_address_predicate.sql")
        .read_text("utf-8")
    )

    assert "COALESCE(street_number_last,-1)" in migration
    assert "COALESCE(street_number_suffix,'')" in migration
    assert "COALESCE(unit_number,'')" in migration
    assert "INCLUDE (property_ref)" in migration


def test_gnaf_identity_guard_index_includes_historical_provenance() -> None:
    migration = (
        files(MIGRATION_PACKAGE).joinpath("049_index_gnaf_identity_anchors.sql").read_text("utf-8")
    )

    assert "ON registry.property_identifier (property_ref)" in migration
    assert "WHERE scheme='gnaf_pid'" in migration
    assert "WHERE is_current" not in migration


def test_consumer_import_identity_and_delivery_are_separately_constrained() -> None:
    initial = (
        files(MIGRATION_PACKAGE)
        .joinpath("040_async_consumer_import_operations.sql")
        .read_text("utf-8")
    )
    extension = (
        files(MIGRATION_PACKAGE)
        .joinpath("041_consumer_import_activation_monitoring.sql")
        .read_text("utf-8")
    )

    assert hashlib.sha256(initial.encode()).hexdigest() == (
        "a7e244d039addacc3c2f1a8fd268f449a6b632b1fa48b5eaf524ea6eb933ab93"
    )
    assert hashlib.sha256(extension.encode()).hexdigest() == (
        "ecf5a145576376aa1a7ffda068207a2c97da11e2a85895dd7e96d491dfc28302"
    )
    assert "CREATE TABLE ops.consumer_import_operation" in initial
    assert "UNIQUE (target_feature, idempotency_key)" in initial
    assert "consumer_import_remote_operation_uq" in initial
    assert "consumer_import_active_release_identity_uq" in extension
    assert "dataset_release_id,dataset_id,target_feature,schema_version" in extension
    assert "WHERE status NOT IN ('failed','rejected')" in extension

    aliases = (
        files(MIGRATION_PACKAGE)
        .joinpath("042_consumer_import_delivery_aliases.sql")
        .read_text("utf-8")
    )
    assert hashlib.sha256(aliases.encode()).hexdigest() == (
        "484640580d777f956b3036da1d51776043e6159ccb4c86c4683216ec2d8e4323"
    )
    assert "CREATE TABLE ops.consumer_import_delivery_alias" in aliases
    assert "PRIMARY KEY (target_feature, idempotency_key)" in aliases
    assert "ADD COLUMN activation_attempt" in aliases
    assert "consumer_import_operation_id, target_feature" in aliases
