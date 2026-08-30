"""Small deterministic SQL migration runner."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
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
            existing_checksum = existing["checksum"] if isinstance(existing, dict) else existing[0]
            if existing_checksum != checksum:
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
               COALESCE(column_default, '') AS column_default
        FROM information_schema.columns
        WHERE table_schema IN ('ops', 'registry', 'warehouse', 'serving', 'stage')
        ORDER BY table_schema, table_name, ordinal_position
        """
    ).fetchall()
    indexes = connection.execute(
        """
        SELECT schemaname, tablename, indexname, indexdef
        FROM pg_indexes
        WHERE schemaname IN ('ops', 'registry', 'warehouse', 'serving', 'stage')
        ORDER BY schemaname, tablename, indexname
        """
    ).fetchall()
    payload = json.dumps(
        [
            *_fingerprint_records(
                "column",
                rows,
                (
                    "table_schema",
                    "table_name",
                    "column_name",
                    "data_type",
                    "is_nullable",
                    "column_default",
                ),
            ),
            *_fingerprint_records(
                "index",
                indexes,
                ("schemaname", "tablename", "indexname", "indexdef"),
            ),
        ],
        default=str,
        separators=(",", ":"),
    )
    return sha256(payload.encode()).hexdigest()


def _fingerprint_records(
    kind: str,
    rows: Sequence[Mapping[str, Any] | Sequence[Any]],
    fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Canonicalise tuple rows and the store's real ``dict_row`` results identically."""
    return [
        {
            "kind": kind,
            "values": [row[field] for field in fields] if isinstance(row, Mapping) else list(row),
        }
        for row in rows
    ]
