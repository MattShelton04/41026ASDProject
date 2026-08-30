"""Component tests for the owned SQLite workflow store."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from agent_core import ConcurrentRunUpdateError, create_run, transition_run
from ai_mode.operations import RunListQuery
from ai_mode.persistence import IdempotencyConflictError, SQLiteRunStore
from ai_mode.persistence.sqlite import MIGRATION_1, MIGRATION_2, PersistenceError
from shared_contracts import (
    AgentRun,
    AgentRunRequest,
    AgentStep,
    ApprovalStatus,
    HumanReview,
    ReviewDecision,
    RunStatus,
    StepPhase,
    StepStatus,
    ToolCall,
    ToolError,
)

NOW = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)


def _store(tmp_path: Path) -> SQLiteRunStore:
    store = SQLiteRunStore(tmp_path / "agent-state.sqlite3")
    store.initialize()
    return store


def _run() -> AgentRun:
    return create_run(
        AgentRunRequest(feature_key="student-1-feature", objective="Find records"),
        run_id=uuid4(),
        request_id="request-1",
        now=NOW,
    )


def _review_for_step(
    run: AgentRun,
    step: AgentStep,
    *,
    reviewed_at: datetime,
) -> HumanReview:
    call = ToolCall(
        id=uuid4(),
        run_id=run.id,
        step_id=step.id,
        tool_name="records.update.v1",
        tool_version="v1",
        approval_status=ApprovalStatus.APPROVED,
    )
    return HumanReview(
        id=uuid4(),
        run_id=run.id,
        step_id=step.id,
        tool_call=call,
        decision=ReviewDecision.APPROVE,
        reviewer="persistence-test",
        reviewed_at=reviewed_at,
    )


def _save_reviewed_step(
    store: SQLiteRunStore,
    run: AgentRun,
    *,
    sequence: int,
    reviewed_at: datetime,
) -> tuple[AgentRun, AgentStep, HumanReview]:
    step = AgentStep(
        id=uuid4(),
        run_id=run.id,
        sequence=sequence,
        phase=StepPhase.ACT,
        status=StepStatus.SUCCEEDED,
    )
    review = _review_for_step(run, step, reviewed_at=reviewed_at)
    updated = run.evolve(
        status=RunStatus.READY,
        version=run.version + 1,
        updated_at=max(run.updated_at, reviewed_at),
    )
    store.save(
        updated,
        expected_version=run.version,
        step=step,
        review=review,
    )
    return updated, step, review


def test_initialize_and_round_trip_run(tmp_path: Path) -> None:
    store = _store(tmp_path)
    run = _run()

    store.create(run)

    assert store.get(run.id) is not None
    assert store.get(run.id).run == run  # type: ignore[union-attr]
    assert store.health().ready is True
    events = store.list_events(run.id)
    assert len(events) == 1
    assert events[0].event_type == "run.created"
    assert events[0].run_version == 0


def test_run_and_step_updates_are_atomic_and_upsert_the_same_step(tmp_path: Path) -> None:
    store = _store(tmp_path)
    run = _run()
    store.create(run)
    step = AgentStep(
        id=uuid4(),
        run_id=run.id,
        sequence=1,
        phase=StepPhase.PLAN,
        status=StepStatus.RUNNING,
        started_at=NOW,
    )
    planning = transition_run(run, RunStatus.PLANNING, now=NOW)
    store.save(planning, expected_version=run.version, step=step)
    completed = step.model_copy(
        update={"status": StepStatus.SUCCEEDED, "completed_at": NOW, "output": {"ok": True}}
    )
    ready = transition_run(planning, RunStatus.READY, now=NOW)

    store.save(ready, expected_version=planning.version, step=completed)

    detail = store.get(run.id)
    assert detail is not None
    assert detail.run.status is RunStatus.READY
    assert detail.steps == (completed,)


def test_stale_update_does_not_append_its_step(tmp_path: Path) -> None:
    store = _store(tmp_path)
    run = _run()
    store.create(run)
    planning = transition_run(run, RunStatus.PLANNING, now=NOW)
    store.save(planning, expected_version=0)
    stale_step = AgentStep(
        id=uuid4(),
        run_id=run.id,
        sequence=1,
        phase=StepPhase.PLAN,
        status=StepStatus.RUNNING,
    )

    with pytest.raises(ConcurrentRunUpdateError, match="concurrently updated"):
        store.save(planning, expected_version=0, step=stale_step)

    assert store.get(run.id).steps == ()  # type: ignore[union-attr]


def test_step_failure_rolls_back_the_run_update_atomically(tmp_path: Path) -> None:
    store = _store(tmp_path)
    run = _run()
    store.create(run)
    step = AgentStep(
        id=uuid4(),
        run_id=run.id,
        sequence=1,
        phase=StepPhase.PLAN,
        status=StepStatus.RUNNING,
    )
    planning = transition_run(run, RunStatus.PLANNING, now=NOW)
    store.save(planning, expected_version=run.version, step=step)
    ready = transition_run(planning, RunStatus.READY, now=NOW)
    invalid_update = step.model_copy(update={"sequence": 2})

    with pytest.raises(PersistenceError, match="identity or sequence"):
        store.save(ready, expected_version=planning.version, step=invalid_update)

    detail = store.get(run.id)
    assert detail is not None
    assert detail.run == planning
    assert detail.steps == (step,)


def test_cancellation_is_immediate_for_queued_run_and_idempotent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    run = _run()
    store.create(run)

    cancelled = store.request_cancellation(run.id, now=NOW + timedelta(seconds=1))
    again = store.request_cancellation(run.id, now=NOW + timedelta(seconds=2))

    assert cancelled is not None
    assert cancelled.status is RunStatus.CANCELLED
    assert again == cancelled


def test_list_resumable_handles_empty_and_single_active_store(tmp_path: Path) -> None:
    store = _store(tmp_path)

    assert store.list_resumable() == ()

    queued = _run()
    store.create(queued)

    resumable = store.list_resumable()

    assert [detail.run.id for detail in resumable] == [queued.id]


def test_list_resumable_orders_multiple_active_runs_stably(tmp_path: Path) -> None:
    store = _store(tmp_path)
    later = create_run(
        AgentRunRequest(feature_key="student-1-feature", objective="Later"),
        run_id=UUID(int=1),
        request_id="later",
        now=NOW + timedelta(seconds=1),
    )
    same_time_second = create_run(
        AgentRunRequest(feature_key="student-1-feature", objective="Second"),
        run_id=UUID(int=3),
        request_id="same-time-second",
        now=NOW,
    )
    same_time_first = create_run(
        AgentRunRequest(feature_key="student-1-feature", objective="First"),
        run_id=UUID(int=2),
        request_id="same-time-first",
        now=NOW,
    )
    for run in (later, same_time_second, same_time_first):
        store.create(run)

    resumable = store.list_resumable()

    assert [detail.run.id for detail in resumable] == [
        same_time_first.id,
        same_time_second.id,
        later.id,
    ]


def test_list_resumable_excludes_terminal_and_review_blocked_runs(tmp_path: Path) -> None:
    store = _store(tmp_path)
    queued = _run()
    excluded = (
        _run().evolve(status=RunStatus.REVIEW_REQUIRED),
        _run().evolve(status=RunStatus.SUCCEEDED, final_result={"summary": "done"}),
        _run().evolve(
            status=RunStatus.FAILED,
            error=ToolError(code="test_failure", message="Expected test failure"),
        ),
        _run().evolve(status=RunStatus.CANCELLED),
    )
    for run in (queued, *excluded):
        store.create(run)

    resumable = store.list_resumable()

    assert [detail.run.id for detail in resumable] == [queued.id]


def test_list_resumable_preserves_step_and_review_order(tmp_path: Path) -> None:
    store = _store(tmp_path)
    run = _run()
    store.create(run)
    run, later_step, later_review = _save_reviewed_step(
        store,
        run,
        sequence=2,
        reviewed_at=NOW + timedelta(seconds=2),
    )
    _, earlier_step, earlier_review = _save_reviewed_step(
        store,
        run,
        sequence=1,
        reviewed_at=NOW + timedelta(seconds=1),
    )

    detail = store.list_resumable()[0]

    assert detail.steps == (earlier_step, later_step)
    assert detail.reviews == (earlier_review, later_review)


@pytest.mark.parametrize("corrupted_table", ["agent_runs", "agent_steps", "human_reviews"])
def test_list_resumable_fails_closed_for_malformed_aggregate_rows(
    tmp_path: Path,
    corrupted_table: str,
) -> None:
    store = _store(tmp_path)
    run = _run()
    store.create(run)
    run, _, _ = _save_reviewed_step(
        store,
        run,
        sequence=1,
        reviewed_at=NOW + timedelta(seconds=1),
    )
    statements = {
        "agent_runs": "UPDATE agent_runs SET payload_json = '{}' WHERE id = ?",
        "agent_steps": "UPDATE agent_steps SET payload_json = '{}' WHERE run_id = ?",
        "human_reviews": "UPDATE human_reviews SET payload_json = '{}' WHERE run_id = ?",
    }
    with sqlite3.connect(tmp_path / "agent-state.sqlite3") as connection:
        connection.execute(statements[corrupted_table], (str(run.id),))

    with pytest.raises(PersistenceError, match=f"stored agent run is invalid: {run.id}"):
        store.list_resumable()


@pytest.mark.parametrize("run_count", [0, 1, 4])
def test_list_resumable_uses_one_connection_and_three_selects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    run_count: int,
) -> None:
    store = _store(tmp_path)
    for index in range(run_count):
        store.create(
            create_run(
                AgentRunRequest(feature_key="student-1-feature", objective=f"Run {index}"),
                run_id=UUID(int=index + 1),
                request_id=f"run-{index}",
                now=NOW,
            )
        )
    statements: list[str] = []
    connection_count = 0
    original_connect = store._connect

    def traced_connect() -> sqlite3.Connection:
        nonlocal connection_count
        connection_count += 1
        connection = original_connect()
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(store, "_connect", traced_connect)

    store.list_resumable()

    selects = [
        statement for statement in statements if statement.lstrip().upper().startswith("SELECT")
    ]
    assert connection_count == 1
    assert len(selects) == 3


def test_create_idempotency_returns_original_and_rejects_argument_mismatch(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    original = _run()
    duplicate = _run()

    created, was_created = store.create_or_get(
        original,
        idempotency_key="create-key",
        request_hash="a" * 64,
    )
    replayed, replay_created = store.create_or_get(
        duplicate,
        idempotency_key="create-key",
        request_hash="a" * 64,
    )

    assert was_created is True
    assert replay_created is False
    assert replayed == created == original
    assert store.get(duplicate.id) is None
    with pytest.raises(IdempotencyConflictError, match="different run request"):
        store.create_or_get(
            duplicate,
            idempotency_key="create-key",
            request_hash="b" * 64,
        )


def test_schema_one_database_is_forward_migrated_with_existing_run(tmp_path: Path) -> None:
    path = tmp_path / "old.sqlite3"
    run = _run()
    with sqlite3.connect(path) as connection:
        connection.executescript(MIGRATION_1)
        connection.execute("PRAGMA user_version = 1")
        connection.execute(
            """
            INSERT INTO agent_runs (id, version, status, updated_at, payload_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                str(run.id),
                run.version,
                run.status.value,
                run.updated_at.isoformat(),
                json.dumps(run.model_dump(mode="json")),
            ),
        )

    store = SQLiteRunStore(path)
    store.initialize()

    assert store.get(run.id) is not None
    assert store.health().detail == "schema version 3"
    assert store.list_events(run.id) == ()

    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(agent_runs)")}
        indexes = {row[1] for row in connection.execute("PRAGMA index_list(agent_runs)")}
        indexed = connection.execute(
            "SELECT created_at, feature_key, model_profile FROM agent_runs WHERE id = ?",
            (str(run.id),),
        ).fetchone()
    assert {"created_at", "feature_key", "model_profile"}.issubset(columns)
    assert {
        "ix_agent_runs_created_id",
        "ix_agent_runs_status_created_id",
        "ix_agent_runs_feature_created_id",
    }.issubset(indexes)
    assert indexed == (run.created_at.isoformat(), run.feature_key, run.model_profile)


