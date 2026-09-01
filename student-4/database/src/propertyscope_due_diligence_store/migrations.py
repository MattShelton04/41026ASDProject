"""Apply checked, immutable SQL migrations in lexical order."""

from __future__ import annotations

from collections.abc import Iterator
from hashlib import sha256
from importlib import resources
from typing import Any

from psycopg import Connection

MIGRATION_PACKAGE = "propertyscope_due_diligence_store.sql"


def iter_migrations() -> Iterator[tuple[str, str]]:
    """Yield ``(filename, sql)`` for every packaged migration in lexical order."""
    root = resources.files(MIGRATION_PACKAGE)
    resources_in_order = sorted(
        (entry for entry in root.iterdir() if entry.name.endswith(".sql")),
        key=lambda entry: entry.name,
    )
    for entry in resources_in_order:
        yield entry.name, entry.read_text(encoding="utf-8")


def migrate(connection: Connection[Any]) -> None:
    """Create the migration ledger then apply any unapplied migrations once each."""
    connection.execute("CREATE SCHEMA IF NOT EXISTS due_diligence")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS due_diligence.schema_migration ("
        "version text PRIMARY KEY, checksum text NOT NULL, "
        "applied_at timestamptz NOT NULL DEFAULT now())"
    )
    applied = {
        row["version"]
        for row in connection.execute("SELECT version FROM due_diligence.schema_migration")
    }
    for name, sql in iter_migrations():
        if name in applied:
            continue
        checksum = sha256(sql.encode("utf-8")).hexdigest()
        with connection.transaction():
            connection.execute(sql)
            connection.execute(
                "INSERT INTO due_diligence.schema_migration (version, checksum) VALUES (%s, %s)",
                (name, checksum),
            )
