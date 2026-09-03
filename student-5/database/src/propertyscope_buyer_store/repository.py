"""SQLite persistence owned exclusively by the Student 5 database service."""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Callable, Mapping
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from propertyscope_buyer_store.domain import decode_case
from propertyscope_buyer_store.migrations import migrate, schema_fingerprint

TABLES = ("buyer_case", "case_property", "case_note", "case_task")


class StoreError(RuntimeError):
    """Base class for safe persistence outcomes."""


class RecordNotFoundError(StoreError):
    """A record is absent from the configured owner's scope."""


class ConcurrentUpdateError(StoreError):
    """The submitted optimistic version is stale."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _new_id() -> str:
    return str(uuid.uuid4())


def _mapping(row: sqlite3.Row) -> dict[str, Any]:
    value = dict(row)
    if "completed" in value:
        value["completed"] = bool(value["completed"])
    return value


class BuyerStore:
    """Repository facade that opens the feature-owned SQLite file per operation."""

    def __init__(
        self,
        database_path: Path,
        *,
        clock: Callable[[], str] = _utc_now,
        id_factory: Callable[[], str] = _new_id,
    ) -> None:
        self._database_path = database_path
        self._clock = clock
        self._id_factory = id_factory

    def connect(self) -> sqlite3.Connection:
        """Open one configured connection with SQLite integrity enforcement enabled."""

        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self._database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialize(self) -> None:
        with closing(self.connect()) as connection:
            migrate(connection)

    def ready(self) -> bool:
        try:
            with closing(self.connect()) as connection:
                connection.execute("SELECT 1").fetchone()
                connection.execute("SELECT json_valid('[]')").fetchone()
                return int(connection.execute("PRAGMA user_version").fetchone()[0]) >= 2
        except sqlite3.Error:
            return False

    def seed_report(self) -> dict[str, Any]:
        with closing(self.connect()) as connection:
            counts = {
                table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in TABLES
            }
        return {
            "tables": counts,
            "minimum_required": 10,
            "minimum_satisfied": min(counts.values()) >= 10,
        }

    def schema_fingerprint(self) -> dict[str, str | int]:
        with closing(self.connect()) as connection:
            return schema_fingerprint(connection)

    def list_cases(self, owner_ref: str, *, page: int, page_size: int) -> dict[str, Any]:
        offset = (page - 1) * page_size
        with closing(self.connect()) as connection:
            total = int(
                connection.execute(
                    "SELECT COUNT(*) FROM buyer_case WHERE owner_ref = ?", (owner_ref,)
                ).fetchone()[0]
            )
            rows = connection.execute(
                """
                SELECT * FROM buyer_case
                WHERE owner_ref = ?
                ORDER BY updated_at DESC, id
                LIMIT ? OFFSET ?
                """,
                (owner_ref, page_size, offset),
            ).fetchall()
        return {
            "items": [decode_case(_mapping(row)) for row in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
        }

    def get_case(self, owner_ref: str, case_id: str) -> dict[str, Any] | None:
        with closing(self.connect()) as connection:
            row = connection.execute(
                "SELECT * FROM buyer_case WHERE id = ? AND owner_ref = ?",
                (case_id, owner_ref),
            ).fetchone()
        return None if row is None else decode_case(_mapping(row))

    def create_case(self, owner_ref: str, values: Mapping[str, Any]) -> dict[str, Any]:
        case_id = self._id_factory()
        timestamp = self._clock()
        with closing(self.connect()) as connection:
            connection.execute(
                """
                INSERT INTO buyer_case (
                    id, owner_ref, name, preferences_json, budget_min_aud, budget_max_aud,
                    target_suburbs_json, status, created_at, updated_at, version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    case_id,
                    owner_ref,
                    values["name"],
                    values["preferences_json"],
                    values["budget_min_aud"],
                    values["budget_max_aud"],
                    values["target_suburbs_json"],
                    values["status"],
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()
        created = self.get_case(owner_ref, case_id)
        assert created is not None
        return created

    def update_case(
        self,
        owner_ref: str,
        case_id: str,
        changes: Mapping[str, Any],
        *,
        expected_version: int,
    ) -> dict[str, Any]:
        current = self.get_case(owner_ref, case_id)
        if current is None:
            raise RecordNotFoundError("buyer case does not exist")
        if current["version"] != expected_version:
            raise ConcurrentUpdateError("buyer case version is stale")
        assignments = [f"{field} = ?" for field in changes]
        assignments.extend(["updated_at = ?", "version = version + 1"])
        parameters = [*changes.values(), self._clock(), case_id, owner_ref, expected_version]
        with closing(self.connect()) as connection:
            cursor = connection.execute(
                f"UPDATE buyer_case SET {', '.join(assignments)} "
                "WHERE id = ? AND owner_ref = ? AND version = ?",
                parameters,
            )
            connection.commit()
        if cursor.rowcount != 1:
            raise ConcurrentUpdateError("buyer case version is stale")
        updated = self.get_case(owner_ref, case_id)
        assert updated is not None
        return updated

    def delete_case(self, owner_ref: str, case_id: str) -> bool:
        with closing(self.connect()) as connection:
            deleted = connection.execute(
                "DELETE FROM buyer_case WHERE id = ? AND owner_ref = ?",
                (case_id, owner_ref),
            ).rowcount
            connection.commit()
        return bool(deleted)

    def list_properties(
        self, owner_ref: str, case_id: str, *, page: int, page_size: int
    ) -> dict[str, Any]:
        return self._list_children("case_property", owner_ref, case_id, page, page_size)

    def get_property(self, owner_ref: str, case_id: str, property_id: str) -> dict[str, Any] | None:
        return self._get_child("case_property", owner_ref, case_id, property_id)

    def create_property(
        self, owner_ref: str, case_id: str, values: Mapping[str, Any]
    ) -> dict[str, Any]:
        return self._create_child("case_property", owner_ref, case_id, values)

    def update_property(
        self,
        owner_ref: str,
        case_id: str,
        property_id: str,
        changes: Mapping[str, Any],
        *,
        expected_version: int,
    ) -> dict[str, Any]:
        return self._update_child(
            "case_property",
            owner_ref,
            case_id,
            property_id,
            changes,
            expected_version=expected_version,
        )

    def delete_property(self, owner_ref: str, case_id: str, property_id: str) -> bool:
        timestamp = self._clock()
        with closing(self.connect()) as connection:
            owned = connection.execute(
                """
                SELECT 1 FROM case_property AS child
                JOIN buyer_case AS parent ON parent.id = child.buyer_case_id
                WHERE child.id = ? AND child.buyer_case_id = ? AND parent.owner_ref = ?
                """,
                (property_id, case_id, owner_ref),
            ).fetchone()
            if owned is None:
                return False
            for table in ("case_note", "case_task"):
                connection.execute(
                    f"""
                    UPDATE {table}
                    SET case_property_id = NULL, updated_at = ?, version = version + 1
                    WHERE buyer_case_id = ? AND case_property_id = ?
                    """,
                    (timestamp, case_id, property_id),
                )
            deleted = connection.execute(
                "DELETE FROM case_property WHERE id = ? AND buyer_case_id = ?",
                (property_id, case_id),
            ).rowcount
            connection.commit()
        return bool(deleted)

    def list_notes(
        self, owner_ref: str, case_id: str, *, page: int, page_size: int
    ) -> dict[str, Any]:
        return self._list_children("case_note", owner_ref, case_id, page, page_size)

    def get_note(self, owner_ref: str, case_id: str, note_id: str) -> dict[str, Any] | None:
        return self._get_child("case_note", owner_ref, case_id, note_id)

    def create_note(
        self, owner_ref: str, case_id: str, values: Mapping[str, Any]
    ) -> dict[str, Any]:
        return self._create_child("case_note", owner_ref, case_id, values)

    def update_note(
        self,
        owner_ref: str,
        case_id: str,
        note_id: str,
        changes: Mapping[str, Any],
        *,
        expected_version: int,
    ) -> dict[str, Any]:
        return self._update_child(
            "case_note",
            owner_ref,
            case_id,
            note_id,
            changes,
            expected_version=expected_version,
        )

    def delete_note(self, owner_ref: str, case_id: str, note_id: str) -> bool:
        return self._delete_child("case_note", owner_ref, case_id, note_id)

    def list_tasks(
        self, owner_ref: str, case_id: str, *, page: int, page_size: int
    ) -> dict[str, Any]:
        return self._list_children("case_task", owner_ref, case_id, page, page_size)

    def get_task(self, owner_ref: str, case_id: str, task_id: str) -> dict[str, Any] | None:
        return self._get_child("case_task", owner_ref, case_id, task_id)

    def create_task(
        self, owner_ref: str, case_id: str, values: Mapping[str, Any]
    ) -> dict[str, Any]:
        normalized = dict(values)
        normalized["completed"] = int(bool(normalized["completed"]))
        return self._create_child("case_task", owner_ref, case_id, normalized)

    def update_task(
        self,
        owner_ref: str,
        case_id: str,
        task_id: str,
        changes: Mapping[str, Any],
        *,
        expected_version: int,
    ) -> dict[str, Any]:
        normalized = dict(changes)
        if "completed" in normalized:
            normalized["completed"] = int(bool(normalized["completed"]))
        return self._update_child(
            "case_task",
            owner_ref,
            case_id,
            task_id,
            normalized,
            expected_version=expected_version,
        )

    def delete_task(self, owner_ref: str, case_id: str, task_id: str) -> bool:
        return self._delete_child("case_task", owner_ref, case_id, task_id)

    def _case_exists(self, connection: sqlite3.Connection, owner_ref: str, case_id: str) -> bool:
        return (
            connection.execute(
                "SELECT 1 FROM buyer_case WHERE id = ? AND owner_ref = ?", (case_id, owner_ref)
            ).fetchone()
            is not None
        )

    def _list_children(
        self, table: str, owner_ref: str, case_id: str, page: int, page_size: int
    ) -> dict[str, Any]:
        offset = (page - 1) * page_size
        with closing(self.connect()) as connection:
            if not self._case_exists(connection, owner_ref, case_id):
                raise RecordNotFoundError("buyer case does not exist")
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE buyer_case_id = ?", (case_id,)
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"SELECT * FROM {table} WHERE buyer_case_id = ? "
                "ORDER BY updated_at DESC, id LIMIT ? OFFSET ?",
                (case_id, page_size, offset),
            ).fetchall()
        return {
            "items": [_mapping(row) for row in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
        }

    def _get_child(
        self, table: str, owner_ref: str, case_id: str, record_id: str
    ) -> dict[str, Any] | None:
        with closing(self.connect()) as connection:
            row = connection.execute(
                f"""
                SELECT child.* FROM {table} AS child
                JOIN buyer_case AS parent ON parent.id = child.buyer_case_id
                WHERE child.id = ? AND child.buyer_case_id = ? AND parent.owner_ref = ?
                """,
                (record_id, case_id, owner_ref),
            ).fetchone()
        return None if row is None else _mapping(row)

    def _create_child(
        self, table: str, owner_ref: str, case_id: str, values: Mapping[str, Any]
    ) -> dict[str, Any]:
        record_id = self._id_factory()
        timestamp = self._clock()
        with closing(self.connect()) as connection:
            if not self._case_exists(connection, owner_ref, case_id):
                raise RecordNotFoundError("buyer case does not exist")
            fields = ["id", "buyer_case_id", *values.keys(), "created_at", "updated_at", "version"]
            parameters = [record_id, case_id, *values.values(), timestamp, timestamp, 1]
            placeholders = ", ".join("?" for _ in fields)
            connection.execute(
                f"INSERT INTO {table} ({', '.join(fields)}) VALUES ({placeholders})", parameters
            )
            connection.commit()
        created = self._get_child(table, owner_ref, case_id, record_id)
        assert created is not None
        return created

    def _update_child(
        self,
        table: str,
        owner_ref: str,
        case_id: str,
        record_id: str,
        changes: Mapping[str, Any],
        *,
        expected_version: int,
    ) -> dict[str, Any]:
        current = self._get_child(table, owner_ref, case_id, record_id)
        if current is None:
            raise RecordNotFoundError("resource does not exist")
        if current["version"] != expected_version:
            raise ConcurrentUpdateError("resource version is stale")
        assignments = [f"{field} = ?" for field in changes]
        assignments.extend(["updated_at = ?", "version = version + 1"])
        parameters = [*changes.values(), self._clock(), record_id, case_id, expected_version]
        with closing(self.connect()) as connection:
            cursor = connection.execute(
                f"UPDATE {table} SET {', '.join(assignments)} "
                "WHERE id = ? AND buyer_case_id = ? AND version = ?",
                parameters,
            )
            connection.commit()
        if cursor.rowcount != 1:
            raise ConcurrentUpdateError("resource version is stale")
        updated = self._get_child(table, owner_ref, case_id, record_id)
        assert updated is not None
        return updated

    def _delete_child(self, table: str, owner_ref: str, case_id: str, record_id: str) -> bool:
        if self._get_child(table, owner_ref, case_id, record_id) is None:
            return False
        with closing(self.connect()) as connection:
            deleted = connection.execute(
                f"DELETE FROM {table} WHERE id = ? AND buyer_case_id = ?", (record_id, case_id)
            ).rowcount
            connection.commit()
        return bool(deleted)
