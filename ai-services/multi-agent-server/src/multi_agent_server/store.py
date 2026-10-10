"""SQLite run store plus append-only JSONL workflow history and coordination audit.

The database is the source of truth: each run is one validated JSON snapshot with an optimistic
version, and every history and audit entry is a row with a per-run sequence number. After each
commit the same entries are appended to ``workflow_history.jsonl`` and
``coordination_audit.jsonl`` in the state directory, so the evidence trail can be read with
ordinary tools while the server runs.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from multi_agent_server.errors import ConcurrentUpdateError, RunNotFoundError, StoreUnavailableError
from shared_contracts.multi_agent import (
    ACTIVE_WORKFLOW_STATES,
    AgentRole,
    AuditEvent,
    CoordinationAuditEntry,
    JsonObject,
    WorkflowHistoryEntry,
    WorkflowRun,
    WorkflowState,
)

HISTORY_FILE = "workflow_history.jsonl"
AUDIT_FILE = "coordination_audit.jsonl"
DATABASE_FILE = "multi-agent.sqlite3"
SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    template_id TEXT NOT NULL,
    feature_id TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL,
    document TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS runs_by_created ON runs (created_at DESC);
CREATE TABLE IF NOT EXISTS history (
    run_id TEXT NOT NULL REFERENCES runs (id),
    sequence INTEGER NOT NULL,
    document TEXT NOT NULL,
    PRIMARY KEY (run_id, sequence)
);
CREATE TABLE IF NOT EXISTS audit (
    run_id TEXT NOT NULL REFERENCES runs (id),
    sequence INTEGER NOT NULL,
    document TEXT NOT NULL,
    PRIMARY KEY (run_id, sequence)
);
"""
_SELECT_DOCUMENTS = {
    "history": "SELECT document FROM history WHERE run_id = ? AND sequence > ? ORDER BY sequence",
    "audit": "SELECT document FROM audit WHERE run_id = ? AND sequence > ? ORDER BY sequence",
}
_NEXT_SEQUENCE = {
    "history": "SELECT COALESCE(MAX(sequence), 0) + 1 FROM history WHERE run_id = ?",
    "audit": "SELECT COALESCE(MAX(sequence), 0) + 1 FROM audit WHERE run_id = ?",
}
_LIST_RUNS = (
    "SELECT document FROM runs WHERE (? IS NULL OR template_id = ?) "
    "AND (? IS NULL OR feature_id = ?) AND (? IS NULL OR state = ?) "
    "ORDER BY created_at DESC, id LIMIT ?"
)


@dataclass(frozen=True, slots=True)
class HistoryDraft:
    """A transition to record; the store assigns sequence and time."""

    from_state: WorkflowState | None
    to_state: WorkflowState
    actor: str
    role: AgentRole
    reason: str
    request_id: str | None = None


@dataclass(frozen=True, slots=True)
class AuditDraft:
    """A coordination event to record; the store assigns sequence and time."""

    event: AuditEvent
    role: AgentRole
    actor: str
    detail: JsonObject
    request_id: str | None = None


