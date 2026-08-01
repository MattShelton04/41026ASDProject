"""Tests for deterministic run budgets and cancellation intent."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from agent_core import (
    RunLimitExceededError,
    create_run,
    ensure_within_limits,
    request_cancellation,
    transition_run,
)
from shared_contracts import AgentRun, AgentRunRequest, RunLimits, RunStatus

NOW = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)


def _run() -> AgentRun:
    return create_run(
        AgentRunRequest(
            feature_key="student-1-feature",
            objective="Find verified records",
            limits=RunLimits(max_iterations=2, max_tool_calls=3, time_budget_ms=1_000),
        ),
        run_id=uuid4(),
        request_id="request-1",
        now=NOW,
    )


@pytest.mark.parametrize(
    ("updates", "now", "message"),
    [
        ({"iteration_count": 2}, NOW, "iterations limit reached"),
        ({"tool_call_count": 3}, NOW, "tool_calls limit reached"),
        ({}, NOW + timedelta(seconds=1), "time limit reached"),
    ],
)
def test_each_budget_is_a_hard_stop(updates: dict[str, int], now: datetime, message: str) -> None:
    run = _run().model_copy(update=updates)

    with pytest.raises(RunLimitExceededError, match=message):
        ensure_within_limits(run, now=now)


def test_queued_cancellation_is_immediate_and_idempotent() -> None:
    cancelled = request_cancellation(_run(), now=NOW)

    assert cancelled.status is RunStatus.CANCELLED
    assert cancelled.cancel_requested is True
    assert request_cancellation(cancelled, now=NOW + timedelta(seconds=1)) is cancelled


def test_active_cancellation_records_intent_until_a_safe_boundary() -> None:
    planning = transition_run(_run(), RunStatus.PLANNING, now=NOW)

    requested = request_cancellation(planning, now=NOW + timedelta(seconds=1))

    assert requested.status is RunStatus.PLANNING
    assert requested.cancel_requested is True
    assert requested.version == planning.version + 1
