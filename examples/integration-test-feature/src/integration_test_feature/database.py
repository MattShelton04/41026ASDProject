"""Exclusive SQLite owner for the integration test feature."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, request

from integration_test_feature.errors import problem_response
from shared_contracts import IDEMPOTENCY_KEY_HEADER

OPERATION_KEY_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r":call:"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


class IntegrationTestConflictError(ValueError):
    """A mutation violates idempotency or record uniqueness."""


class IntegrationRecordStore:
    """Small SQLite repository with atomic mutation idempotency."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def initialize(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL CHECK (status IN ('active', 'archived'))
                );
                CREATE TABLE IF NOT EXISTS operations (
                    idempotency_key TEXT PRIMARY KEY,
                    request_hash TEXT NOT NULL,
                    outcome TEXT NOT NULL CHECK (outcome IN ('applied')),
                    result_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS record_details (
                    record_id INTEGER PRIMARY KEY REFERENCES records(id) ON DELETE CASCADE,
                    summary TEXT NOT NULL,
                    priority INTEGER NOT NULL CHECK (priority BETWEEN 1 AND 5)
                );
                CREATE TABLE IF NOT EXISTS record_dependencies (
                    record_id INTEGER NOT NULL REFERENCES records(id) ON DELETE CASCADE,
                    depends_on_record_id INTEGER NOT NULL REFERENCES records(id) ON DELETE CASCADE,
                    relationship TEXT NOT NULL CHECK (relationship IN ('requires', 'informs')),
                    PRIMARY KEY (record_id, depends_on_record_id),
                    CHECK (record_id != depends_on_record_id)
                );
                """
            )
            connection.executemany(
                "INSERT OR IGNORE INTO records (title, status) VALUES (?, 'active')",
                ((f"Reference record {index:02d}",) for index in range(1, 11)),
            )
            connection.executemany(
                """
                INSERT OR IGNORE INTO record_details (record_id, summary, priority)
                SELECT id, ?, ? FROM records WHERE title = ?
                """,
                (
                    (
                        f"Deterministic evidence item {index:02d} for integration testing.",
                        ((index - 1) % 5) + 1,
                        f"Reference record {index:02d}",
                    )
                    for index in range(1, 11)
                ),
            )
            connection.executemany(
                """
                INSERT OR IGNORE INTO record_dependencies (
                    record_id, depends_on_record_id, relationship
                )
                SELECT source.id, dependency.id, ?
                FROM records AS source, records AS dependency
                WHERE source.title = ? AND dependency.title = ?
                """,
                (
                    ("requires", "Reference record 03", "Reference record 01"),
                    ("informs", "Reference record 03", "Reference record 02"),
                    ("requires", "Reference record 06", "Reference record 03"),
                    ("requires", "Reference record 08", "Reference record 04"),
                    ("informs", "Reference record 08", "Reference record 05"),
                ),
            )

    def search(self, query: str) -> list[dict[str, object]]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT id, title, status FROM records
                WHERE lower(title) LIKE ? ORDER BY id ASC LIMIT 50
                """,
                (f"%{query.lower()}%",),
            ).fetchall()
        return [dict(row) for row in rows]

    def inspect(self, title: str) -> dict[str, object] | None:
        """Return deterministic detail for one exact record title."""
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT records.id, records.title, records.status,
                       record_details.summary, record_details.priority
                FROM records
                JOIN record_details ON record_details.record_id = records.id
                WHERE records.title = ? COLLATE NOCASE
                """,
                (title,),
            ).fetchone()
        return dict(row) if row is not None else None

    def dependencies(self, title: str) -> dict[str, object] | None:
        """Return one record plus its ordered dependency evidence."""
        record = self.inspect(title)
        if record is None:
            return None
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT dependency.id, dependency.title, dependency.status,
                       detail.priority, link.relationship
                FROM record_dependencies AS link
                JOIN records AS dependency ON dependency.id = link.depends_on_record_id
                JOIN record_details AS detail ON detail.record_id = dependency.id
                WHERE link.record_id = ?
                ORDER BY dependency.id ASC
                """,
                (record["id"],),
            ).fetchall()
        items = [dict(row) for row in rows]
        return {
            "record": record,
            "items": items,
            "count": len(items),
            "all_active": all(item["status"] == "active" for item in items),
        }

    def create(self, title: str, *, idempotency_key: str) -> tuple[dict[str, object], bool]:
        request_hash = sha256(
            json.dumps({"title": title}, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT request_hash, result_json FROM operations WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise IntegrationTestConflictError("idempotency key arguments do not match")
                return dict(json.loads(existing["result_json"])), False
            try:
                cursor = connection.execute(
                    "INSERT INTO records (title, status) VALUES (?, 'active')", (title,)
                )
            except sqlite3.IntegrityError as exc:
                raise IntegrationTestConflictError("record title already exists") from exc
            if cursor.lastrowid is None:
                raise RuntimeError("SQLite did not return the created record identifier")
            result: dict[str, object] = {
                "record": {"id": int(cursor.lastrowid), "title": title, "status": "active"},
                "created": True,
            }
            connection.execute(
                """
                INSERT INTO operations (idempotency_key, request_hash, outcome, result_json)
                VALUES (?, ?, 'applied', ?)
                """,
                (idempotency_key, request_hash, json.dumps(result, sort_keys=True)),
            )
            return result, True

    def operation_status(self, idempotency_key: str) -> dict[str, object]:
        if OPERATION_KEY_PATTERN.fullmatch(idempotency_key) is None:
            return {"status": "unknown"}
        with self._connection() as connection:
            row = connection.execute(
                "SELECT result_json FROM operations WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        if row is None:
            return {"status": "not_applied"}
        return {"status": "applied", "result": json.loads(row["result_json"])}

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._path, timeout=5, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()


def create_database_app(store: IntegrationRecordStore) -> Flask:
    """Create the internal database-service API around its exclusive store."""
    app = Flask("integration-test-feature-database")

    @app.get("/health/ready")
    def ready() -> tuple[Response, int]:
        return jsonify({"status": "healthy"}), 200

    @app.get("/api/v1/records")
    def search_records() -> tuple[Response, int]:
        query = request.args.get("query", "").strip()
        items = store.search(query)
        return jsonify({"items": items, "count": len(items)}), 200

    @app.post("/api/v1/records")
    def create_record() -> Response | tuple[Response, int]:
        payload: Any = request.get_json(silent=True)
        title = payload.get("title", "").strip() if isinstance(payload, dict) else ""
        key = request.headers.get(IDEMPOTENCY_KEY_HEADER, "").strip()
        if not title or len(title) > 200 or OPERATION_KEY_PATTERN.fullmatch(key) is None:
            return problem_response(
                422,
                "invalid_request",
                "title and a valid operation idempotency key are required",
            )
        try:
            result, created = store.create(title, idempotency_key=key)
        except IntegrationTestConflictError:
            return problem_response(
                409,
                "idempotency_conflict",
                "The idempotency key or record title conflicts with an existing operation",
            )
        return jsonify(result), 201 if created else 200

    @app.get("/api/v1/records/by-title/<path:title>")
    def inspect_record(title: str) -> Response | tuple[Response, int]:
        record = store.inspect(title.strip())
        if record is None:
            return problem_response(404, "record_not_found", "Record does not exist")
        return jsonify({"record": record}), 200

    @app.get("/api/v1/records/by-title/<path:title>/dependencies")
    def record_dependencies(title: str) -> Response | tuple[Response, int]:
        result = store.dependencies(title.strip())
        if result is None:
            return problem_response(404, "record_not_found", "Record does not exist")
        return jsonify(result), 200

    @app.get("/api/v1/operations/<path:idempotency_key>")
    def operation_status(idempotency_key: str) -> tuple[Response, int]:
        return jsonify(store.operation_status(idempotency_key)), 200

    return app


def create_app() -> Flask:
    """Environment-driven application factory used by the database container."""
    store = IntegrationRecordStore(
        Path(os.environ.get("INTEGRATION_TEST_DATABASE_PATH", "instance/integration-test.sqlite3"))
    )
    store.initialize()
    return create_database_app(store)
