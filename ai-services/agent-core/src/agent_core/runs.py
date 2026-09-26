"""Pure creation and cancellation policies for agent runs."""

from datetime import datetime
from uuid import UUID

from agent_core.state_machine import TERMINAL_STATUSES, transition_run
from shared_contracts import AgentRun, AgentRunRequest, RunStatus


def create_run(
    request: AgentRunRequest,
    *,
    run_id: UUID,
    request_id: str,
    now: datetime,
    traceparent: str | None = None,
) -> AgentRun:
    """Create a queued run without performing persistence or external I/O."""
    return AgentRun(
        id=run_id,
        request_id=request_id,
        traceparent=traceparent,
        feature_key=request.feature_key,
        objective=request.objective,
        title=request.title,
        grounding=request.grounding,
        status=RunStatus.QUEUED,
        prompt_set=request.prompt_set,
        model_profile=request.model_profile,
        limits=request.limits,
        tool_allowlist=request.tool_allowlist,
        trusted_identifiers=request.trusted_identifiers,
        created_at=now,
        updated_at=now,
    )


def request_cancellation(run: AgentRun, *, now: datetime) -> AgentRun:
    """Idempotently request cancellation and stop queued work immediately."""
    if run.status in TERMINAL_STATUSES or run.cancel_requested:
        return run
    if run.status is RunStatus.QUEUED:
        cancelled = transition_run(run, RunStatus.CANCELLED, now=now)
        return cancelled.evolve(cancel_requested=True)
    return run.evolve(
        cancel_requested=True,
        updated_at=now,
        version=run.version + 1,
    )
