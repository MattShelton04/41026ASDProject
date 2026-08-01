"""End-to-end deterministic tests for the persisted four-phase runner."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from agent_core import (
    AgentRunner,
    ConcurrentRunUpdateError,
    ModelMessage,
    ModelMetrics,
    ModelRole,
    RecoveryDisposition,
    StructuredModelRequest,
    StructuredModelResult,
    ToolRegistry,
    apply_human_review,
    create_run,
    request_cancellation,
    transition_run,
)
from shared_contracts import (
    AgentRun,
    AgentRunDetail,
    AgentRunRequest,
    AgentStep,
    ApprovalStatus,
    HumanReview,
    HumanReviewRequest,
    Observation,
    Plan,
    ReviewDecision,
    RunLimits,
    RunStatus,
    SideEffectClass,
    StepPhase,
    StepStatus,
    ToolCall,
    ToolDefinition,
    ToolError,
    ToolOutcome,
    ToolResult,
)
from shared_testkit import ScriptedLLMProvider

NOW = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)


class FixedClock:
    def now(self) -> datetime:
        return NOW


class MutableClock(FixedClock):
    def __init__(self) -> None:
        self.current = NOW

    def now(self) -> datetime:
        return self.current


class RandomIds:
    def new(self) -> UUID:
        return uuid4()


class MemoryStore:
    def __init__(self, run: AgentRun) -> None:
        self.run = run
        self.steps: list[AgentStep] = []
        self.reviews: list[HumanReview] = []

    def create(self, run: AgentRun) -> None:
        self.run = run

    def get(self, run_id: UUID) -> AgentRunDetail | None:
        if run_id != self.run.id:
            return None
        return AgentRunDetail(run=self.run, steps=tuple(self.steps), reviews=tuple(self.reviews))

    def list_resumable(self) -> tuple[AgentRunDetail, ...]:
        detail = self.get(self.run.id)
        return (detail,) if detail is not None else ()

    def save(
        self,
        run: AgentRun,
        *,
        expected_version: int,
        step: AgentStep | None = None,
        review: HumanReview | None = None,
    ) -> None:
        if self.run.version != expected_version:
            raise ConcurrentRunUpdateError("stale test update")
        self.run = run
        if step is not None:
            for index, existing in enumerate(self.steps):
                if existing.id == step.id:
                    self.steps[index] = step
                    break
            else:
                self.steps.append(step)
        if review is not None:
            self.reviews.append(review)

    def request_cancellation(self, run_id: UUID, *, now: datetime) -> AgentRun | None:
        if run_id != self.run.id:
            return None
        self.run = request_cancellation(self.run, now=now)
        return self.run


class TestPromptBuilder:
    def build_plan_request(
        self, run: AgentRun, definitions: tuple[ToolDefinition, ...]
    ) -> StructuredModelRequest:
        return self._request(run, ModelRole.PLANNER, "planner")

    def build_adaptation_request(
        self,
        run: AgentRun,
        plan: Plan,
        tool_result: ToolResult,
        observation: Observation,
    ) -> StructuredModelRequest:
        return self._request(run, ModelRole.ADAPTER, "adapter")

    @staticmethod
    def _request(run: AgentRun, role: ModelRole, prompt_id: str) -> StructuredModelRequest:
        return StructuredModelRequest(
            run_id=run.id,
            role=role,
            model_profile=run.model_profile,
            messages=(ModelMessage(role="system", content=f"Act as the {role.value}."),),
            output_schema={},
            prompt_id=prompt_id,
            prompt_version="v1",
            prompt_hash="a" * 64,
            rendered_input_hash="b" * 64,
        )


class RecordingToolExecutor:
    def __init__(
        self,
        store: MemoryStore,
        *,
        outcome: ToolOutcome = ToolOutcome.SUCCEEDED,
        retryable: bool = False,
        exception: Exception | None = None,
        cancel_during_execute: bool = False,
    ) -> None:
        self.store = store
        self.outcome = outcome
        self.retryable = retryable
        self.exception = exception
        self.cancel_during_execute = cancel_during_execute
        self.calls: list[ToolCall] = []

    def execute(self, call: ToolCall, definition: ToolDefinition) -> ToolResult:
        assert self.store.run.status is RunStatus.ACTING
        assert self.store.steps[-1].status.value == "running"
        self.calls.append(call)
        if self.cancel_during_execute:
            self.store.request_cancellation(call.run_id, now=NOW)
        if self.exception is not None:
            raise self.exception
        if self.outcome is ToolOutcome.SUCCEEDED:
            return ToolResult(
                call_id=call.id,
                outcome=self.outcome,
                content={"count": 1},
                duration_ms=5,
            )
        return ToolResult(
            call_id=call.id,
            outcome=self.outcome,
            error=ToolError(code="feature_unavailable", message="Feature tool unavailable"),
            duration_ms=5,
            retryable=self.retryable,
        )


def _tool(*, side_effect: SideEffectClass = SideEffectClass.READ_ONLY) -> ToolDefinition:
    return ToolDefinition(
        name="student_1.records.search.v1",
        version="v1",
        description="Search feature-owned records",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {"count": {"type": "integer", "minimum": 0}},
            "required": ["count"],
            "additionalProperties": False,
        },
        side_effect=side_effect,
    )


def _model_result(content: dict[str, object]) -> StructuredModelResult:
    return StructuredModelResult(
        content=content,
        provider="scripted",
        model="fake",
        metrics=ModelMetrics(total_duration_ms=1),
    )


def _plan(*, arguments: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "goal": "Find verified records",
        "actions": [
            {
                "sequence": 1,
                "tool_name": "student_1.records.search.v1",
                "arguments": arguments or {"query": "verified"},
                "purpose": "Search the feature-owned records",
            }
        ],
        "success_criteria": ["A verified result is returned"],
        "risk_level": "low",
        "assumptions": [],
    }


def _adaptation(decision: str) -> dict[str, object]:
    payload: dict[str, object] = {
        "decision": decision,
        "justification": "Deterministic test decision",
    }
    if decision == "complete":
        payload["final_result"] = {"summary": "Found one verified record"}
    return payload


def _runner(
    outcomes: list[StructuredModelResult | Exception],
    *,
    tool: ToolDefinition | None = None,
    tool_outcome: ToolOutcome = ToolOutcome.SUCCEEDED,
    limits: RunLimits | None = None,
    tool_exception: Exception | None = None,
    cancel_during_execute: bool = False,
    clock: FixedClock | None = None,
) -> tuple[AgentRunner, MemoryStore, RecordingToolExecutor]:
    run = create_run(
        AgentRunRequest(
            feature_key="student-1-feature",
            objective="Find verified records",
            limits=limits or RunLimits(),
        ),
        run_id=uuid4(),
        request_id="request-1",
        now=NOW,
    )
    store = MemoryStore(run)
    executor = RecordingToolExecutor(
        store,
        outcome=tool_outcome,
        exception=tool_exception,
        cancel_during_execute=cancel_during_execute,
    )
    runner = AgentRunner(
        store=store,
        provider=ScriptedLLMProvider(outcomes),
        prompt_builder=TestPromptBuilder(),
        tools=ToolRegistry([tool or _tool()]),
        tool_executor=executor,
        clock=clock or FixedClock(),
        ids=RandomIds(),
    )
    return runner, store, executor


def test_runner_persists_a_complete_four_phase_success() -> None:
    runner, store, executor = _runner(
        [_model_result(_plan()), _model_result(_adaptation("complete"))]
    )

    result = runner.run_until_blocked(store.run.id)

    assert result.status is RunStatus.SUCCEEDED
    assert result.iteration_count == 1
    assert result.tool_call_count == 1
    assert result.final_result == {"summary": "Found one verified record"}
    assert [step.phase.value for step in store.steps] == ["plan", "act", "observe", "adapt"]
    assert all(step.status.value == "succeeded" for step in store.steps)
    assert len(executor.calls) == 1


def test_protected_action_stops_for_review_before_any_effect() -> None:
    runner, store, executor = _runner(
        [_model_result(_plan())],
        tool=_tool(side_effect=SideEffectClass.DESTRUCTIVE_WRITE),
    )

    result = runner.run_until_blocked(store.run.id)

    assert result.status is RunStatus.REVIEW_REQUIRED
    assert store.steps[-1].status.value == "pending"
    assert executor.calls == []
    pending_call = ToolCall.model_validate(store.steps[-1].input["tool_call"])
    assert pending_call.idempotency_key is not None
    assert pending_call.approval_status.value == "pending"


def test_approved_action_resumes_with_the_original_idempotent_call() -> None:
    runner, store, executor = _runner(
        [_model_result(_plan()), _model_result(_adaptation("complete"))],
        tool=_tool(side_effect=SideEffectClass.DESTRUCTIVE_WRITE),
    )
    blocked = runner.run_until_blocked(store.run.id)
    pending_call = ToolCall.model_validate(store.steps[-1].input["tool_call"])
    blocked_detail = store.get(blocked.id)
    assert blocked_detail is not None
    review = apply_human_review(
        blocked_detail,
        HumanReviewRequest(decision=ReviewDecision.APPROVE, reviewer="reviewer"),
        review_id=uuid4(),
        now=NOW,
    )
    store.save(
        review.run,
        expected_version=blocked.version,
        step=review.step,
        review=review.review,
    )

    result = runner.run_until_blocked(store.run.id)

    assert result.status is RunStatus.SUCCEEDED
    assert len(executor.calls) == 1
    assert executor.calls[0].id == pending_call.id
    assert executor.calls[0].idempotency_key == pending_call.idempotency_key


def test_replanned_writes_receive_distinct_call_scoped_idempotency_keys() -> None:
    runner, store, executor = _runner(
        [
            _model_result(_plan(arguments={"query": "first"})),
            _model_result(_adaptation("replan")),
            _model_result(_plan(arguments={"query": "second"})),
            _model_result(_adaptation("complete")),
        ],
        tool=_tool(side_effect=SideEffectClass.REVERSIBLE_WRITE),
    )

    result = runner.run_until_blocked(store.run.id)

    assert result.status is RunStatus.SUCCEEDED
    assert len(executor.calls) == 2
    first, second = executor.calls
    assert first.arguments != second.arguments
    assert first.idempotency_key == f"{store.run.id}:call:{first.id}"
    assert second.idempotency_key == f"{store.run.id}:call:{second.id}"
    assert first.idempotency_key != second.idempotency_key


def test_cancellation_race_reconciles_an_uncertain_write_to_review() -> None:
    runner, store, executor = _runner(
        [_model_result(_plan())],
        tool=_tool(side_effect=SideEffectClass.REVERSIBLE_WRITE),
        cancel_during_execute=True,
    )

    result = runner.run_until_blocked(store.run.id)

    assert result.status is RunStatus.REVIEW_REQUIRED
    assert result.cancel_requested is True
    assert len(executor.calls) == 1
    pending = store.steps[-1]
    assert pending.status is StepStatus.PENDING
    assert pending.output["recovery"] is not None


def test_invalid_planner_arguments_fail_before_tool_execution() -> None:
    runner, store, executor = _runner([_model_result(_plan(arguments={"wrong": True}))])

    result = runner.run_until_blocked(store.run.id)

    assert result.status is RunStatus.FAILED
    assert result.error is not None
    assert result.error.code == "invalid_model_or_tool_data"
    assert executor.calls == []


def test_non_retryable_tool_failure_is_terminal_but_still_persisted() -> None:
    runner, store, _ = _runner([_model_result(_plan())], tool_outcome=ToolOutcome.FAILED)

    result = runner.run_until_blocked(store.run.id)

    assert result.status is RunStatus.FAILED
    assert result.error is not None
    assert result.error.code == "feature_unavailable"
    assert result.tool_call_count == 1
    assert store.steps[-1].output["tool_result"] is not None


def test_iteration_limit_stops_a_continue_loop_before_another_effect() -> None:
    runner, store, executor = _runner(
        [_model_result(_plan()), _model_result(_adaptation("continue"))],
        limits=RunLimits(max_iterations=1),
    )

    result = runner.run_until_blocked(store.run.id)

    assert result.status is RunStatus.FAILED
    assert result.error is not None
    assert result.error.code == "run_limit_reached"
    assert len(executor.calls) == 1


def test_elapsed_budget_prevents_an_adaptation_model_call_after_tool_io() -> None:
    clock = MutableClock()
    runner, store, _ = _runner(
        [_model_result(_plan()), _model_result(_adaptation("complete"))],
        limits=RunLimits(time_budget_ms=1_000),
        clock=clock,
    )
    ready = runner.advance(store.get(store.run.id))  # type: ignore[arg-type]
    observing = runner.advance(store.get(ready.id))  # type: ignore[arg-type]
    clock.current = NOW + timedelta(seconds=2)
    adapting = runner.advance(store.get(observing.id))  # type: ignore[arg-type]

    result = runner.advance(store.get(adapting.id))  # type: ignore[arg-type]

    assert result.status is RunStatus.FAILED
    assert result.error is not None
    assert result.error.code == "run_limit_reached"
    assert result.error.message == "time limit reached"


def test_adaptation_review_without_actionable_target_fails_closed() -> None:
    runner, store, executor = _runner(
        [_model_result(_plan()), _model_result(_adaptation("request_review"))]
    )

    result = runner.run_until_blocked(store.run.id)

    assert result.status is RunStatus.FAILED
    assert result.error is not None
    assert result.error.code == "unsupported_review_target"
    assert "pending tool call" in result.error.message
    assert len(executor.calls) == 1


def test_unexpected_read_only_executor_exception_is_persisted_safely() -> None:
    runner, store, executor = _runner(
        [_model_result(_plan())],
        tool_exception=RuntimeError("private adapter detail"),
    )

    result = runner.run_until_blocked(store.run.id)

    assert result.status is RunStatus.FAILED
    assert result.error is not None
    assert result.error.code == "tool_executor_error"
    assert result.error.message == "Unexpected orchestration failure"
    assert store.steps[-1].status is StepStatus.FAILED
    assert len(executor.calls) == 1


def test_unexpected_write_executor_exception_pauses_uncertain_effect_for_review() -> None:
    runner, store, executor = _runner(
        [_model_result(_plan())],
        tool=_tool(side_effect=SideEffectClass.REVERSIBLE_WRITE),
        tool_exception=RuntimeError("response was lost"),
    )

    result = runner.run_until_blocked(store.run.id)

    assert result.status is RunStatus.REVIEW_REQUIRED
    assert result.tool_call_count == 0
    pending_step = store.steps[-1]
    pending_call = ToolCall.model_validate(pending_step.input["tool_call"])
    assert pending_step.status is StepStatus.PENDING
    assert pending_call.approval_status.value == "pending"
    assert pending_call.idempotency_key is not None
    assert pending_step.output["recovery"] is not None
    assert len(executor.calls) == 1


def test_interrupted_planning_attempt_is_closed_and_retried_from_safe_boundary() -> None:
    runner, store, _ = _runner([RuntimeError("process interrupted")])

    with pytest.raises(RuntimeError, match="process interrupted"):
        runner.run_until_blocked(store.run.id)

    interrupted_version = store.run.version
    detail = store.get(store.run.id)
    assert detail is not None
    decision = runner.recover_interrupted(detail)

    assert decision.disposition is RecoveryDisposition.REENQUEUE
    assert store.run.status is RunStatus.PLANNING
    assert store.run.version == interrupted_version + 1
    assert store.steps[-1].status is StepStatus.FAILED
    assert store.steps[-1].error is not None
    assert store.steps[-1].error.code == "execution_interrupted"


def test_interrupted_adaptation_attempt_is_closed_and_retried_from_safe_boundary() -> None:
    runner, store, _ = _runner([_model_result(_plan()), RuntimeError("process interrupted")])

    with pytest.raises(RuntimeError, match="process interrupted"):
        runner.run_until_blocked(store.run.id)

    detail = store.get(store.run.id)
    assert detail is not None
    assert detail.run.status is RunStatus.ADAPTING
    decision = runner.recover_interrupted(detail)

    assert decision.disposition is RecoveryDisposition.REENQUEUE
    assert store.run.status is RunStatus.ADAPTING
    assert store.steps[-1].phase is StepPhase.ADAPT
    assert store.steps[-1].status is StepStatus.FAILED


def test_observing_boundary_needs_no_repair_before_reenqueue() -> None:
    runner, store, _ = _runner([_model_result(_plan())])
    ready = runner.advance(store.get(store.run.id))  # type: ignore[arg-type]
    assert ready.status is RunStatus.READY
    observing = runner.advance(store.get(store.run.id))  # type: ignore[arg-type]
    assert observing.status is RunStatus.OBSERVING
    version = observing.version

    detail = store.get(store.run.id)
    assert detail is not None
    decision = runner.recover_interrupted(detail)

    assert decision.disposition is RecoveryDisposition.REENQUEUE
    assert decision.changed is False
    assert store.run.version == version


@pytest.mark.parametrize(
    ("side_effect", "expected_status", "expected_disposition"),
    [
        (SideEffectClass.READ_ONLY, RunStatus.READY, RecoveryDisposition.REENQUEUE),
        (
            SideEffectClass.REVERSIBLE_WRITE,
            RunStatus.REVIEW_REQUIRED,
            RecoveryDisposition.AWAIT_REVIEW,
        ),
    ],
)
def test_interrupted_action_recovery_is_effect_aware(
    side_effect: SideEffectClass,
    expected_status: RunStatus,
    expected_disposition: RecoveryDisposition,
) -> None:
    definition = _tool(side_effect=side_effect)
    runner, store, _ = _runner([_model_result(_plan())], tool=definition)
    ready = runner.advance(store.get(store.run.id))  # type: ignore[arg-type]
    call = ToolCall(
        id=uuid4(),
        run_id=ready.id,
        step_id=uuid4(),
        tool_name=definition.name,
        tool_version=definition.version,
        arguments={"query": "verified"},
        idempotency_key=(None if side_effect is SideEffectClass.READ_ONLY else f"{ready.id}:1:v1"),
        approval_status=ApprovalStatus.NOT_REQUIRED,
    )
    step = AgentStep(
        id=call.step_id,
        run_id=ready.id,
        sequence=2,
        phase=StepPhase.ACT,
        status=StepStatus.RUNNING,
        started_at=NOW,
        input={"tool_call": call.model_dump(mode="json")},
    )
    acting = transition_run(ready, RunStatus.ACTING, now=NOW)
    store.save(acting, expected_version=ready.version, step=step)

    detail = store.get(store.run.id)
    assert detail is not None
    decision = runner.recover_interrupted(detail)

    assert decision.disposition is expected_disposition
    assert store.run.status is expected_status
    recovered_call = ToolCall.model_validate(store.steps[-1].input["tool_call"])
    assert recovered_call.id == call.id
    assert store.steps[-1].status is StepStatus.PENDING
    if side_effect is SideEffectClass.READ_ONLY:
        assert recovered_call.approval_status is ApprovalStatus.NOT_REQUIRED
    else:
        assert recovered_call.approval_status is ApprovalStatus.PENDING
