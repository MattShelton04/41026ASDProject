"""Pure transition policy for persisted agent runs."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from pydantic import JsonValue

from agent_core.errors import InvalidStateTransitionError
from shared_contracts import AgentRun, RunStatus, ToolError

TERMINAL_STATUSES = frozenset(
    {
        RunStatus.SUCCEEDED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    }
)

ALLOWED_TRANSITIONS: Mapping[RunStatus, frozenset[RunStatus]] = {
    RunStatus.QUEUED: frozenset({RunStatus.PLANNING, RunStatus.CANCELLED}),
    RunStatus.PLANNING: frozenset({RunStatus.READY, RunStatus.FAILED, RunStatus.CANCELLED}),
    RunStatus.READY: frozenset(
        {RunStatus.ACTING, RunStatus.REVIEW_REQUIRED, RunStatus.CANCELLED, RunStatus.FAILED}
    ),
    RunStatus.ACTING: frozenset(
        {
            RunStatus.READY,
            RunStatus.OBSERVING,
            RunStatus.REVIEW_REQUIRED,
            RunStatus.FAILED,
        }
    ),
    RunStatus.OBSERVING: frozenset({RunStatus.ADAPTING, RunStatus.FAILED}),
    RunStatus.ADAPTING: frozenset(
        {
            RunStatus.READY,
            RunStatus.PLANNING,
            RunStatus.REVIEW_REQUIRED,
            RunStatus.SUCCEEDED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }
    ),
    RunStatus.REVIEW_REQUIRED: frozenset({RunStatus.READY, RunStatus.CANCELLED, RunStatus.FAILED}),
    RunStatus.SUCCEEDED: frozenset(),
    RunStatus.FAILED: frozenset(),
    RunStatus.CANCELLED: frozenset(),
}


def can_transition(current: RunStatus, target: RunStatus) -> bool:
    """Return whether the explicit transition graph permits the change."""
    return target in ALLOWED_TRANSITIONS[current]


def transition_run(
    run: AgentRun,
    target: RunStatus,
    *,
    now: datetime,
    final_result: Mapping[str, JsonValue] | None = None,
    error: ToolError | None = None,
) -> AgentRun:
    """Return the next immutable-style run snapshot after checking invariants."""
    if not can_transition(run.status, target):
        raise InvalidStateTransitionError(
            f"run cannot transition from {run.status.value} to {target.value}"
        )
    if target is RunStatus.SUCCEEDED and final_result is None:
        raise InvalidStateTransitionError("succeeded runs require a final result")
    if target is not RunStatus.SUCCEEDED and final_result is not None:
        raise InvalidStateTransitionError("only succeeded runs may set a final result")
    if target is RunStatus.FAILED and error is None:
        raise InvalidStateTransitionError("failed runs require a structured error")
    if target is not RunStatus.FAILED and error is not None:
        raise InvalidStateTransitionError("only failed runs may set an error")

    return run.evolve(
        status=target,
        updated_at=now,
        version=run.version + 1,
        final_result=dict(final_result) if final_result is not None else None,
        error=error,
    )
