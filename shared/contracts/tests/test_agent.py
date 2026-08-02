"""Contract tests for domain-neutral agent harness payloads."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from shared_contracts import (
    Adaptation,
    AdaptationDecision,
    AgentRunRequest,
    ApprovalStatus,
    Plan,
    PlanAction,
    ToolCall,
    ToolError,
    ToolOutcome,
    ToolResult,
)


def test_agent_request_rejects_unknown_and_unbounded_values() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AgentRunRequest(
            feature_key="student-1-feature",
            objective="Find matching records",
            unexpected=True,  # type: ignore[call-arg]
        )

    with pytest.raises(ValidationError, match="String should have at most 4000 characters"):
        AgentRunRequest(feature_key="student-1-feature", objective="x" * 4_001)

    with pytest.raises(ValidationError, match=r"default\.v1"):
        AgentRunRequest(
            feature_key="student-1-feature",
            objective="Find matching records",
            prompt_set="unregistered.v1",  # type: ignore[arg-type]
        )


def test_plan_requires_unambiguous_contiguous_action_order() -> None:
    with pytest.raises(ValidationError, match="action sequences must be contiguous"):
        Plan(
            goal="Find records",
            actions=(
                PlanAction(
                    sequence=2,
                    tool_name="student_1.records.search.v1",
                    purpose="Search the feature-owned records",
                ),
            ),
            success_criteria=("At least one verified match",),
            risk_level="low",
        )


def test_tool_result_requires_error_only_for_unsuccessful_outcome() -> None:
    call_id = uuid4()
    with pytest.raises(ValidationError, match="unsuccessful tool results must contain an error"):
        ToolResult(call_id=call_id, outcome=ToolOutcome.TIMED_OUT, duration_ms=500)

    with pytest.raises(ValidationError, match="successful tool results cannot contain an error"):
        ToolResult(
            call_id=call_id,
            outcome=ToolOutcome.SUCCEEDED,
            duration_ms=5,
            error=ToolError(code="unexpected", message="should not be here"),
        )


def test_completion_requires_a_final_result() -> None:
    with pytest.raises(ValidationError, match="complete adaptations require a final_result"):
        Adaptation(
            decision=AdaptationDecision.COMPLETE,
            justification="All deterministic criteria passed",
        )


def test_write_call_contract_retains_idempotency_and_approval_metadata() -> None:
    run_id = uuid4()
    call = ToolCall(
        id=uuid4(),
        run_id=run_id,
        step_id=uuid4(),
        tool_name="student_1.records.update.v1",
        tool_version="v1",
        arguments={"record_id": 1},
        idempotency_key=f"{run_id}:1",
        approval_status=ApprovalStatus.APPROVED,
    )

    assert call.model_dump(mode="json")["approval_status"] == "approved"


def test_tool_call_rejects_zero_w3c_trace_identifiers() -> None:
    with pytest.raises(ValidationError, match="non-zero trace and parent identifiers"):
        ToolCall(
            id=uuid4(),
            run_id=uuid4(),
            step_id=uuid4(),
            traceparent="00-" + "0" * 32 + "-00f067aa0ba902b7-01",
            tool_name="student_1.records.search.v1",
            tool_version="v1",
            approval_status=ApprovalStatus.NOT_REQUIRED,
        )
