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
from shared_contracts import AgentRun, AgentRunDetail, AgentStep, HumanReview, RunStatus

SCHEMA_VERSION = 1

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


class PersistenceError(RuntimeError):
    """The owned state store is unavailable or contains incompatible data."""


class SQLiteRunStore(RunStore):
    """Persist run snapshots and steps atomically with optimistic versions."""

    def __init__(self, path: Path, *, busy_timeout_ms: int = 5_000) -> None:
        self._path = path
        self._busy_timeout_ms = busy_timeout_ms

    def initialize(self) -> None:
        """Create the store and apply forward-only migrations explicitly."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            current = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if current > SCHEMA_VERSION:
                raise PersistenceError(
                    f"database schema {current} is newer than supported schema {SCHEMA_VERSION}"
                )
            if current < 1:
                connection.executescript(MIGRATION_1)
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def create(self, run: AgentRun) -> None:
        """Persist a new run exactly once."""
        try:
            with self._transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO agent_runs (id, version, status, updated_at, payload_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    self._run_values(run),
                )
        except sqlite3.IntegrityError as exc:
            raise PersistenceError(f"agent run already exists: {run.id}") from exc

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
            return updated

    def health(self) -> StoreHealth:
        """Verify connectivity and migration state without changing the store."""
        try:
            with self._connection() as connection:
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                connection.execute("SELECT 1").fetchone()
            if version != SCHEMA_VERSION:
                return StoreHealth(
                    ready=False,
                    detail=f"schema version {version}; expected {SCHEMA_VERSION}",
                )
            return StoreHealth(ready=True, detail=f"schema version {version}")
        except sqlite3.Error as exc:
            return StoreHealth(ready=False, detail=f"SQLite unavailable: {type(exc).__name__}")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._path,
            timeout=self._busy_timeout_ms / 1_000,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {self._busy_timeout_ms}")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
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

    @staticmethod
    def _dump(model: AgentRun | AgentStep | HumanReview) -> str:
        return json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
