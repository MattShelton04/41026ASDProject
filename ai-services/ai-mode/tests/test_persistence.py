"""Component tests for the owned SQLite workflow store."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from agent_core import ConcurrentRunUpdateError, create_run, transition_run
from ai_mode.persistence import SQLiteRunStore
from ai_mode.persistence.sqlite import PersistenceError
from shared_contracts import (
    AgentRunRequest,
    AgentStep,
    RunStatus,
    StepPhase,
    StepStatus,
    ToolError,
)

NOW = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)


def _store(tmp_path: Path) -> SQLiteRunStore:
    store = SQLiteRunStore(tmp_path / "agent-state.sqlite3")
    store.initialize()
    return store


def _run():  # type: ignore[no-untyped-def]
    return create_run(
        AgentRunRequest(feature_key="student-1-feature", objective="Find records"),
        run_id=uuid4(),
        request_id="request-1",
        now=NOW,
    )


def test_initialize_and_round_trip_run(tmp_path: Path) -> None:
    store = _store(tmp_path)
    run = _run()

    store.create(run)

    assert store.get(run.id) is not None
    assert store.get(run.id).run == run  # type: ignore[union-attr]
    assert store.health().ready is True


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


def test_list_resumable_excludes_terminal_and_review_blocked_runs(tmp_path: Path) -> None:
    store = _store(tmp_path)
    queued = _run()
    terminal = _run()
    store.create(queued)
    store.create(terminal)
    planning = transition_run(terminal, RunStatus.PLANNING, now=NOW)
    store.save(planning, expected_version=terminal.version)
    failed = transition_run(
        planning,
        RunStatus.FAILED,
        now=NOW,
        error=ToolError(code="test_failure", message="Expected test failure"),
    )
    store.save(failed, expected_version=planning.version)

    resumable = store.list_resumable()

    assert [detail.run.id for detail in resumable] == [queued.id]
