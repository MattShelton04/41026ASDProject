"""SQLite implementation of the optimistic, single-writer run store."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from uuid import UUID

from agent_core import ConcurrentRunUpdateError, RunStore, StoreHealth, request_cancellation
from shared_contracts import (
    AgentRun,
    AgentRunDetail,
    AgentRunEvent,
    AgentStep,
    HumanReview,
    RunStatus,
)

SCHEMA_VERSION = 2
REQUIRED_TABLES = frozenset(
    {
        "agent_runs",
        "agent_steps",
        "human_reviews",
        "create_run_requests",
        "run_events",
    }
)

MIGRATION_1 = """
CREATE TABLE IF NOT EXISTS agent_runs (
    id TEXT PRIMARY KEY,
    version INTEGER NOT NULL CHECK (version >= 0),
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_steps (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL CHECK (sequence > 0),
    phase TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    UNIQUE (run_id, sequence)
);
CREATE INDEX IF NOT EXISTS ix_agent_steps_run_sequence
    ON agent_steps (run_id, sequence);
CREATE TABLE IF NOT EXISTS human_reviews (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    step_id TEXT NOT NULL REFERENCES agent_steps(id),
    reviewed_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    UNIQUE (run_id, step_id)
);
"""

MIGRATION_2 = """
CREATE TABLE IF NOT EXISTS create_run_requests (
    idempotency_key TEXT PRIMARY KEY,
    request_hash TEXT NOT NULL,
    run_id TEXT NOT NULL UNIQUE REFERENCES agent_runs(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS run_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    run_version INTEGER NOT NULL CHECK (run_version >= 0),
    occurred_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_run_events_run_id_id ON run_events (run_id, id);
"""


class PersistenceError(RuntimeError):
    """The owned state store is unavailable or contains incompatible data."""


class IdempotencyConflictError(PersistenceError):
    """An idempotency key was reused for a different validated request."""


class SQLiteRunStore(RunStore):
    """Persist run snapshots and steps atomically with optimistic versions."""

    def __init__(self, path: Path, *, busy_timeout_ms: int = 5_000) -> None:
        self._path = path
        self._busy_timeout_ms = busy_timeout_ms

    def initialize(self) -> None:
        """Create the store and apply forward-only migrations explicitly."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            current = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if current > SCHEMA_VERSION:
                raise PersistenceError(
                    f"database schema {current} is newer than supported schema {SCHEMA_VERSION}"
                )
            if current < 1:
                connection.executescript(MIGRATION_1)
                connection.execute("PRAGMA user_version = 1")
                current = 1
            if current < 2:
                connection.executescript(MIGRATION_2)
                connection.execute("PRAGMA user_version = 2")

    def create(self, run: AgentRun) -> None:
        """Persist a new run exactly once."""
        with self._transaction() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO agent_runs (id, version, status, updated_at, payload_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    self._run_values(run),
                )
            except sqlite3.IntegrityError as exc:
                raise PersistenceError(f"agent run already exists: {run.id}") from exc
            self._append_event(connection, run, event_type="run.created")

    def create_or_get(
        self,
        run: AgentRun,
        *,
        idempotency_key: str,
        request_hash: str,
    ) -> tuple[AgentRun, bool]:
        """Atomically create once or return the original run for an exact retry."""
        with self._transaction() as connection:
            existing = connection.execute(
                """
                SELECT request_hash, run_id FROM create_run_requests
                WHERE idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise IdempotencyConflictError(
                        "idempotency key was already used for a different run request"
                    )
                row = connection.execute(
                    "SELECT payload_json FROM agent_runs WHERE id = ?", (existing["run_id"],)
                ).fetchone()
                if row is None:
                    raise PersistenceError("idempotency record references a missing agent run")
                try:
                    return AgentRun.model_validate_json(row["payload_json"]), False
                except ValueError as exc:
                    raise PersistenceError("idempotent agent run is invalid") from exc
            connection.execute(
                """
                INSERT INTO agent_runs (id, version, status, updated_at, payload_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                self._run_values(run),
            )
            connection.execute(
                """
                INSERT INTO create_run_requests (idempotency_key, request_hash, run_id)
                VALUES (?, ?, ?)
                """,
                (idempotency_key, request_hash, str(run.id)),
            )
            self._append_event(connection, run, event_type="run.created")
            return run, True

    def get(self, run_id: UUID) -> AgentRunDetail | None:
        """Load a validated run and its steps in stable sequence order."""
        with self._connection() as connection:
            run_row = connection.execute(
                "SELECT payload_json FROM agent_runs WHERE id = ?", (str(run_id),)
            ).fetchone()
            if run_row is None:
                return None
            step_rows = connection.execute(
                """
                SELECT payload_json FROM agent_steps
                WHERE run_id = ? ORDER BY sequence ASC
                """,
                (str(run_id),),
            ).fetchall()
            review_rows = connection.execute(
                """
                SELECT payload_json FROM human_reviews
                WHERE run_id = ? ORDER BY reviewed_at ASC, id ASC
                """,
                (str(run_id),),
            ).fetchall()
        try:
            run = AgentRun.model_validate_json(run_row["payload_json"])
            steps = tuple(AgentStep.model_validate_json(row["payload_json"]) for row in step_rows)
            reviews = tuple(
                HumanReview.model_validate_json(row["payload_json"]) for row in review_rows
            )
        except ValueError as exc:
            raise PersistenceError(f"stored agent run is invalid: {run_id}") from exc
        return AgentRunDetail(run=run, steps=steps, reviews=reviews)

    def list_resumable(self) -> tuple[AgentRunDetail, ...]:
        """Load active runs in a stable order for startup reconciliation."""
        excluded = (
            RunStatus.REVIEW_REQUIRED.value,
            RunStatus.SUCCEEDED.value,
            RunStatus.FAILED.value,
            RunStatus.CANCELLED.value,
        )
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT id FROM agent_runs
                WHERE status NOT IN (?, ?, ?, ?)
                ORDER BY updated_at ASC, id ASC
                """,
                excluded,
            ).fetchall()
        details: list[AgentRunDetail] = []
        for row in rows:
            detail = self.get(UUID(row["id"]))
            if detail is not None:
                details.append(detail)
        return tuple(details)

    def list_events(
        self,
        run_id: UUID,
        *,
        after_id: int = 0,
        limit: int = 100,
    ) -> tuple[AgentRunEvent, ...]:
        """Return a bounded page of safe events after an exclusive cursor."""
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT payload_json FROM run_events
                WHERE run_id = ? AND id > ?
                ORDER BY id ASC LIMIT ?
                """,
                (str(run_id), after_id, limit),
            ).fetchall()
        try:
            return tuple(AgentRunEvent.model_validate_json(row["payload_json"]) for row in rows)
        except ValueError as exc:
            raise PersistenceError(f"stored events are invalid for agent run: {run_id}") from exc

    def save(
        self,
        run: AgentRun,
        *,
        expected_version: int,
        step: AgentStep | None = None,
        review: HumanReview | None = None,
    ) -> None:
        """Atomically advance a run and insert or update one phase step."""
        if run.version != expected_version + 1:
            raise ConcurrentRunUpdateError("run version must advance by exactly one")
        if step is not None and step.run_id != run.id:
            raise PersistenceError("step belongs to a different agent run")
        if review is not None and review.run_id != run.id:
            raise PersistenceError("review belongs to a different agent run")
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE agent_runs
                SET version = ?, status = ?, updated_at = ?, payload_json = ?
                WHERE id = ? AND version = ?
                """,
                (
                    run.version,
                    run.status.value,
                    run.updated_at.isoformat(),
                    self._dump(run),
                    str(run.id),
                    expected_version,
                ),
            )
            if cursor.rowcount != 1:
                raise ConcurrentRunUpdateError(
                    f"agent run {run.id} was concurrently updated or does not exist"
                )
            if step is not None:
                self._upsert_step(connection, step)
            if review is not None:
                connection.execute(
                    """
                    INSERT INTO human_reviews (id, run_id, step_id, reviewed_at, payload_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        str(review.id),
                        str(review.run_id),
                        str(review.step_id),
                        review.reviewed_at.isoformat(),
                        self._dump(review),
                    ),
                )
            event_type = (
                "review.recorded"
                if review is not None
                else "step.updated"
                if step
                else "run.updated"
            )
            self._append_event(connection, run, event_type=event_type, step=step)

    def request_cancellation(self, run_id: UUID, *, now: datetime) -> AgentRun | None:
        """Record cancellation intent idempotently in one write transaction."""
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT payload_json FROM agent_runs WHERE id = ?", (str(run_id),)
            ).fetchone()
            if row is None:
                return None
            try:
                current = AgentRun.model_validate_json(row["payload_json"])
            except ValueError as exc:
                raise PersistenceError(f"stored agent run is invalid: {run_id}") from exc
            updated = request_cancellation(current, now=now)
            if updated is current:
                return current
            cursor = connection.execute(
                """
                UPDATE agent_runs
                SET version = ?, status = ?, updated_at = ?, payload_json = ?
                WHERE id = ? AND version = ?
                """,
                (
                    updated.version,
                    updated.status.value,
                    updated.updated_at.isoformat(),
                    self._dump(updated),
                    str(run_id),
                    current.version,
                ),
            )
            if cursor.rowcount != 1:
                raise ConcurrentRunUpdateError(f"agent run {run_id} was concurrently updated")
            self._append_event(connection, updated, event_type="run.cancellation_requested")
            return updated

    def health(self) -> StoreHealth:
        """Verify connectivity and migration state without changing the store."""
        try:
            with self._connection() as connection:
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                connection.execute("SELECT 1").fetchone()
                table_rows = connection.execute(
                    "SELECT name FROM sqlite_schema WHERE type = 'table'"
                ).fetchall()
            if version != SCHEMA_VERSION:
                return StoreHealth(
                    ready=False,
                    detail=f"schema version {version}; expected {SCHEMA_VERSION}",
                )
            missing = REQUIRED_TABLES.difference(row["name"] for row in table_rows)
            if missing:
                return StoreHealth(
                    ready=False,
                    detail=f"schema is missing tables: {', '.join(sorted(missing))}",
                )
            return StoreHealth(ready=True, detail=f"schema version {version}")
        except (PersistenceError, sqlite3.Error) as exc:
            cause = exc.__cause__ or exc
            return StoreHealth(ready=False, detail=f"SQLite unavailable: {type(cause).__name__}")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._path,
            timeout=self._busy_timeout_ms / 1_000,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {self._busy_timeout_ms}")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        try:
            connection = self._connect()
        except sqlite3.Error as exc:
            raise PersistenceError(f"SQLite connection failed: {type(exc).__name__}") from exc
        try:
            try:
                yield connection
            except PersistenceError:
                raise
            except sqlite3.Error as exc:
                raise PersistenceError(f"SQLite operation failed: {type(exc).__name__}") from exc
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

    @classmethod
    def _upsert_step(cls, connection: sqlite3.Connection, step: AgentStep) -> None:
        existing = connection.execute(
            "SELECT run_id, sequence FROM agent_steps WHERE id = ?", (str(step.id),)
        ).fetchone()
        if existing is None:
            connection.execute(
                """
                INSERT INTO agent_steps (id, run_id, sequence, phase, status, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(step.id),
                    str(step.run_id),
                    step.sequence,
                    step.phase.value,
                    step.status.value,
                    cls._dump(step),
                ),
            )
            return
        if existing["run_id"] != str(step.run_id) or existing["sequence"] != step.sequence:
            raise PersistenceError("persisted step identity or sequence cannot change")
        connection.execute(
            """
            UPDATE agent_steps SET phase = ?, status = ?, payload_json = ? WHERE id = ?
            """,
            (step.phase.value, step.status.value, cls._dump(step), str(step.id)),
        )

    @classmethod
    def _run_values(cls, run: AgentRun) -> tuple[str, int, str, str, str]:
        return (
            str(run.id),
            run.version,
            run.status.value,
            run.updated_at.isoformat(),
            cls._dump(run),
        )

    @classmethod
    def _append_event(
        cls,
        connection: sqlite3.Connection,
        run: AgentRun,
        *,
        event_type: str,
        step: AgentStep | None = None,
    ) -> None:
        cursor = connection.execute(
            """
            INSERT INTO run_events (run_id, run_version, occurred_at, payload_json)
            VALUES (?, ?, ?, '')
            """,
            (str(run.id), run.version, run.updated_at.isoformat()),
        )
        if cursor.lastrowid is None:
            raise PersistenceError("SQLite did not return the appended event identifier")
        event = AgentRunEvent(
            id=int(cursor.lastrowid),
            run_id=run.id,
            run_version=run.version,
            event_type=event_type,
            status=run.status,
            occurred_at=run.updated_at,
            step_id=step.id if step else None,
            step_phase=step.phase if step else None,
            step_status=step.status if step else None,
        )
        connection.execute(
            "UPDATE run_events SET payload_json = ? WHERE id = ?",
            (cls._dump(event), event.id),
        )

    @staticmethod
    def _dump(model: AgentRun | AgentRunEvent | AgentStep | HumanReview) -> str:
        return json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
