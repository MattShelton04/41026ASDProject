"""Remove the seeded demonstration baseline from a production database.

The migrations seed a deterministic showcase (``002_showcase_seed.sql`` and its repairs): about
ten synthetic records per accepted dataset, their runs, releases and quality evidence, and thirty
``Example Street`` properties. Local stacks and tests rely on it. A production database
(``PROPERTYSCOPE_DEMONSTRATION_DATA=false``, the Azure deployment) must start empty, so
``purge_demonstration_data`` runs after every migration pass there.

Only demonstration rows are removed, so the purge is idempotent and safe beside real data:

- runs with the seed identifiers (``30000000-…``, ``c0000000-…``) or of the synthetic
  ``fixture-property-full`` job, plus their retries;
- releases with the seed identifiers (``60000000-…``), of the ``fixture-property`` dataset, or
  built by those runs, with everything that hangs off them;
- the seed properties (``a0000000-…``) and properties only those releases referenced.

The source and job catalogue (``ops.source_definition``, ``ops.job_definition``) is kept: the
seed rows there are the registered jobs that real collections run.
"""

from __future__ import annotations

from typing import Any

from psycopg import Connection

# Plain literals throughout: nothing here is built from input.
_SELECT_DEMONSTRATION_ROWS: tuple[str, ...] = (
    "DROP TABLE IF EXISTS pg_temp.demo_run, pg_temp.demo_release, pg_temp.demo_property, "
    "pg_temp.demo_import",
    # Seed runs, every run of the synthetic fixture-property-full job, and their retries.
    """CREATE TEMP TABLE demo_run ON COMMIT DROP AS
    WITH RECURSIVE demo AS (
        SELECT id FROM ops.ingestion_run
        WHERE id::text LIKE '30000000-0000-0000-0000-%'
           OR id::text LIKE 'c0000000-0000-0000-0000-%'
           OR job_definition_id = '20000000-0000-0000-0000-000000000010'
        UNION
        SELECT child.id FROM ops.ingestion_run AS child JOIN demo ON child.parent_run_id = demo.id
    )
    SELECT id FROM demo""",
    """CREATE TEMP TABLE demo_release ON COMMIT DROP AS
    SELECT id FROM ops.dataset_release
    WHERE id::text LIKE '60000000-0000-0000-0000-%'
       OR dataset_id = 'fixture-property'
       OR ingestion_run_id IN (SELECT id FROM pg_temp.demo_run)""",
    """CREATE TEMP TABLE demo_property ON COMMIT DROP AS
    SELECT property_ref FROM registry.property
    WHERE property_ref::text LIKE 'a0000000-0000-0000-0000-%'
    UNION SELECT property_ref FROM warehouse.gnaf_address
        WHERE dataset_release_id IN (SELECT id FROM pg_temp.demo_release)
          AND property_ref IS NOT NULL
    UNION SELECT property_ref FROM warehouse.psi_sale
        WHERE dataset_release_id IN (SELECT id FROM pg_temp.demo_release)
          AND property_ref IS NOT NULL
    UNION SELECT property_ref FROM registry.property_identifier
        WHERE source_release_id IN (SELECT id FROM pg_temp.demo_release)
    UNION SELECT property_ref FROM registry.address_alias
        WHERE source_release_id IN (SELECT id FROM pg_temp.demo_release)
    UNION SELECT property_ref FROM serving.property_coverage
        WHERE dataset_release_id IN (SELECT id FROM pg_temp.demo_release)""",
    """CREATE TEMP TABLE demo_import ON COMMIT DROP AS
    SELECT id FROM ops.import_operation
    WHERE candidate_release_id IN (SELECT id FROM pg_temp.demo_release)
       OR ingestion_run_id IN (SELECT id FROM pg_temp.demo_run)""",
)

