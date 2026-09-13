"""Unit tests for cursor stability and safe operations evidence projection."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from agent_core import create_run
from ai_mode.operations import (
    EvidencePolicy,
    InvalidRunCursorError,
    OperationsService,
    RunListQuery,
    RunSnapshot,
    decode_run_cursor,
    encode_run_cursor,
)
from shared_contracts import (
    AgentRunDetail,
    AgentRunRequest,
    AgentStep,
    ApprovalStatus,
    HumanReview,
    ReviewDecision,
    RunStatus,
    StepPhase,
    StepStatus,
    ToolCall,
    ToolOutcome,
    ToolResult,
)

NOW = datetime(2026, 8, 2, 3, 4, 5, tzinfo=UTC)


class StubReader:
    def __init__(self, detail: AgentRunDetail, *, has_more: bool = False) -> None:
        self.detail = detail
        self.has_more = has_more

    def list_run_snapshots(self, query: RunListQuery) -> tuple[tuple[RunSnapshot, ...], bool]:
        return (RunSnapshot(run=self.detail.run),), self.has_more

    def get(self, run_id: UUID) -> AgentRunDetail | None:
        return self.detail if run_id == self.detail.run.id else None


def _detail() -> AgentRunDetail:
    run = create_run(
        AgentRunRequest(
            feature_key="student-1-feature",
            objective="Inspect records with token=super-secret-value",
        ),
        run_id=uuid4(),
        request_id="operations-request",
        now=NOW,
        traceparent="00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
    )
    plan_step = AgentStep(
        id=uuid4(),
        run_id=run.id,
        sequence=1,
        phase=StepPhase.PLAN,
        status=StepStatus.SUCCEEDED,
        started_at=NOW,
        completed_at=NOW + timedelta(milliseconds=25),
        output={
            "plan": {
                "goal": "Inspect matching records",
                "actions": [
                    {
                        "sequence": 1,
                        "tool_name": "records.search.v1",
                        "arguments": {"password": "do-not-display"},
                        "purpose": "Find matching records",
                    }
                ],
                "success_criteria": ["A match is observed"],
                "risk_level": "low",
                "assumptions": [],
            },
            "model_invocation": {
                "provider": "scripted",
                "model": "test-model",
                "model_digest": None,
                "metrics": {
                    "total_duration_ms": 20,
                    "load_duration_ms": 2,
                    "prompt_eval_duration_ms": 5,
                    "eval_duration_ms": 13,
                    "prompt_tokens": 25,
                    "output_tokens": 10,
                },
                "prompt_id": "planner",
                "prompt_version": "v1",
                "prompt_hash": "a" * 64,
                "rendered_input_hash": "b" * 64,
                "repair_count": 2,
                "provider_retry_count": 1,
            },
        },
    )
    act_step_id = uuid4()
    call = ToolCall(
        id=uuid4(),
        run_id=run.id,
        step_id=act_step_id,
        request_id=run.request_id,
        tool_name="records.search.v1",
        tool_version="v1",
        arguments={
            "query": "safe",
            "authorization": "Bearer this-must-not-appear",
            "nested": {"api_key": "api-secret-value"},
        },
        approval_status=ApprovalStatus.APPROVED,
    )
    result = ToolResult(
        call_id=call.id,
        outcome=ToolOutcome.SUCCEEDED,
        content={
            "title": "<script>alert(1)</script>",
            "password": "hidden",
            "items": list(range(55)),
        },
        duration_ms=12,
        evidence_references=("service:records",),
    )
    act_step = AgentStep(
        id=act_step_id,
        run_id=run.id,
        sequence=2,
        phase=StepPhase.ACT,
        status=StepStatus.SUCCEEDED,
        started_at=NOW + timedelta(milliseconds=25),
        completed_at=NOW + timedelta(milliseconds=37),
        input={"tool_call": call.model_dump(mode="json")},
        output={"tool_result": result.model_dump(mode="json")},
    )
    observe_step = AgentStep(
        id=uuid4(),
        run_id=run.id,
        sequence=3,
        phase=StepPhase.OBSERVE,
        status=StepStatus.SUCCEEDED,
        output={
            "observation": {
                "facts": ["A record matched"],
                "satisfied_criteria": ["A match is observed"],
                "unsatisfied_criteria": [],
                "unassessed_criteria": [],
                "new_constraints": [],
            }
        },
    )
    adapt_step = AgentStep(
        id=uuid4(),
        run_id=run.id,
        sequence=4,
        phase=StepPhase.ADAPT,
        status=StepStatus.SUCCEEDED,
        output={
            "adaptation": {
                "decision": "complete",
                "justification": "The persisted evidence satisfies the objective",
                "final_result": {"summary": "Safe result", "secret": "hidden"},
            }
        },
    )
    review = HumanReview(
        id=uuid4(),
        run_id=run.id,
        step_id=act_step.id,
        tool_call=call,
        decision=ReviewDecision.APPROVE,
        reviewer="Matt token=review-secret",
        comment="Approved after verification",
        reviewed_at=NOW + timedelta(seconds=1),
    )
    return AgentRunDetail(
        run=run,
        steps=(plan_step, act_step, observe_step, adapt_step),
        reviews=(review,),
    )


def test_cursor_round_trip_is_opaque_and_rejects_tampering() -> None:
    run_id = uuid4()
    cursor = encode_run_cursor(NOW, run_id)

    assert decode_run_cursor(cursor) == (NOW, run_id)
    with pytest.raises(InvalidRunCursorError):
        decode_run_cursor("not-base64!")
    with pytest.raises(InvalidRunCursorError):
        decode_run_cursor("x" * 513)
    with pytest.raises(ValueError, match="supplied together"):
        RunListQuery(cursor_created_at=NOW)
    with pytest.raises(ValueError, match="between 1 and 100"):
        RunListQuery(limit=101)


def test_projection_attributes_evidence_and_redacts_nested_secrets() -> None:
    detail = _detail()
    projected = OperationsService(StubReader(detail)).get_evidence(
        detail.run.id, as_of=NOW + timedelta(seconds=2)
    )

    assert projected is not None
    assert projected.run.latest_phase is StepPhase.ADAPT
    assert projected.correlation.trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert projected.objective == "Inspect records with [REDACTED]"
    assert projected.steps[0].source == "model"
    assert projected.steps[0].plan is not None
    assert projected.steps[0].model_invocation is not None
    assert projected.steps[0].model_invocation.repair_count == 2
    assert projected.steps[0].model_invocation.provider_retry_count == 1
    assert projected.steps[0].plan.actions[0].purpose == "Find matching records"
    assert projected.steps[1].source == "tool"
    tool = projected.steps[1].tool
    assert tool is not None
    assert tool.redacted_arguments == {
        "query": "safe",
        "authorization": "[REDACTED]",
        "nested": {"api_key": "[REDACTED]"},
    }
    assert tool.redacted_result is not None
    assert tool.redacted_result["title"] == "<script>alert(1)</script>"
    assert tool.redacted_result["password"] == "[REDACTED]"
    assert tool.redacted_result["items"][-1] == "[TRUNCATED]"
    assert projected.steps[2].observation is not None
    assert projected.steps[2].observation.facts == ("A record matched",)
    assert projected.steps[3].adaptation is not None
    assert projected.steps[3].adaptation.redacted_final_result == {
        "summary": "Safe result",
        "secret": "[REDACTED]",
    }
    assert projected.reviews[0].reviewer == "Matt [REDACTED]"
    assert "do-not-display" not in projected.model_dump_json()
    assert "this-must-not-appear" not in projected.model_dump_json()


def test_parallel_evidence_preserves_every_call_and_matches_reordered_results() -> None:
    detail = _detail()
    original = detail.steps[1]
    first = ToolCall.model_validate(original.input["tool_call"])
    first_result = ToolResult.model_validate(original.output["tool_result"])
    second = first.evolve(id=uuid4(), tool_name="records.inspect.v1")
    second_result = first_result.evolve(call_id=second.id, content={"count": 42})
    parallel = original.evolve(
        input={"tool_calls": [first.model_dump(mode="json"), second.model_dump(mode="json")]},
        output={
            "tool_results": [
                second_result.model_dump(mode="json"),
                first_result.model_dump(mode="json"),
            ]
        },
    )
    detail = detail.evolve(steps=(detail.steps[0], parallel, *detail.steps[2:]))
    projected = OperationsService(StubReader(detail)).get_evidence(detail.run.id, as_of=NOW)
    assert projected is not None
    checks = projected.steps[1].tools
    assert len(checks) == 2
    assert checks[0].call_id == first.id
    assert checks[1].redacted_result == {"count": 42}
    assert projected.steps[1].tool == checks[0]
    assert "do-not-display" not in projected.model_dump_json()
    assert "this-must-not-appear" not in projected.model_dump_json()


def test_metadata_only_policy_hides_restricted_values() -> None:
    detail = _detail()
    projected = OperationsService(
        StubReader(detail),
        EvidencePolicy(show_objectives=False, show_tool_values=False),
    ).get_evidence(detail.run.id, as_of=NOW)

    assert projected is not None
    assert projected.objective is None
    assert projected.run.objective_preview is None
    assert projected.steps[1].tool is not None
    assert projected.steps[1].tool.redacted_arguments is None
    assert projected.steps[1].tool.redacted_result is None


def test_list_projection_uses_live_duration_and_absent_lookup_is_safe() -> None:
    detail = _detail()
    service = OperationsService(StubReader(detail))

    page = service.list_runs(RunListQuery(), as_of=NOW + timedelta(seconds=3))

    assert page.items[0].duration_ms == 3000
    assert page.items[0].status is RunStatus.QUEUED
    assert service.get_evidence(uuid4(), as_of=NOW) is None


def test_list_projection_emits_cursor_and_uses_terminal_update_duration() -> None:
    detail = _detail()
    terminal_run = detail.run.model_copy(
        update={
            "status": RunStatus.SUCCEEDED,
            "updated_at": NOW + timedelta(seconds=4),
            "objective": "x" * 200,
            "final_result": {"summary": "complete"},
        }
    )
    reader = StubReader(detail.model_copy(update={"run": terminal_run}), has_more=True)
    page = OperationsService(reader).list_runs(RunListQuery(), as_of=NOW + timedelta(seconds=20))

    assert page.items[0].duration_ms == 4000
    assert page.items[0].objective_preview is not None
    assert page.items[0].objective_preview.endswith("…")
    assert page.next_cursor is not None
    assert decode_run_cursor(page.next_cursor) == (NOW, terminal_run.id)
