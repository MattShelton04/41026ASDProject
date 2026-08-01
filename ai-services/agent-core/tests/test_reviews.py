"""Tests for the atomic human-review decision policy."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from agent_core import AgentCoreError, apply_human_review, create_run, transition_run
from shared_contracts import (
    AgentRunDetail,
    AgentRunRequest,
    AgentStep,
    ApprovalStatus,
    HumanReviewRequest,
    ReviewDecision,
    RunStatus,
    StepPhase,
    StepStatus,
    ToolCall,
)

NOW = datetime(2026, 8, 1, tzinfo=UTC)


def _detail() -> AgentRunDetail:
    run = create_run(
        AgentRunRequest(feature_key="student-1-feature", objective="Delete a record"),
        run_id=uuid4(),
        request_id="request-1",
        now=NOW,
    )
    planning = transition_run(run, RunStatus.PLANNING, now=NOW)
    ready = transition_run(planning, RunStatus.READY, now=NOW)
    review_required = transition_run(ready, RunStatus.REVIEW_REQUIRED, now=NOW)
    step_id = uuid4()
    call = ToolCall(
        id=uuid4(),
        run_id=run.id,
        step_id=step_id,
        tool_name="student_1.records.delete.v1",
        tool_version="v1",
        arguments={"record_id": 1},
        idempotency_key=f"{run.id}:1:v1",
        approval_status=ApprovalStatus.PENDING,
    )
    step = AgentStep(
        id=step_id,
        run_id=run.id,
        sequence=2,
        phase=StepPhase.ACT,
        status=StepStatus.PENDING,
        input={"tool_call": call.model_dump(mode="json")},
    )
    return AgentRunDetail(run=review_required, steps=(step,))


@pytest.mark.parametrize(
    ("decision", "status", "step_status", "approval"),
    [
        (ReviewDecision.APPROVE, RunStatus.READY, StepStatus.PENDING, ApprovalStatus.APPROVED),
        (
            ReviewDecision.REJECT,
            RunStatus.CANCELLED,
            StepStatus.CANCELLED,
            ApprovalStatus.REJECTED,
        ),
    ],
)
def test_review_updates_run_step_and_immutable_audit_together(
    decision: ReviewDecision,
    status: RunStatus,
    step_status: StepStatus,
    approval: ApprovalStatus,
) -> None:
    applied = apply_human_review(
        _detail(),
        HumanReviewRequest(decision=decision, reviewer="reviewer@example.test"),
        review_id=uuid4(),
        now=NOW,
    )

    decided_call = ToolCall.model_validate(applied.step.input["tool_call"])
    assert applied.run.status is status
    assert applied.step.status is step_status
    assert decided_call.approval_status is approval
    assert applied.review.tool_call == decided_call
    assert applied.review.decision is decision


def test_review_is_rejected_when_run_is_not_waiting() -> None:
    detail = _detail()
    not_waiting = detail.model_copy(
        update={"run": detail.run.model_copy(update={"status": RunStatus.READY})}
    )

    with pytest.raises(AgentCoreError, match="not awaiting"):
        apply_human_review(
            not_waiting,
            HumanReviewRequest(decision=ReviewDecision.APPROVE, reviewer="reviewer"),
            review_id=uuid4(),
            now=NOW,
        )
