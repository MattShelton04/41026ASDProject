"""Apply packaged, forward-only SQLite migrations."""

from __future__ import annotations

import sqlite3
from importlib.resources import files


def migrate(connection: sqlite3.Connection) -> None:
    """Apply each migration after the current SQLite user version."""

    current = int(connection.execute("PRAGMA user_version").fetchone()[0])
    root = files("propertyscope_market_store.sql")
    migrations = sorted(
        (item for item in root.iterdir() if item.name.endswith(".sql")),
        key=lambda item: item.name,
    )
    for index, migration in enumerate(migrations, start=1):
        if index <= current:
            continue
        connection.executescript(migration.read_text(encoding="utf-8"))
        connection.execute(f"PRAGMA user_version = {index}")
        connection.commit()
