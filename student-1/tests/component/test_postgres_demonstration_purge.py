"""Production purge of the seeded demonstration baseline against a disposable PostGIS database.

Requires PROPERTYSCOPE_TEST_POSTGRES_URL for a disposable administrator server.
Never point it at the retained application database.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from propertyscope_data_store.demonstration_data import purge_demonstration_data, purge_script
from propertyscope_data_store.migrations import migrate

ADMIN_URL = os.getenv("PROPERTYSCOPE_TEST_POSTGRES_URL", "").strip()
pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="requires disposable PostgreSQL test URL")

Connection = psycopg.Connection[dict[str, Any]]

SEED_RUN = "30000000-0000-0000-0000-000000000001"
SEED_ARTIFACT = "50000000-0000-0000-0000-000000000001"
SEED_RELEASE = "60000000-0000-0000-0000-000000000001"
SEED_PROPERTY = "a0000000-0000-0000-0000-000000000001"
CATALOGUE = ("ops.source_definition", "ops.job_definition")
DEMONSTRATION_TABLES = (
    "ops.artifact_record",
    "ops.dataset_release",
    "ops.idempotency_record",
    "ops.import_attempt_evidence",
    "ops.import_operation",
    "ops.ingestion_run",
    "ops.publication_receipt",
    "ops.quality_result",
    "ops.run_activity",
    "ops.run_task",
    "registry.address_alias",
    "registry.property",
    "registry.property_identifier",
    "registry.unresolved_match",
    "serving.accepted_generation",
    "serving.property_coverage",
    "warehouse.bocsar_coverage",
    "warehouse.bocsar_observation",
    "warehouse.gnaf_address",
    "warehouse.import_batch",
    "warehouse.psi_sale",
    "warehouse.school",
)


@pytest.fixture
def database() -> Iterator[str]:
    name = f"propertyscope_demo_purge_{uuid.uuid4().hex}"
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = make_conninfo(ADMIN_URL, dbname=name)
    try:
        with psycopg.connect(url, row_factory=dict_row) as conn:
            migrate(conn)
        yield url
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def _count(conn: Connection, table: str) -> int:
    row = conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()  # noqa: S608 - table names are test constants
    assert row is not None
    return int(row["n"])


def _copy(conn: Connection, table: str, key: str, source: str, overrides: dict[str, Any]) -> None:
    """Insert a copy of one seed row with new identities: a stand-in for a real collection."""
    conn.execute(
        f"""INSERT INTO {table}
        SELECT (jsonb_populate_record(NULL::{table}, to_jsonb(seed) || %s::jsonb)).*
        FROM {table} AS seed WHERE seed.{key} = %s""",  # noqa: S608 - identifiers are test constants; values are bound
        (Jsonb(overrides), source),
    )


def test_purge_empties_every_demonstration_table_and_keeps_the_job_catalogue(
    database: str,
) -> None:
    with psycopg.connect(database, row_factory=dict_row) as conn:
        catalogue = {table: _count(conn, table) for table in CATALOGUE}
        assert all(_count(conn, table) > 0 for table in DEMONSTRATION_TABLES)

        deleted = purge_demonstration_data(conn)

        assert deleted["ops.dataset_release"] == 7
        assert deleted["registry.property"] == 30
        assert {table: _count(conn, table) for table in DEMONSTRATION_TABLES} == dict.fromkeys(
            DEMONSTRATION_TABLES, 0
        )
        assert {table: _count(conn, table) for table in CATALOGUE} == catalogue
        assert purge_demonstration_data(conn) == {}


def test_purge_keeps_real_releases_and_unlinks_the_seed_release_they_superseded(
    database: str,
) -> None:
    run, artifact, release, prop = (str(uuid.uuid4()) for _ in range(4))
    with psycopg.connect(database, row_factory=dict_row) as conn:
        _copy(
            conn,
            "ops.ingestion_run",
            "id",
            SEED_RUN,
            {"id": run, "request_id": f"real-{run}", "idempotency_key": f"real-{run}"},
        )
        _copy(
            conn,
            "ops.artifact_record",
            "id",
            SEED_ARTIFACT,
            {"id": artifact, "ingestion_run_id": run, "run_task_id": None},
        )
        _copy(
            conn,
            "ops.dataset_release",
            "id",
            SEED_RELEASE,
            {
                "id": release,
                "ingestion_run_id": run,
                "artifact_record_id": artifact,
                "release_version": f"real-{release}",
                "status": "candidate",
                "supersedes_release_id": SEED_RELEASE,
            },
        )
        _copy(
            conn,
            "registry.property",
            "property_ref",
            SEED_PROPERTY,
            {"property_ref": prop, "address_display": "1 George Street, Sydney NSW 2000"},
        )
        conn.execute(
            """INSERT INTO warehouse.gnaf_address
            SELECT (jsonb_populate_record(NULL::warehouse.gnaf_address, to_jsonb(seed)
                || jsonb_build_object('dataset_release_id', %s::text, 'ingestion_run_id', %s::text,
                                      'artifact_record_id', %s::text, 'property_ref', %s::text)
            )).* FROM warehouse.gnaf_address AS seed WHERE seed.dataset_release_id = %s""",
            (release, run, artifact, prop, SEED_RELEASE),
        )
        conn.commit()

        purge_demonstration_data(conn)

        kept = conn.execute(
            "SELECT supersedes_release_id FROM ops.dataset_release WHERE id = %s", (release,)
        ).fetchone()
        assert kept == {"supersedes_release_id": None}
        assert _count(conn, "ops.dataset_release") == 1
        assert _count(conn, "ops.ingestion_run") == 1
        assert _count(conn, "warehouse.gnaf_address") > 0
        properties = conn.execute("SELECT property_ref FROM registry.property").fetchall()
        assert [str(row["property_ref"]) for row in properties] == [prop]


def test_the_operator_script_matches_the_startup_purge(database: str) -> None:
    with psycopg.connect(database, row_factory=dict_row, autocommit=True) as conn:
        conn.execute(purge_script())
        assert all(_count(conn, table) == 0 for table in DEMONSTRATION_TABLES)
        assert all(_count(conn, table) > 0 for table in CATALOGUE)