class WorkflowStore:
    """Thread-safe single-connection SQLite store with JSONL mirrors."""

    def __init__(
        self,
        state_directory: Path,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._directory = state_directory
        self._clock = clock
        self._lock = threading.RLock()
        try:
            state_directory.mkdir(parents=True, exist_ok=True)
            self._connection = sqlite3.connect(
                state_directory / DATABASE_FILE, check_same_thread=False, timeout=10
            )
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA foreign_keys=ON")
            self._connection.executescript(SCHEMA)
        except (OSError, sqlite3.Error) as exc:
            raise StoreUnavailableError("Workflow state store could not be opened") from exc

    @property
    def directory(self) -> Path:
        return self._directory

    def close(self) -> None:
        """Close the connection; the store cannot be used afterwards."""
        with self._lock:
            self._connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                with self._connection:
                    yield self._connection
            except sqlite3.Error as exc:
                raise StoreUnavailableError("Workflow state store is unavailable") from exc

    def now(self) -> datetime:
        """The store clock, so snapshots and log entries agree on time."""
        return self._clock()

    def health(self) -> tuple[bool, str]:
        """Non-throwing readiness probe."""
        try:
            with self._lock:
                count = self._connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        except sqlite3.Error:
            return False, "Workflow state store is unavailable"
        return True, f"SQLite store ready with {count} run(s)"

    def create(
        self,
        run: WorkflowRun,
        *,
        history: HistoryDraft,
        audit: Sequence[AuditDraft] = (),
    ) -> WorkflowRun:
        """Insert a new run with its first transition and audit events."""
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
                (
                    str(run.id),
                    run.template_id,
                    run.feature_id,
                    run.state.value,
                    run.created_at.isoformat(),
                    run.updated_at.isoformat(),
                    run.model_dump_json(),
                ),
            )
            entries = self._append(connection, run, [history], audit)
        self._mirror(entries)
        return run

    def get(self, run_id: UUID) -> tuple[WorkflowRun, int]:
        """Return the current snapshot and its version."""
        with self._lock:
            try:
                row = self._connection.execute(
                    "SELECT document, version FROM runs WHERE id = ?", (str(run_id),)
                ).fetchone()
            except sqlite3.Error as exc:
                raise StoreUnavailableError("Workflow state store is unavailable") from exc
        if row is None:
            raise RunNotFoundError(f"Workflow run {run_id} does not exist")
        return WorkflowRun.model_validate_json(row[0]), int(row[1])

    def save(
        self,
        run: WorkflowRun,
        *,
        expected_version: int,
        history: Sequence[HistoryDraft] = (),
        audit: Sequence[AuditDraft] = (),
    ) -> int:
        """Replace the snapshot if nobody changed it since ``expected_version``."""
        with self._transaction() as connection:
            cursor = connection.execute(
                "UPDATE runs SET state = ?, updated_at = ?, version = version + 1, document = ? "
                "WHERE id = ? AND version = ?",
                (
                    run.state.value,
                    run.updated_at.isoformat(),
                    run.model_dump_json(),
                    str(run.id),
                    expected_version,
                ),
            )
            if cursor.rowcount != 1:
                raise ConcurrentUpdateError("Workflow run was concurrently updated")
            entries = self._append(connection, run, history, audit)
        self._mirror(entries)
        return expected_version + 1

    def append_audit(self, run: WorkflowRun, drafts: Sequence[AuditDraft]) -> None:
        """Record coordination events without changing the run snapshot."""
        with self._transaction() as connection:
            entries = self._append(connection, run, (), drafts)
        self._mirror(entries)

    def list_runs(
        self,
        *,
        template_id: str | None = None,
        feature_id: str | None = None,
        state: str | None = None,
        limit: int = 20,
    ) -> list[WorkflowRun]:
        """Newest-first runs, optionally filtered."""
        parameters = (
            template_id,
            template_id,
            feature_id,
            feature_id,
            state,
            state,
            limit,
        )
        with self._lock:
            try:
                rows = self._connection.execute(_LIST_RUNS, parameters).fetchall()
            except sqlite3.Error as exc:
                raise StoreUnavailableError("Workflow state store is unavailable") from exc
        return [WorkflowRun.model_validate_json(row[0]) for row in rows]

    def active_runs(self) -> list[WorkflowRun]:
        """Runs whose agents were working (used to recover after a restart)."""
        with self._lock:
            rows = self._connection.execute(
                "SELECT document FROM runs WHERE state IN (?, ?, ?)",
                tuple(state.value for state in sorted(ACTIVE_WORKFLOW_STATES)),
            ).fetchall()
        return [WorkflowRun.model_validate_json(row[0]) for row in rows]

    def history(self, run_id: UUID, *, after: int = 0) -> tuple[WorkflowHistoryEntry, ...]:
        """Transitions for a run in sequence order, optionally only those after ``after``."""
        return tuple(
            WorkflowHistoryEntry.model_validate_json(document)
            for document in self._documents("history", run_id, after)
        )

    def audit(self, run_id: UUID, *, after: int = 0) -> tuple[CoordinationAuditEntry, ...]:
        """Coordination events for a run in sequence order, optionally only after ``after``."""
        return tuple(
            CoordinationAuditEntry.model_validate_json(document)
            for document in self._documents("audit", run_id, after)
        )

    def _documents(self, table: str, run_id: UUID, after: int = 0) -> list[str]:
        with self._lock:
            try:
                rows = self._connection.execute(
                    _SELECT_DOCUMENTS[table], (str(run_id), after)
                ).fetchall()
            except sqlite3.Error as exc:
                raise StoreUnavailableError("Workflow state store is unavailable") from exc
        return [row[0] for row in rows]

    def _append(
        self,
        connection: sqlite3.Connection,
        run: WorkflowRun,
        history: Sequence[HistoryDraft],
        audit: Sequence[AuditDraft],
    ) -> list[tuple[str, str]]:
        written: list[tuple[str, str]] = []
        at = self._clock()
        for draft in history:
            sequence = self._next_sequence(connection, "history", run.id)
            entry = WorkflowHistoryEntry(
                sequence=sequence,
                run_id=run.id,
                request_id=draft.request_id or run.request_id,
                at=at,
                from_state=draft.from_state,
                to_state=draft.to_state,
                round=run.round,
                actor=draft.actor,
                role=draft.role,
                reason=draft.reason[:500],
            )
            document = entry.model_dump_json()
            connection.execute(
                "INSERT INTO history VALUES (?, ?, ?)", (str(run.id), sequence, document)
            )
            written.append((HISTORY_FILE, document))
        for audit_draft in audit:
            sequence = self._next_sequence(connection, "audit", run.id)
            audit_entry = CoordinationAuditEntry(
                sequence=sequence,
                run_id=run.id,
                request_id=audit_draft.request_id or run.request_id,
                at=at,
                event=audit_draft.event,
                role=audit_draft.role,
                actor=audit_draft.actor,
                round=run.round,
                detail=audit_draft.detail,
            )
            document = audit_entry.model_dump_json()
            connection.execute(
                "INSERT INTO audit VALUES (?, ?, ?)", (str(run.id), sequence, document)
            )
            written.append((AUDIT_FILE, document))
        return written

    @staticmethod
    def _next_sequence(connection: sqlite3.Connection, table: str, run_id: UUID) -> int:
        row = connection.execute(_NEXT_SEQUENCE[table], (str(run_id),)).fetchone()
        return int(row[0])

    def _mirror(self, entries: Sequence[tuple[str, str]]) -> None:
        """Append committed entries to the JSONL evidence files (best effort, ordered)."""
        if not entries:
            return
        with self._lock:
            for filename in (HISTORY_FILE, AUDIT_FILE):
                lines = [document for name, document in entries if name == filename]
                if not lines:
                    continue
                with (self._directory / filename).open("a", encoding="utf-8") as stream:
                    stream.write("".join(f"{line}\n" for line in lines))


def jsonl(entries: Sequence[WorkflowHistoryEntry] | Sequence[CoordinationAuditEntry]) -> str:
    """Render entries as JSON Lines, one compact object per line."""
    return "".join(
        f"{json.dumps(entry.model_dump(mode='json'), sort_keys=True)}\n" for entry in entries
    )
