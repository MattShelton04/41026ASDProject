"""End-to-end deterministic tests for the persisted four-phase runner."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from agent_core import (
    AgentRunner,
    ConcurrentRunUpdateError,
    ModelMessage,
    ModelMetrics,
    ModelRole,
    StructuredModelRequest,
    StructuredModelResult,
    ToolRegistry,
    apply_human_review,
    create_run,
)
from shared_contracts import (
    AgentRun,
    AgentRunDetail,
    AgentRunRequest,
    AgentStep,
    HumanReview,
    HumanReviewRequest,
    Observation,
    Plan,
    ReviewDecision,
    RunLimits,
    RunStatus,
    SideEffectClass,
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
        raise NotImplementedError


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
    ) -> None:
        self.store = store
        self.outcome = outcome
        self.retryable = retryable
        self.calls: list[ToolCall] = []

    def execute(self, call: ToolCall, definition: ToolDefinition) -> ToolResult:
        assert self.store.run.status is RunStatus.ACTING
        assert self.store.steps[-1].status.value == "running"
        self.calls.append(call)
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
    outcomes: list[StructuredModelResult],
    *,
    tool: ToolDefinition | None = None,
    tool_outcome: ToolOutcome = ToolOutcome.SUCCEEDED,
    limits: RunLimits | None = None,
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
    executor = RecordingToolExecutor(store, outcome=tool_outcome)
    runner = AgentRunner(
        store=store,
        provider=ScriptedLLMProvider(outcomes),
        prompt_builder=TestPromptBuilder(),
        tools=ToolRegistry([tool or _tool()]),
        tool_executor=executor,
        clock=FixedClock(),
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
