"""Contract tests for domain-neutral agent harness payloads."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from shared_contracts import (
    Adaptation,
    AdaptationDecision,
    AgentRun,
    AgentRunDetail,
    AgentRunRequest,
    AgentStep,
    ApprovalStatus,
    Plan,
    PlanAction,
    RunLimits,
    RunStatus,
    StepPhase,
    StepStatus,
    ToolCall,
    ToolError,
    ToolOutcome,
    ToolResult,
    TrustedIdentifier,
)

NOW = datetime(2026, 8, 9, tzinfo=UTC)


def _run(**changes: object) -> AgentRun:
    values: dict[str, object] = {
        "id": uuid4(),
        "request_id": "contract-test",
        "feature_key": "student-1-feature",
        "objective": "Validate immutable run state",
        "status": RunStatus.QUEUED,
        "prompt_set": "default.v3",
        "model_profile": "remote-standard.v1",
        "limits": RunLimits(),
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(changes)
    return AgentRun.model_validate(values)


def test_agent_request_rejects_unknown_and_unbounded_values() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AgentRunRequest(
            feature_key="student-1-feature",
            objective="Find matching records",
            unexpected=True,  # type: ignore[call-arg]
        )

    with pytest.raises(ValidationError, match="String should have at most 16000 characters"):
        AgentRunRequest(feature_key="student-1-feature", objective="x" * 16_001)

    with pytest.raises(ValidationError, match=r"default\.v1"):
        AgentRunRequest(
            feature_key="student-1-feature",
            objective="Find matching records",
            prompt_set="unregistered.v1",  # type: ignore[arg-type]
        )

    assert (
        AgentRunRequest(
            feature_key="student-1-feature",
            objective="Use bounded explicit conversation context",
            prompt_set="default.v5",
        ).prompt_set
        == "default.v5"
    )

    with pytest.raises(ValidationError, match="tool_allowlist entries must be unique"):
        AgentRunRequest(
            feature_key="student-1-feature",
            objective="Find matching records",
            tool_allowlist=("records.read.v1", "records.read.v1"),
        )

    trusted = TrustedIdentifier(kind="record_ref", value=uuid4())
    with pytest.raises(ValidationError, match="trusted_identifiers entries must be unique"):
        AgentRunRequest(
            feature_key="student-1-feature",
            objective="Inspect a record",
            trusted_identifiers=(trusted, trusted),
        )
    with pytest.raises(ValidationError, match="at most 100 items"):
        AgentRunRequest(
            feature_key="student-1-feature",
            objective="Inspect bounded records",
            trusted_identifiers=tuple(
                TrustedIdentifier(kind="record_ref", value=UUID(int=index + 1))
                for index in range(101)
            ),
        )


def test_legacy_run_snapshot_loads_with_an_empty_trust_ledger() -> None:
    payload = _run().model_dump(mode="json")
    payload.pop("trusted_identifiers")

    assert AgentRun.model_validate(payload).trusted_identifiers == ()


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


def test_plan_allows_ordered_actions_in_the_same_contiguous_stage() -> None:
    plan = Plan(
        goal="Gather independent evidence",
        actions=(
            PlanAction(sequence=1, tool_name="records.a.v1", purpose="Read A"),
            PlanAction(sequence=1, tool_name="records.b.v1", purpose="Read B"),
            PlanAction(sequence=2, tool_name="records.c.v1", purpose="Read C later"),
        ),
        success_criteria=("All evidence is returned",),
        risk_level="low",
    )

    assert [action.sequence for action in plan.actions] == [1, 1, 2]
    with pytest.raises(ValidationError, match="and ordered"):
        plan.evolve(
            actions=(
                PlanAction(sequence=1, tool_name="records.a.v1", purpose="Read A"),
                PlanAction(sequence=2, tool_name="records.c.v1", purpose="Read C"),
                PlanAction(sequence=1, tool_name="records.b.v1", purpose="Read B"),
            )
        )


def test_expanded_run_limit_defaults_and_bounds_are_contractual() -> None:
    limits = RunLimits()

    assert limits.max_tool_calls == 30
    assert limits.max_iterations == 10
    assert limits.time_budget_ms == 180_000
    assert limits.max_parallel_tools == 10
    with pytest.raises(ValidationError):
        RunLimits(max_parallel_tools=26)
    with pytest.raises(ValidationError):
        RunLimits(max_tool_calls=101)


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


def test_immutable_updates_are_revalidated() -> None:
    run = _run()

    with pytest.raises(ValidationError, match="valid integer"):
        run.evolve(iteration_count="invalid")
    with pytest.raises(ValidationError, match="must not exceed max_iterations"):
        run.model_copy(update={"iteration_count": run.limits.max_iterations + 1})


def test_run_rejects_naive_or_inconsistent_lifecycle_state() -> None:
    with pytest.raises(ValidationError, match="timezone info"):
        _run(created_at=datetime(2026, 8, 9), updated_at=datetime(2026, 8, 9))
    with pytest.raises(ValidationError, match="updated_at must not be earlier"):
        _run(updated_at=NOW - timedelta(seconds=1))
    with pytest.raises(ValidationError, match="only succeeded runs require a final_result"):
        _run(status=RunStatus.SUCCEEDED)
    with pytest.raises(ValidationError, match="only failed runs require an error"):
        _run(status=RunStatus.FAILED)


def test_step_and_detail_reject_impossible_aggregate_state() -> None:
    run = _run()
    with pytest.raises(ValidationError, match="completed_at must not be earlier"):
        AgentStep(
            id=uuid4(),
            run_id=run.id,
            sequence=1,
            phase=StepPhase.PLAN,
            status=StepStatus.SUCCEEDED,
            started_at=NOW,
            completed_at=NOW - timedelta(milliseconds=1),
        )

    later = AgentStep(
        id=uuid4(),
        run_id=run.id,
        sequence=2,
        phase=StepPhase.ACT,
        status=StepStatus.PENDING,
    )
    earlier = AgentStep(
        id=uuid4(),
        run_id=run.id,
        sequence=1,
        phase=StepPhase.PLAN,
        status=StepStatus.SUCCEEDED,
    )
    with pytest.raises(ValidationError, match="step sequences must be unique and ordered"):
        AgentRunDetail(run=run, steps=(later, earlier))

    foreign = earlier.evolve(run_id=uuid4())
    with pytest.raises(ValidationError, match="every step must belong"):
        AgentRunDetail(run=run, steps=(foreign,))