# Children before parents: (table reported, statement); an empty table name is a link update.
_PURGE_STATEMENTS: tuple[tuple[str, str], ...] = (
    (
        "ops.consumer_import_delivery_alias",
        "DELETE FROM ops.consumer_import_delivery_alias "
        "WHERE dataset_release_id IN (SELECT id FROM pg_temp.demo_release)",
    ),
    (
        "ops.consumer_import_operation",
        "DELETE FROM ops.consumer_import_operation "
        "WHERE dataset_release_id IN (SELECT id FROM pg_temp.demo_release)",
    ),
    (
        "ops.release_activation",
        "DELETE FROM ops.release_activation "
        "WHERE dataset_release_id IN (SELECT id FROM pg_temp.demo_release)",
    ),
    (
        "ops.publication_receipt",
        "DELETE FROM ops.publication_receipt "
        "WHERE dataset_release_id IN (SELECT id FROM pg_temp.demo_release)",
    ),
    (
        "ops.quality_result",
        "DELETE FROM ops.quality_result "
        "WHERE dataset_release_id IN (SELECT id FROM pg_temp.demo_release) "
        "OR ingestion_run_id IN (SELECT id FROM pg_temp.demo_run)",
    ),
    (
        "registry.unresolved_match",
        "DELETE FROM registry.unresolved_match "
        "WHERE dataset_release_id IN (SELECT id FROM pg_temp.demo_release)",
    ),
    (
        "registry.property_identifier",
        "DELETE FROM registry.property_identifier "
        "WHERE source_release_id IN (SELECT id FROM pg_temp.demo_release)",
    ),
    (
        "registry.address_alias",
        "DELETE FROM registry.address_alias "
        "WHERE source_release_id IN (SELECT id FROM pg_temp.demo_release)",
    ),
    (
        "serving.accepted_generation",
        "DELETE FROM serving.accepted_generation "
        "WHERE dataset_release_id IN (SELECT id FROM pg_temp.demo_release)",
    ),
    (
        "serving.property_coverage",
        "DELETE FROM serving.property_coverage "
        "WHERE dataset_release_id IN (SELECT id FROM pg_temp.demo_release)",
    ),
    (
        "serving.suburb_boundary_display",
        "DELETE FROM serving.suburb_boundary_display "
        "WHERE dataset_release_id IN (SELECT id FROM pg_temp.demo_release)",
    ),
    (
        "warehouse.bocsar_coverage",
        "DELETE FROM warehouse.bocsar_coverage "
        "WHERE dataset_release_id IN (SELECT id FROM pg_temp.demo_release) "
        "OR ingestion_run_id IN (SELECT id FROM pg_temp.demo_run)",
    ),
    (
        "warehouse.bocsar_observation",
        "DELETE FROM warehouse.bocsar_observation "
        "WHERE dataset_release_id IN (SELECT id FROM pg_temp.demo_release) "
        "OR ingestion_run_id IN (SELECT id FROM pg_temp.demo_run)",
    ),
    (
        "warehouse.gnaf_address",
        "DELETE FROM warehouse.gnaf_address "
        "WHERE dataset_release_id IN (SELECT id FROM pg_temp.demo_release) "
        "OR ingestion_run_id IN (SELECT id FROM pg_temp.demo_run)",
    ),
    (
        "warehouse.psi_sale",
        "DELETE FROM warehouse.psi_sale "
        "WHERE dataset_release_id IN (SELECT id FROM pg_temp.demo_release) "
        "OR ingestion_run_id IN (SELECT id FROM pg_temp.demo_run)",
    ),
    (
        "warehouse.reference_feature",
        "DELETE FROM warehouse.reference_feature "
        "WHERE dataset_release_id IN (SELECT id FROM pg_temp.demo_release) "
        "OR ingestion_run_id IN (SELECT id FROM pg_temp.demo_run)",
    ),
    (
        "warehouse.school",
        "DELETE FROM warehouse.school "
        "WHERE dataset_release_id IN (SELECT id FROM pg_temp.demo_release) "
        "OR ingestion_run_id IN (SELECT id FROM pg_temp.demo_run)",
    ),
    (
        "warehouse.seifa_sal",
        "DELETE FROM warehouse.seifa_sal "
        "WHERE dataset_release_id IN (SELECT id FROM pg_temp.demo_release) "
        "OR ingestion_run_id IN (SELECT id FROM pg_temp.demo_run)",
    ),
    (
        "warehouse.spatial_feature",
        "DELETE FROM warehouse.spatial_feature "
        "WHERE dataset_release_id IN (SELECT id FROM pg_temp.demo_release) "
        "OR ingestion_run_id IN (SELECT id FROM pg_temp.demo_run)",
    ),
    (
        "warehouse.import_batch",
        "DELETE FROM warehouse.import_batch "
        "WHERE dataset_release_id IN (SELECT id FROM pg_temp.demo_release) "
        "OR ingestion_run_id IN (SELECT id FROM pg_temp.demo_run)",
    ),
    (
        "ops.import_recovery_attribution",
        "DELETE FROM ops.import_recovery_attribution WHERE recovery_evidence_id IN ("
        "SELECT id FROM ops.import_recovery_evidence "
        "WHERE import_operation_id IN (SELECT id FROM pg_temp.demo_import))",
    ),
    # Attempt and recovery evidence cascade from the import operation.
    (
        "ops.import_operation",
        "DELETE FROM ops.import_operation WHERE id IN (SELECT id FROM pg_temp.demo_import)",
    ),
    # Self and circular references are cleared first: RESTRICT is checked row by row.
    (
        "",
        "UPDATE ops.dataset_release SET supersedes_release_id = NULL "
        "WHERE supersedes_release_id IN (SELECT id FROM pg_temp.demo_release)",
    ),
    (
        "ops.dataset_release",
        "DELETE FROM ops.dataset_release WHERE id IN (SELECT id FROM pg_temp.demo_release)",
    ),
    (
        "",
        "UPDATE ops.run_task SET input_artifact_id = NULL, output_artifact_id = NULL "
        "WHERE ingestion_run_id IN (SELECT id FROM pg_temp.demo_run) "
        "AND (input_artifact_id IS NOT NULL OR output_artifact_id IS NOT NULL)",
    ),
    (
        "ops.artifact_record",
        "DELETE FROM ops.artifact_record "
        "WHERE ingestion_run_id IN (SELECT id FROM pg_temp.demo_run)",
    ),
    (
        "ops.run_task",
        "DELETE FROM ops.run_task WHERE ingestion_run_id IN (SELECT id FROM pg_temp.demo_run)",
    ),
    (
        "",
        "UPDATE ops.ingestion_run SET parent_run_id = NULL "
        "WHERE id IN (SELECT id FROM pg_temp.demo_run) AND parent_run_id IS NOT NULL",
    ),
    # Run activity cascades from the run.
    (
        "ops.ingestion_run",
        "DELETE FROM ops.ingestion_run WHERE id IN (SELECT id FROM pg_temp.demo_run)",
    ),
    (
        "registry.property",
        """DELETE FROM registry.property AS property
        WHERE property.property_ref IN (SELECT property_ref FROM pg_temp.demo_property)
          AND NOT EXISTS (SELECT 1 FROM registry.property_identifier AS item
                          WHERE item.property_ref = property.property_ref)
          AND NOT EXISTS (SELECT 1 FROM registry.address_alias AS item
                          WHERE item.property_ref = property.property_ref)
          AND NOT EXISTS (SELECT 1 FROM registry.unresolved_match AS item
                          WHERE item.resolved_property_ref = property.property_ref)
          AND NOT EXISTS (SELECT 1 FROM warehouse.gnaf_address AS item
                          WHERE item.property_ref = property.property_ref)
          AND NOT EXISTS (SELECT 1 FROM warehouse.psi_sale AS item
                          WHERE item.property_ref = property.property_ref)
          AND NOT EXISTS (SELECT 1 FROM serving.property_coverage AS item
                          WHERE item.property_ref = property.property_ref)""",
    ),
    ("ops.idempotency_record", "DELETE FROM ops.idempotency_record WHERE scope = 'showcase'"),
)


def purge_demonstration_data(connection: Connection[Any]) -> dict[str, int]:
    """Delete every demonstration row in one transaction; return the deleted count per table."""
    deleted: dict[str, int] = {}
    with connection.transaction():
        for statement in _SELECT_DEMONSTRATION_ROWS:
            connection.execute(statement)
        for table, statement in _PURGE_STATEMENTS:
            count = connection.execute(statement).rowcount
            if table and count > 0:
                deleted[table] = deleted.get(table, 0) + count
    return deleted


def purge_script() -> str:
    """The purge as one SQL script, for an operator to run with ``psql`` on a live database."""
    statements = [*_SELECT_DEMONSTRATION_ROWS, *(statement for _, statement in _PURGE_STATEMENTS)]
    body = ";\n".join(" ".join(statement.split()) for statement in statements)
    return f"BEGIN;\n{body};\nCOMMIT;\n"
