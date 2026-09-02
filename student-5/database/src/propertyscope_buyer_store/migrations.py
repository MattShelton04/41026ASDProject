"""Forward-only SQLite migrations and deterministic seeding."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from importlib.resources import files

_SQL_PACKAGE = "propertyscope_buyer_store.sql"
_SEED_MIGRATION = "002_seed.sql"


def migrate(connection: sqlite3.Connection) -> None:
    """Apply packaged migrations after the current SQLite user version."""

    current = int(connection.execute("PRAGMA user_version").fetchone()[0])
    migrations = sorted(
        (item for item in files(_SQL_PACKAGE).iterdir() if item.name.endswith(".sql")),
        key=lambda item: item.name,
    )
    for index, migration in enumerate(migrations, start=1):
        if index <= current:
            continue
        connection.executescript(migration.read_text(encoding="utf-8"))
        connection.execute(f"PRAGMA user_version = {index}")
        connection.commit()


def seed(connection: sqlite3.Connection) -> None:
    """Reapply the idempotent deterministic seed without changing retained rows."""

    script = files(_SQL_PACKAGE).joinpath(_SEED_MIGRATION).read_text(encoding="utf-8")
    connection.executescript(script)
    connection.commit()


def schema_fingerprint(connection: sqlite3.Connection) -> dict[str, str | int]:
    """Return a stable digest of the user schema and migration version."""

    rows = connection.execute(
        """
        SELECT type, name, tbl_name, sql
        FROM sqlite_master
        WHERE name NOT LIKE 'sqlite_%'
        ORDER BY type, name
        """
    ).fetchall()
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    canonical = json.dumps(
        {"version": version, "objects": [tuple(row) for row in rows]},
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return {
        "algorithm": "sha256",
        "fingerprint": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "schema_version": version,
    }