def test_run_snapshot_query_filters_and_pages_stably(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = create_run(
        AgentRunRequest(feature_key="student-1-feature", objective="First"),
        run_id=UUID(int=1),
        request_id="first",
        now=NOW,
    )
    second = create_run(
        AgentRunRequest(feature_key="student-2-feature", objective="Second"),
        run_id=UUID(int=2),
        request_id="second",
        now=NOW,
    )
    third = create_run(
        AgentRunRequest(feature_key="student-1-feature", objective="Third"),
        run_id=UUID(int=3),
        request_id="third",
        now=NOW,
    )
    for run in (first, second, third):
        store.create(run)

    page, has_more = store.list_run_snapshots(RunListQuery(limit=2))
    inserted_between_pages = create_run(
        AgentRunRequest(feature_key="student-3-feature", objective="Inserted"),
        run_id=UUID(int=4),
        request_id="inserted",
        now=NOW,
    )
    store.create(inserted_between_pages)
    filtered, filtered_more = store.list_run_snapshots(
        RunListQuery(feature_key="student-1-feature", limit=10)
    )
    next_page, next_more = store.list_run_snapshots(
        RunListQuery(
            cursor_created_at=page[-1].run.created_at,
            cursor_id=page[-1].run.id,
            limit=2,
        )
    )

    assert [snapshot.run.id for snapshot in page] == [third.id, second.id]
    assert has_more is True
    assert [snapshot.run.id for snapshot in filtered] == [third.id, first.id]
    assert filtered_more is False
    assert [snapshot.run.id for snapshot in next_page] == [first.id]
    assert next_more is False

    with sqlite3.connect(tmp_path / "agent-state.sqlite3") as connection:
        query_plan = connection.execute(
            """
            EXPLAIN QUERY PLAN SELECT id FROM agent_runs
            WHERE feature_key = ? ORDER BY created_at DESC, id DESC LIMIT 10
            """,
            ("student-1-feature",),
        ).fetchall()
    assert any("ix_agent_runs_feature_created_id" in str(row) for row in query_plan)


def test_schema_two_migration_fails_closed_for_invalid_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "invalid-v2.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript(MIGRATION_1)
        connection.executescript(MIGRATION_2)
        connection.execute("PRAGMA user_version = 2")
        connection.execute(
            """
            INSERT INTO agent_runs (id, version, status, updated_at, payload_json)
            VALUES (?, 0, 'queued', ?, ?)
            """,
            (str(uuid4()), NOW.isoformat(), json.dumps({"invalid": True})),
        )

    with pytest.raises(PersistenceError, match="cannot be indexed"):
        SQLiteRunStore(path).initialize()

    with sqlite3.connect(path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        columns = {row[1] for row in connection.execute("PRAGMA table_info(agent_runs)")}
    assert version == 2
    assert "created_at" not in columns


def test_health_rejects_incomplete_schema_even_when_version_matches(tmp_path: Path) -> None:
    path = tmp_path / "incomplete.sqlite3"
    store = SQLiteRunStore(path)
    store.initialize()
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE run_events")

    health = store.health()

    assert health.ready is False
    assert health.detail == "schema is missing tables: run_events"


def test_sqlite_failures_are_translated_to_the_persistence_boundary(tmp_path: Path) -> None:
    path = tmp_path / "broken.sqlite3"
    store = SQLiteRunStore(path)
    store.initialize()
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE run_events")

    with pytest.raises(PersistenceError, match="SQLite operation failed: OperationalError"):
        store.list_events(uuid4())


def test_connection_failures_are_translated_to_the_persistence_boundary(tmp_path: Path) -> None:
    invalid_database_path = tmp_path / "database-directory"
    invalid_database_path.mkdir()
    store = SQLiteRunStore(invalid_database_path)

    with pytest.raises(PersistenceError, match="SQLite connection failed: OperationalError"):
        store.initialize()

    health = store.health()
    assert health.ready is False
    assert health.detail == "SQLite unavailable: OperationalError"
