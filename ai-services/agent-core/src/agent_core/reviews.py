"""Pure human-review policy for protected tool actions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from agent_core.errors import AgentCoreError
from agent_core.state_machine import transition_run
from shared_contracts import (
    AgentRun,
    AgentRunDetail,
    AgentStep,
    ApprovalStatus,
    HumanReview,
    HumanReviewRequest,
    ReviewDecision,
    RunStatus,
    StepPhase,
    StepStatus,
    ToolCall,
)


@dataclass(frozen=True, slots=True)
class ReviewApplication:
    """Atomic state, step, and audit updates produced by one review."""

    run: AgentRun
    step: AgentStep
    review: HumanReview


def apply_human_review(
    detail: AgentRunDetail,
    command: HumanReviewRequest,
    *,
    review_id: UUID,
    now: datetime,
) -> ReviewApplication:
    """Apply one decision to exactly one pending protected action."""
    if detail.run.status is not RunStatus.REVIEW_REQUIRED:
        raise AgentCoreError("agent run is not awaiting human review")
    pending = [
        step
        for step in detail.steps
        if step.phase is StepPhase.ACT and step.status is StepStatus.PENDING
    ]
    if len(pending) != 1:
        raise AgentCoreError("agent run must have exactly one pending protected action")
    step = pending[0]
    try:
        call = ToolCall.model_validate(step.input["tool_call"])
    except (KeyError, ValueError) as exc:
        raise AgentCoreError("pending action has no valid tool call") from exc
    if call.approval_status is not ApprovalStatus.PENDING:
        raise AgentCoreError("protected action has already been decided")

    approval = (
        ApprovalStatus.APPROVED
        if command.decision is ReviewDecision.APPROVE
        else ApprovalStatus.REJECTED
    )
    decided_call = call.evolve(approval_status=approval)
    step_updates: dict[str, object] = {"input": {"tool_call": decided_call.model_dump(mode="json")}}
    if command.decision is ReviewDecision.REJECT:
        step_updates.update({"status": StepStatus.CANCELLED, "completed_at": now})
    decided_step = step.evolve(**step_updates)
    target = RunStatus.READY if command.decision is ReviewDecision.APPROVE else RunStatus.CANCELLED
    decided_run = transition_run(detail.run, target, now=now)
    review = HumanReview(
        id=review_id,
        run_id=detail.run.id,
        step_id=step.id,
        tool_call=decided_call,
        decision=command.decision,
        reviewer=command.reviewer,
        comment=command.comment,
        reviewed_at=now,
    )
    return ReviewApplication(run=decided_run, step=decided_step, review=review)
