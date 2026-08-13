"""Small deterministic SQL migration runner."""

from __future__ import annotations

from hashlib import sha256
from importlib.resources import files
from typing import Any

from psycopg import Connection

MIGRATION_PACKAGE = "propertyscope_data_store.sql"


def migrate(connection: Connection[Any]) -> None:
    """Apply checked, immutable SQL migrations in lexical order."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS public.propertyscope_schema_migration (
            version TEXT PRIMARY KEY,
            checksum TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    root = files(MIGRATION_PACKAGE)
    for resource in sorted(root.iterdir(), key=lambda item: item.name):
        if not resource.name.endswith(".sql"):
            continue
        sql = resource.read_text(encoding="utf-8")
        checksum = sha256(sql.encode()).hexdigest()
        existing = connection.execute(
            "SELECT checksum FROM public.propertyscope_schema_migration WHERE version = %s",
            (resource.name,),
        ).fetchone()
        if existing is not None:
            if existing[0] != checksum:
                raise RuntimeError(f"migration checksum changed: {resource.name}")
            continue
        connection.execute(sql)
        connection.execute(
            "INSERT INTO public.propertyscope_schema_migration(version, checksum) VALUES (%s, %s)",
            (resource.name, checksum),
        )
    connection.commit()


def schema_fingerprint(connection: Connection[Any]) -> str:
    """Return a stable fingerprint of Feature 1 schemas, tables, columns and indexes."""
    rows = connection.execute(
        """
        SELECT table_schema, table_name, column_name, data_type, is_nullable,
               COALESCE(column_default, '')
        FROM information_schema.columns
        WHERE table_schema IN ('ops', 'registry', 'warehouse', 'serving', 'stage')
        ORDER BY table_schema, table_name, ordinal_position
        """
    ).fetchall()
    payload = "\n".join("|".join(str(value) for value in row) for row in rows)
    return sha256(payload.encode()).hexdigest()
