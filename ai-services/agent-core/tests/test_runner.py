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
    ModelOutputValidationError,
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
        self,
        run: AgentRun,
        definitions: tuple[ToolDefinition, ...],
        prior_steps: tuple[AgentStep, ...] = (),
    ) -> StructuredModelRequest:
        return self._request(run, ModelRole.PLANNER, "planner")

    def build_adaptation_request(
        self,
        run: AgentRun,
        plan: Plan,
        tool_result: ToolResult,
        observation: Observation,
        tool_results: tuple[ToolResult, ...],
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


class InvalidPromptBuilder(TestPromptBuilder):
    def __init__(self, *, fail_role: ModelRole) -> None:
        self.fail_role = fail_role

    def build_plan_request(
        self,
        run: AgentRun,
        definitions: tuple[ToolDefinition, ...],
        prior_steps: tuple[AgentStep, ...] = (),
    ) -> StructuredModelRequest:
        if self.fail_role is ModelRole.PLANNER:
            raise ValueError("private prompt validation detail")
        return super().build_plan_request(run, definitions, prior_steps)

    def build_adaptation_request(
        self,
        run: AgentRun,
        plan: Plan,
        tool_result: ToolResult,
        observation: Observation,
        tool_results: tuple[ToolResult, ...],
    ) -> StructuredModelRequest:
        if self.fail_role is ModelRole.ADAPTER:
            raise ValueError("private prompt validation detail")
        return super().build_adaptation_request(run, plan, tool_result, observation, tool_results)


class RecordingToolExecutor:
    def __init__(
        self,
        store: MemoryStore,
        *,
        outcome: ToolOutcome = ToolOutcome.SUCCEEDED,
        outcomes: tuple[ToolOutcome, ...] = (),
        retryable: bool = False,
        exception: Exception | None = None,
        cancel_during_execute: bool = False,
    ) -> None:
        self.store = store
        self.outcome = outcome
        self.outcomes = outcomes
        self.retryable = retryable
        self.exception = exception
        self.cancel_during_execute = cancel_during_execute
        self.calls: list[ToolCall] = []
        self.timeouts_ms: list[int] = []

    def execute(
        self,
        call: ToolCall,
        definition: ToolDefinition,
        *,
        timeout_ms: int,
    ) -> ToolResult:
        assert self.store.run.status is RunStatus.ACTING
        assert self.store.steps[-1].status.value == "running"
        self.calls.append(call)
        self.timeouts_ms.append(timeout_ms)
        if self.cancel_during_execute:
            self.store.request_cancellation(call.run_id, now=NOW)
        if self.exception is not None:
            raise self.exception
        outcome = self.outcomes[len(self.calls) - 1] if self.outcomes else self.outcome
        if outcome is ToolOutcome.SUCCEEDED:
            return ToolResult(
                call_id=call.id,
                outcome=outcome,
                content={"count": 1},
                duration_ms=5,
            )
        return ToolResult(
            call_id=call.id,
            outcome=outcome,
            error=ToolError(code="feature_unavailable", message="Feature tool unavailable"),
            duration_ms=5,
            retryable=self.retryable,
        )


def _tool(*, side_effect: SideEffectClass = SideEffectClass.READ_ONLY) -> ToolDefinition:
    return ToolDefinition(
        name="student_1.records.search.v1",
        version="v1",
        feature_key="student-1-feature",
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


def _two_action_plan() -> dict[str, object]:
    plan = _plan()
    actions = list(plan["actions"])  # type: ignore[arg-type]
    actions.append(
        {
            "sequence": 2,
            "tool_name": "student_1.records.search.v1",
            "arguments": {"query": "verified detail"},
            "purpose": "Fetch the detail required by the success criterion",
        }
    )
    plan["actions"] = actions
    return plan


def _runner(
    outcomes: list[StructuredModelResult | Exception],
    *,
    tool: ToolDefinition | None = None,
    tool_outcome: ToolOutcome = ToolOutcome.SUCCEEDED,
    tool_outcomes: tuple[ToolOutcome, ...] = (),
    limits: RunLimits | None = None,
    tool_exception: Exception | None = None,
    cancel_during_execute: bool = False,
    clock: FixedClock | None = None,
    prompt_builder: TestPromptBuilder | None = None,
    tool_allowlist: tuple[str, ...] | None = None,
) -> tuple[AgentRunner, MemoryStore, RecordingToolExecutor]:
    run = create_run(
        AgentRunRequest(
            feature_key="student-1-feature",
            objective="Find verified records",
            limits=limits or RunLimits(),
            tool_allowlist=tool_allowlist,
        ),
        run_id=uuid4(),
        request_id="request-1",
        now=NOW,
    )
    store = MemoryStore(run)
    executor = RecordingToolExecutor(
        store,
        outcome=tool_outcome,
        outcomes=tool_outcomes,
        exception=tool_exception,
        cancel_during_execute=cancel_during_execute,
    )
    runner = AgentRunner(
        store=store,
        provider=ScriptedLLMProvider(outcomes),
        prompt_builder=prompt_builder or TestPromptBuilder(),
        tools=ToolRegistry([tool or _tool()]),
        tool_executor=executor,
        clock=clock or FixedClock(),
        ids=RandomIds(),
    )
    return runner, store, executor


def test_per_run_tool_allowlist_hides_and_rejects_feature_write_capabilities() -> None:
    definition = _tool(side_effect=SideEffectClass.DESTRUCTIVE_WRITE)
    runner, store, executor = _runner(
        [_model_result(_plan()), _model_result(_plan()), _model_result(_plan())],
        tool=definition,
        tool_allowlist=("student_1.records.read.v1",),
    )

    assert runner._definitions_for_run(store.run) == ()
    result = runner.run_until_blocked(store.run.id)

    assert result.status is RunStatus.FAILED
    assert result.error is not None
    assert result.error.code == "invalid_model_or_tool_data"
    assert executor.calls == []


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


def test_prompt_construction_validation_failure_terminalizes_without_recovery_loop() -> None:
    runner, store, executor = _runner(
        [], prompt_builder=InvalidPromptBuilder(fail_role=ModelRole.PLANNER)
    )

    result = runner.run_until_blocked(store.run.id)

    assert result.status is RunStatus.FAILED
    assert result.error is not None
    assert result.error.code == "invalid_model_or_tool_data"
    assert result.error.message == "Prompt or model data failed validation"
    assert store.steps[-1].status is StepStatus.FAILED
    assert executor.calls == []


def test_adaptation_prompt_validation_failure_terminalizes_once() -> None:
    runner, store, executor = _runner(
        [_model_result(_plan())],
        prompt_builder=InvalidPromptBuilder(fail_role=ModelRole.ADAPTER),
    )

    result = runner.run_until_blocked(store.run.id)

    assert result.status is RunStatus.FAILED
    assert result.error is not None
    assert result.error.code == "invalid_model_or_tool_data"
    assert len([step for step in store.steps if step.phase is StepPhase.ADAPT]) == 1
    assert len(executor.calls) == 1


def test_plan_accepts_exact_tool_discovered_non_rfc_fixture_identifier() -> None:
    discovered_ref = "a0000000-0000-0000-0000-000000000012"
    inspect_tool = ToolDefinition(
        name="student_1.records.inspect.v1",
        version="v1",
        feature_key="student-1-feature",
        description="Inspect one exact record",
        input_schema={
            "type": "object",
            "properties": {"record_ref": {"type": "string"}},
            "required": ["record_ref"],
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        side_effect=SideEffectClass.READ_ONLY,
    )
    runner, store, _ = _runner([], tool=inspect_tool)
    discovered = AgentStep(
        id=uuid4(),
        run_id=store.run.id,
        sequence=1,
        phase=StepPhase.ACT,
        status=StepStatus.SUCCEEDED,
        output={
            "tool_result": {
                "call_id": str(uuid4()),
                "outcome": "succeeded",
                "content": {"record": {"record_ref": discovered_ref}},
                "duration_ms": 1,
                "retryable": False,
                "evidence_references": [],
            }
        },
    )
    plan = Plan.model_validate(
        {
            "goal": "Inspect the discovered record",
            "actions": [
                {
                    "sequence": 1,
                    "tool_name": inspect_tool.name,
                    "arguments": {"record_ref": discovered_ref},
                    "purpose": "Inspect the exact result",
                }
            ],
            "success_criteria": ["Exact record is inspected"],
            "risk_level": "low",
        }
    )

    runner._validate_model_plan(store.run, plan, (discovered,))


def test_plan_rejects_cross_type_uuid_substitution_from_tool_evidence() -> None:
    run_id = "70000000-0000-0000-0000-000000000001"
    release_id = "60000000-0000-0000-0000-000000000001"
    inspect_tool = ToolDefinition(
        name="data.release_inspect.v1",
        version="v1",
        feature_key="student-1-feature",
        description="Inspect one release",
        input_schema={
            "type": "object",
            "properties": {"release_id": {"type": "string", "format": "uuid"}},
            "required": ["release_id"],
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        side_effect=SideEffectClass.READ_ONLY,
    )
    runner, store, _ = _runner([], tool=inspect_tool)
    discovered = AgentStep(
        id=uuid4(),
        run_id=store.run.id,
        sequence=1,
        phase=StepPhase.ACT,
        status=StepStatus.SUCCEEDED,
        input={"tool_call": {"tool_name": "data.runs.v1", "arguments": {}}},
        output={
            "tool_result": {
                "outcome": "succeeded",
                "content": {
                    "items": [{"id": run_id}],
                    "message": f"Related release in narrative: {release_id}",
                },
            }
        },
    )
    plan = Plan.model_validate(
        {
            "goal": "Inspect a release",
            "actions": [
                {
                    "sequence": 1,
                    "tool_name": inspect_tool.name,
                    "arguments": {"release_id": run_id},
                    "purpose": "Inspect exact release evidence",
                }
            ],
            "success_criteria": ["Release is inspected"],
            "risk_level": "low",
        }
    )

    with pytest.raises(ModelOutputValidationError, match="release_id must copy"):
        runner._validate_model_plan(store.run, plan, (discovered,))


@pytest.mark.parametrize(
    ("objective", "tool_name", "content"),
    [
        (
            "Validated page context:\n- ingestion_run_id: 70000000-0000-0000-0000-000000000002",
            "data.runs.v1",
            {},
        ),
        (
            "Inspect release evidence without guessing identifiers",
            "data.release_inspect.v1",
            {"quality_results": [{"id": "70000000-0000-0000-0000-000000000002"}]},
        ),
    ],
)
def test_plan_rejects_typed_objective_and_nested_id_substitution(
    objective: str, tool_name: str, content: dict[str, object]
) -> None:
    wrong_release_id = "70000000-0000-0000-0000-000000000002"
    inspect_tool = ToolDefinition(
        name="data.release_inspect.v1",
        version="v1",
        feature_key="student-1-feature",
        description="Inspect one release",
        input_schema={
            "type": "object",
            "properties": {"release_id": {"type": "string", "format": "uuid"}},
            "required": ["release_id"],
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        side_effect=SideEffectClass.READ_ONLY,
    )
    runner, store, _ = _runner([], tool=inspect_tool)
    store.run = store.run.evolve(objective=objective)
    discovered = AgentStep(
        id=uuid4(),
        run_id=store.run.id,
        sequence=1,
        phase=StepPhase.ACT,
        status=StepStatus.SUCCEEDED,
        input={"tool_call": {"tool_name": tool_name, "arguments": {}}},
        output={"tool_result": {"outcome": "succeeded", "content": content}},
    )
    plan = Plan.model_validate(
        {
            "goal": "Inspect a release",
            "actions": [
                {
                    "sequence": 1,
                    "tool_name": inspect_tool.name,
                    "arguments": {"release_id": wrong_release_id},
                    "purpose": "Inspect exact release evidence",
                }
            ],
            "success_criteria": ["Release is inspected"],
            "risk_level": "low",
        }
    )

    with pytest.raises(ModelOutputValidationError, match="release_id must copy"):
        runner._validate_model_plan(store.run, plan, (discovered,))


def test_successful_call_signatures_ignore_non_action_and_failed_steps() -> None:
    run_id = store_id = uuid4()
    steps = (
        AgentStep(
            id=uuid4(),
            run_id=run_id,
            sequence=1,
            phase=StepPhase.OBSERVE,
            status=StepStatus.SUCCEEDED,
        ),
        AgentStep(
            id=uuid4(),
            run_id=store_id,
            sequence=2,
            phase=StepPhase.ACT,
            status=StepStatus.FAILED,
            input={"tool_call": {"tool_name": "data.runs.v1", "arguments": {}}},
            output={"tool_result": {"outcome": "failed"}},
        ),
    )

    assert AgentRunner._successful_call_signatures(steps) == set()


def test_plan_rejects_guessed_non_rfc_fixture_identifier_before_tool_execution() -> None:
    guessed_ref = "a0000000-0000-0000-0000-000000000099"
    inspect_tool = ToolDefinition(
        name="student_1.records.inspect.v1",
        version="v1",
        feature_key="student-1-feature",
        description="Inspect one exact record",
        input_schema={
            "type": "object",
            "properties": {"record_ref": {"type": "string"}},
            "required": ["record_ref"],
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        side_effect=SideEffectClass.READ_ONLY,
    )
    runner, store, executor = _runner([], tool=inspect_tool)
    plan = Plan.model_validate(
        {
            "goal": "Inspect a guessed record",
            "actions": [
                {
                    "sequence": 1,
                    "tool_name": inspect_tool.name,
                    "arguments": {"record_ref": guessed_ref},
                    "purpose": "Inspect a record",
                }
            ],
            "success_criteria": ["Record is inspected"],
            "risk_level": "low",
        }
    )

    with pytest.raises(ModelOutputValidationError, match="supplied by the user or discovered"):
        runner._validate_model_plan(store.run, plan)
    assert executor.calls == []


def test_successful_intermediate_action_continues_without_an_extra_model_call() -> None:
    runner, store, executor = _runner(
        [_model_result(_two_action_plan()), _model_result(_adaptation("complete"))]
    )

    result = runner.run_until_blocked(store.run.id)

    assert result.status is RunStatus.SUCCEEDED
    assert result.iteration_count == 2
    assert len(executor.calls) == 2
    adaptations = [step for step in store.steps if step.phase is StepPhase.ADAPT]
    assert adaptations[0].output["decision_source"] == "orchestration_policy"
    assert "model_invocation" not in adaptations[0].output
    assert adaptations[1].output["decision_source"] == "model"


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


def test_invalid_planner_arguments_are_repaired_before_tool_execution() -> None:
    runner, store, executor = _runner(
        [
            _model_result(_plan(arguments={"wrong": True})),
            _model_result(_plan()),
            _model_result(_adaptation("complete")),
        ]
    )

    result = runner.run_until_blocked(store.run.id)

    assert result.status is RunStatus.SUCCEEDED
    assert [call.arguments for call in executor.calls] == [{"query": "verified"}]
    plan_step = next(step for step in store.steps if step.phase is StepPhase.PLAN)
    assert plan_step.output["model_invocation"]["repair_count"] == 1


def test_invalid_planner_arguments_fail_after_bounded_repair() -> None:
    invalid = _model_result(_plan(arguments={"wrong": True}))
    runner, store, executor = _runner([invalid, invalid])

    result = runner.run_until_blocked(store.run.id)

    assert result.status is RunStatus.FAILED
    assert result.error is not None
    assert result.error.code == "invalid_model_or_tool_data"
    assert executor.calls == []


def test_first_read_failure_can_replan_and_succeed() -> None:
    runner, store, executor = _runner(
        [
            _model_result(_plan()),
            _model_result(_adaptation("replan")),
            _model_result(_plan(arguments={"query": "fallback"})),
            _model_result(_adaptation("complete")),
        ],
        tool_outcomes=(ToolOutcome.FAILED, ToolOutcome.SUCCEEDED),
    )

    result = runner.run_until_blocked(store.run.id)

    assert result.status is RunStatus.SUCCEEDED
    assert [call.arguments for call in executor.calls] == [
        {"query": "verified"},
        {"query": "fallback"},
    ]
    failed_action = next(
        step
        for step in store.steps
        if step.phase is StepPhase.ACT and step.status is StepStatus.FAILED
    )
    assert failed_action.error is not None
    assert failed_action.error.code == "feature_unavailable"


def test_replan_repairs_a_successful_call_repeated_inside_a_different_plan() -> None:
    runner, store, executor = _runner(
        [
            _model_result(_plan()),
            _model_result(_adaptation("replan")),
            _model_result(_plan()),
            _model_result(_plan(arguments={"query": "new evidence"})),
            _model_result(_adaptation("complete")),
        ]
    )

    result = runner.run_until_blocked(store.run.id)

    assert result.status is RunStatus.SUCCEEDED
    assert [call.arguments for call in executor.calls] == [
        {"query": "verified"},
        {"query": "new evidence"},
    ]
    plan_steps = [step for step in store.steps if step.phase is StepPhase.PLAN]
    assert plan_steps[-1].output["model_invocation"]["repair_count"] == 1


def test_same_read_failure_is_terminal_on_second_identical_attempt() -> None:
    runner, store, executor = _runner(
        [
            _model_result(_plan()),
            _model_result(_adaptation("replan")),
            _model_result(_plan()),
        ],
        tool_outcomes=(ToolOutcome.FAILED, ToolOutcome.FAILED),
    )

    result = runner.run_until_blocked(store.run.id)

    assert result.status is RunStatus.FAILED
    assert result.error is not None
    assert result.error.code == "repeated_tool_failure"
    assert "feature_unavailable" in result.error.message
    assert len(executor.calls) == 2


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


def test_continue_after_last_action_replans_instead_of_exhausting_the_plan() -> None:
    runner, store, executor = _runner(
        [
            _model_result(_plan()),
            _model_result(_adaptation("continue")),
            _model_result(_plan(arguments={"query": "refined"})),
            _model_result(_adaptation("complete")),
        ]
    )

    result = runner.run_until_blocked(store.run.id)

    assert result.status is RunStatus.SUCCEEDED
    assert result.iteration_count == 2
    assert [call.arguments for call in executor.calls] == [
        {"query": "verified"},
        {"query": "refined"},
    ]


def test_replanning_repeated_success_fails_after_bounded_repair() -> None:
    runner, store, executor = _runner(
        [
            _model_result(_plan()),
            _model_result(_adaptation("continue")),
            _model_result(_plan()),
            _model_result(_plan()),
        ]
    )

    result = runner.run_until_blocked(store.run.id)

    assert result.status is RunStatus.FAILED
    assert result.error is not None
    assert result.error.code == "invalid_model_or_tool_data"
    assert result.error.message == "model output failed Plan validation"
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


def test_tool_timeout_is_capped_to_the_remaining_run_budget() -> None:
    clock = MutableClock()
    runner, store, executor = _runner(
        [_model_result(_plan())],
        limits=RunLimits(time_budget_ms=1_000),
        clock=clock,
    )
    ready = runner.advance(store.get(store.run.id))  # type: ignore[arg-type]
    clock.current = NOW + timedelta(milliseconds=750)

    runner.advance(store.get(ready.id))  # type: ignore[arg-type]

    assert executor.timeouts_ms == [250]


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
        [
            _model_result(_plan()),
            _model_result(_adaptation("replan")),
            _model_result(_plan()),
        ],
        tool_exception=RuntimeError("private adapter detail"),
    )

    result = runner.run_until_blocked(store.run.id)

    assert result.status is RunStatus.FAILED
    assert result.error is not None
    assert result.error.code == "repeated_tool_failure"
    assert "tool_executor_error" in result.error.message
    assert store.steps[-1].status is StepStatus.FAILED
    assert len(executor.calls) == 2


def test_unexpected_write_executor_exception_pauses_uncertain_effect_for_review() -> None:
    runner, store, executor = _runner(
        [_model_result(_plan())],
        tool=_tool(side_effect=SideEffectClass.REVERSIBLE_WRITE),
        tool_exception=RuntimeError("response was lost"),
    )

    result = runner.run_until_blocked(store.run.id)

    assert result.status is RunStatus.REVIEW_REQUIRED
    assert result.tool_call_count == 1
    pending_step = store.steps[-1]
    pending_call = ToolCall.model_validate(pending_step.input["tool_call"])
    assert pending_step.status is StepStatus.PENDING
    assert pending_call.approval_status.value == "pending"
    assert pending_call.idempotency_key is not None
    assert pending_step.output["recovery"] is not None
    assert len(executor.calls) == 1


def test_retryable_write_failure_pauses_unknown_outcome_for_review() -> None:
    runner, store, executor = _runner(
        [_model_result(_plan())],
        tool=_tool(side_effect=SideEffectClass.REVERSIBLE_WRITE),
        tool_outcome=ToolOutcome.TIMED_OUT,
    )
    executor.retryable = True

    result = runner.run_until_blocked(store.run.id)

    assert result.status is RunStatus.REVIEW_REQUIRED
    assert result.tool_call_count == 1
    pending_step = store.steps[-1]
    pending_call = ToolCall.model_validate(pending_step.input["tool_call"])
    recovery = pending_step.output["recovery"]
    assert pending_step.status is StepStatus.PENDING
    assert pending_call.approval_status is ApprovalStatus.PENDING
    assert isinstance(recovery, dict)
    assert recovery["reported_result"]["outcome"] == "timed_out"
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


def test_stable_adapting_boundary_is_reenqueued_without_recovery_mutation() -> None:
    runner, store, _ = _runner([_model_result(_plan())])
    runner.advance(store.get(store.run.id))  # type: ignore[arg-type]
    runner.advance(store.get(store.run.id))  # type: ignore[arg-type]
    adapting = runner.advance(store.get(store.run.id))  # type: ignore[arg-type]
    assert adapting.status is RunStatus.ADAPTING
    version = adapting.version

    detail = store.get(store.run.id)
    assert detail is not None
    assert not any(
        step.phase is StepPhase.ADAPT and step.status is StepStatus.RUNNING for step in detail.steps
    )
    decision = runner.recover_interrupted(detail)

    assert decision.disposition is RecoveryDisposition.REENQUEUE
    assert decision.changed is False
    assert store.run.version == version


def test_stable_replanning_boundary_is_reenqueued_without_recovery_mutation() -> None:
    runner, store, _ = _runner([_model_result(_plan()), _model_result(_adaptation("replan"))])
    for _ in range(4):
        runner.advance(store.get(store.run.id))  # type: ignore[arg-type]
    assert store.run.status is RunStatus.PLANNING
    version = store.run.version

    detail = store.get(store.run.id)
    assert detail is not None
    assert not any(
        step.phase is StepPhase.PLAN and step.status is StepStatus.RUNNING for step in detail.steps
    )
    decision = runner.recover_interrupted(detail)

    assert decision.disposition is RecoveryDisposition.REENQUEUE
    assert decision.changed is False
    assert store.run.version == version


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
