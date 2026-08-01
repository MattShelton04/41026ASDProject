"""Deterministic run budget enforcement."""

from datetime import datetime
from enum import StrEnum

from agent_core.errors import RunLimitExceededError
from shared_contracts import AgentRun


class LimitKind(StrEnum):
    """Stable identifiers for exhausted run budgets."""

    ITERATIONS = "iterations"
    TOOL_CALLS = "tool_calls"
    TIME = "time"


def ensure_within_limits(run: AgentRun, *, now: datetime) -> None:
    """Reject a run that may not begin another model/tool iteration."""
    if run.iteration_count >= run.limits.max_iterations:
        raise RunLimitExceededError(f"{LimitKind.ITERATIONS.value} limit reached")
    if run.tool_call_count >= run.limits.max_tool_calls:
        raise RunLimitExceededError(f"{LimitKind.TOOL_CALLS.value} limit reached")
    ensure_time_remaining(run, now=now)


def ensure_time_remaining(run: AgentRun, *, now: datetime) -> None:
    """Reject another external-I/O phase after the elapsed-time budget."""
    elapsed_ms = max(0, int((now - run.created_at).total_seconds() * 1_000))
    if elapsed_ms >= run.limits.time_budget_ms:
        raise RunLimitExceededError(f"{LimitKind.TIME.value} limit reached")
