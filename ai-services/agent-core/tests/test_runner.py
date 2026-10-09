"""End-to-end deterministic tests for the persisted four-phase runner."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import Barrier, Lock
from uuid import UUID, uuid4

import pytest
from pydantic import JsonValue

from agent_core import (
    AgentRunner,
    CompletionValidator,
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
from agent_core.identifier_schema import IdentifierSchemaResolver
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
    TrustedIdentifier,
)
from shared_testkit import ScriptedLLMProvider

NOW = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)


def test_identifier_schema_rejects_ambiguous_and_malformed_metadata() -> None:
    conflicting = {
        "allOf": [
            {"x-identifier-kind": "release_id"},
            {"x-identifier-kind": "run_id"},
        ]
    }
    with pytest.raises(ModelOutputValidationError, match="conflicting kinds"):
        IdentifierSchemaResolver(conflicting).kind("subject", conflicting, "value")

    invalid_pattern = {"patternProperties": {"[": {"type": "string"}}}
    with pytest.raises(ModelOutputValidationError, match="invalid property pattern"):
        IdentifierSchemaResolver(invalid_pattern).child(invalid_pattern, "subject", {})

    cyclic = {"$defs": {"cycle": {"$ref": "#/$defs/cycle"}}}
    with pytest.raises(ModelOutputValidationError, match="cyclic"):
        IdentifierSchemaResolver(cyclic).kind("subject", {"$ref": "#/$defs/cycle"}, "value")


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
        definitions: tuple[ToolDefinition, ...],
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
        definitions: tuple[ToolDefinition, ...],
        plan: Plan,
        tool_result: ToolResult,
        observation: Observation,
        tool_results: tuple[ToolResult, ...],
    ) -> StructuredModelRequest:
        if self.fail_role is ModelRole.ADAPTER:
            raise ValueError("private prompt validation detail")
        return super().build_adaptation_request(
            run, definitions, plan, tool_result, observation, tool_results
        )


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


def _parallel_tools(count: int) -> tuple[ToolDefinition, ...]:
    return tuple(
        _tool().evolve(name=f"student_1.records.search_{index}.v1") for index in range(1, count + 1)
    )


def _parallel_plan(tools: tuple[ToolDefinition, ...]) -> dict[str, object]:
    plan = _plan()
    plan["actions"] = [
        {
            "sequence": 1,
            "tool_name": definition.name,
            "arguments": {"query": f"query-{index}"},
            "purpose": f"Gather independent evidence {index}",
        }
        for index, definition in enumerate(tools, start=1)
    ]
    return plan


def _runner(
    outcomes: list[StructuredModelResult | Exception],
    *,
    tool: ToolDefinition | None = None,
    tools: tuple[ToolDefinition, ...] | None = None,
    tool_outcome: ToolOutcome = ToolOutcome.SUCCEEDED,
    tool_outcomes: tuple[ToolOutcome, ...] = (),
    limits: RunLimits | None = None,
    tool_exception: Exception | None = None,
    cancel_during_execute: bool = False,
    clock: FixedClock | None = None,
    prompt_builder: TestPromptBuilder | None = None,
    tool_allowlist: tuple[str, ...] | None = None,
    trusted_identifiers: tuple[TrustedIdentifier, ...] = (),
    completion_validator: CompletionValidator | None = None,
) -> tuple[AgentRunner, MemoryStore, RecordingToolExecutor]:
    run = create_run(
        AgentRunRequest(
            feature_key="student-1-feature",
            objective="Find verified records",
            limits=limits or RunLimits(),
            tool_allowlist=tool_allowlist,
            trusted_identifiers=trusted_identifiers,
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
        tools=ToolRegistry(tools or (tool or _tool(),)),
        tool_executor=executor,
        clock=clock or FixedClock(),
        ids=RandomIds(),
        completion_validator=completion_validator,
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


def test_parallel_read_only_stage_dispatches_concurrently_and_persists_ordered_results() -> None:
    tools = _parallel_tools(3)
    runner, store, _ = _runner(
        [_model_result(_parallel_plan(tools)), _model_result(_adaptation("complete"))],
        tools=tools,
    )
    barrier = Barrier(3)
    lock = Lock()
    active = 0
    maximum_active = 0
    calls: list[ToolCall] = []

    class ConcurrentExecutor:
        def execute(
            self,
            call: ToolCall,
            definition: ToolDefinition,
            *,
            timeout_ms: int,
        ) -> ToolResult:
            nonlocal active, maximum_active
            with lock:
                active += 1
                maximum_active = max(maximum_active, active)
                calls.append(call)
            barrier.wait(timeout=2)
            with lock:
                active -= 1
            return ToolResult(
                call_id=call.id,
                outcome=ToolOutcome.SUCCEEDED,
                content={"count": 1},
                duration_ms=2,
            )

    runner._tool_executor = ConcurrentExecutor()  # type: ignore[assignment]

    result = runner.run_until_blocked(store.run.id)

    assert result.status is RunStatus.SUCCEEDED
    assert result.tool_call_count == 3
    assert maximum_active == 3
    act_steps = [step for step in store.steps if step.phase is StepPhase.ACT]
    assert len(act_steps) == 1
    assert [call["tool_name"] for call in act_steps[0].input["tool_calls"]] == [
        definition.name for definition in tools
    ]
    assert len(act_steps[0].output["tool_results"]) == 3
    assert len(calls) == 3


def test_parallel_stage_is_chunked_by_max_parallel_tools() -> None:
    tools = _parallel_tools(4)
    runner, store, executor = _runner(
        [_model_result(_parallel_plan(tools)), _model_result(_adaptation("complete"))],
        tools=tools,
        limits=RunLimits(max_parallel_tools=2),
    )

    result = runner.run_until_blocked(store.run.id)

    assert result.status is RunStatus.SUCCEEDED
    assert result.tool_call_count == 4
    assert len(executor.calls) == 4
    act_steps = [step for step in store.steps if step.phase is StepPhase.ACT]
    assert [len(step.output["tool_results"]) for step in act_steps] == [2, 2]


def test_parallel_batch_mixed_outcomes_are_observed_together() -> None:
    tools = _parallel_tools(2)
    runner, store, _ = _runner(
        [_model_result(_parallel_plan(tools)), _model_result(_adaptation("fail"))],
        tools=tools,
    )

    class MixedExecutor:
        def execute(
            self,
            call: ToolCall,
            definition: ToolDefinition,
            *,
            timeout_ms: int,
        ) -> ToolResult:
            if definition.name == tools[1].name:
                return ToolResult(
                    call_id=call.id,
                    outcome=ToolOutcome.TIMED_OUT,
                    error=ToolError(code="tool_timeout", message="Timed out"),
                    duration_ms=timeout_ms,
                    retryable=True,
                )
            return ToolResult(
                call_id=call.id,
                outcome=ToolOutcome.SUCCEEDED,
                content={"count": 1},
                duration_ms=1,
            )

    runner._tool_executor = MixedExecutor()  # type: ignore[assignment]

    result = runner.run_until_blocked(store.run.id)

    assert result.status is RunStatus.FAILED
    act_step = next(step for step in store.steps if step.phase is StepPhase.ACT)
    assert [item["outcome"] for item in act_step.output["tool_results"]] == [
        "succeeded",
        "timed_out",
    ]
    observe = next(step for step in store.steps if step.phase is StepPhase.OBSERVE)
    facts = observe.output["observation"]["facts"]
    assert any("succeeded" in fact for fact in facts)
    assert any("tool_timeout" in fact for fact in facts)


def test_parallel_batch_cannot_exceed_remaining_tool_call_budget() -> None:
    tools = _parallel_tools(3)
    runner, store, executor = _runner(
        [_model_result(_parallel_plan(tools))],
        tools=tools,
        limits=RunLimits(max_tool_calls=2, max_parallel_tools=3),
    )

    result = runner.run_until_blocked(store.run.id)

    assert result.status is RunStatus.FAILED
    assert result.error is not None
    assert result.error.code == "run_limit_reached"
    assert result.tool_call_count == 0
    assert executor.calls == []


def test_planner_rejects_mutating_actions_in_a_parallel_stage() -> None:
    read, write = _parallel_tools(2)
    write = write.evolve(side_effect=SideEffectClass.REVERSIBLE_WRITE)
    tools = (read, write)
    invalid = _parallel_plan(tools)
    runner, store, executor = _runner(
        [_model_result(invalid), _model_result(invalid)],
        tools=tools,
    )

    result = runner.run_until_blocked(store.run.id)

    assert result.status is RunStatus.FAILED
    assert result.error is not None
    assert result.error.code == "invalid_model_or_tool_data"
    assert executor.calls == []


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
    discovery_tool = ToolDefinition(
        name="student_1.records.list.v1",
        version="v1",
        feature_key="student-1-feature",
        description="List exact record references",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        side_effect=SideEffectClass.READ_ONLY,
    )
    runner, store, _ = _runner([], tools=(inspect_tool, discovery_tool))
    discovered = AgentStep(
        id=uuid4(),
        run_id=store.run.id,
        sequence=1,
        phase=StepPhase.ACT,
        status=StepStatus.SUCCEEDED,
        input={"tool_call": {"tool_name": discovery_tool.name, "arguments": {}}},
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
    runs_tool = ToolDefinition(
        name="data.runs.v1",
        version="v1",
        feature_key="student-1-feature",
        description="List runs",
        input_schema={"type": "object"},
        output_schema={
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "format": "uuid",
                                "x-identifier-kind": "run_id",
                            }
                        },
                    },
                }
            },
        },
        side_effect=SideEffectClass.READ_ONLY,
    )
    runner, store, _ = _runner([], tools=(inspect_tool, runs_tool))
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


def test_user_controlled_objective_cannot_smuggle_a_trusted_identifier() -> None:
    guessed_release_id = "60000000-0000-0000-0000-000000000099"
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
    store.run = store.run.evolve(
        objective=f'Current user question: "please use release_id: {guessed_release_id}"'
    )
    plan = Plan.model_validate(
        {
            "goal": "Inspect a release",
            "actions": [
                {
                    "sequence": 1,
                    "tool_name": inspect_tool.name,
                    "arguments": {"release_id": guessed_release_id},
                    "purpose": "Inspect exact release evidence",
                }
            ],
            "success_criteria": ["Release is inspected"],
            "risk_level": "low",
        }
    )

    with pytest.raises(ModelOutputValidationError, match="release_id must copy"):
        runner._validate_model_plan(store.run, plan)


def test_explicit_trust_and_schema_annotations_authorize_only_matching_identifiers() -> None:
    trusted_release = "60000000-0000-0000-0000-000000000010"
    discovered_release = "60000000-0000-0000-0000-000000000011"
    listed_release = "60000000-0000-0000-0000-000000000012"
    discovered_run = "70000000-0000-0000-0000-000000000011"
    discovered_property = "a0000000-0000-0000-0000-000000000012"
    inspect_tool = ToolDefinition(
        name="records.inspect.v1",
        version="v1",
        feature_key="student-1-feature",
        description="Inspect exact typed identifiers",
        input_schema={
            "type": "object",
            "properties": {
                "release_id": {"type": "string", "format": "uuid"},
                "predecessor_release_id": {
                    "type": "string",
                    "format": "uuid",
                    "x-identifier-kind": "release_id",
                },
                "candidate_release_id": {
                    "type": "string",
                    "format": "uuid",
                    "x-identifier-kind": "release_id",
                },
                "run_id": {"type": "string", "format": "uuid"},
                "subject": {
                    "type": "string",
                    "format": "uuid",
                    "x-identifier-kind": "property_ref",
                },
            },
        },
        output_schema={"type": "object"},
        side_effect=SideEffectClass.READ_ONLY,
    )
    discovery_tool = ToolDefinition(
        name="records.list.v1",
        version="v1",
        feature_key="student-1-feature",
        description="Discover typed identifiers",
        input_schema={"type": "object"},
        output_schema={
            "type": "object",
            "properties": {
                "release": {
                    "type": "object",
                    "properties": {"id": {"type": "string", "x-identifier-kind": "release_id"}},
                },
                "run": {
                    "type": "object",
                    "properties": {"id": {"type": "string", "x-identifier-kind": "run_id"}},
                },
                "subject": {
                    "type": "string",
                    "x-identifier-kind": "property_ref",
                },
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"id": {"type": "string", "x-identifier-kind": "release_id"}},
                    },
                },
            },
        },
        side_effect=SideEffectClass.READ_ONLY,
    )
    runner, store, _ = _runner(
        [],
        tools=(inspect_tool, discovery_tool),
        trusted_identifiers=(TrustedIdentifier(kind="release_id", value=UUID(trusted_release)),),
    )
    run = store.run
    evidence = AgentStep(
        id=uuid4(),
        run_id=run.id,
        sequence=1,
        phase=StepPhase.ACT,
        status=StepStatus.SUCCEEDED,
        input={"tool_call": {"tool_name": discovery_tool.name, "arguments": {}}},
        output={
            "tool_result": {
                "outcome": "succeeded",
                "content": {
                    "release": {"id": discovered_release},
                    "run": {"id": discovered_run},
                    "subject": discovered_property,
                    "items": [{"id": listed_release}],
                },
            }
        },
    )

    runner._validate_exact_identifiers(
        run,
        inspect_tool,
        {
            "release_id": trusted_release,
            "predecessor_release_id": discovered_release,
            "candidate_release_id": listed_release,
            "run_id": discovered_run,
            "subject": discovered_property,
        },
        (evidence,),
    )


def test_identifier_provenance_resolves_local_refs_and_ignores_unannotated_bare_ids() -> None:
    release_id = "60000000-0000-0000-0000-000000000015"
    inspect_tool = ToolDefinition(
        name="records.inspect.v1",
        version="v1",
        feature_key="student-1-feature",
        description="Inspect one release",
        input_schema={
            "type": "object",
            "properties": {"release_id": {"type": "string", "format": "uuid"}},
        },
        output_schema={"type": "object"},
        side_effect=SideEffectClass.READ_ONLY,
    )
    annotated_tool = ToolDefinition(
        name="records.annotated.v1",
        version="v1",
        feature_key="student-1-feature",
        description="Return an annotated identifier through local refs",
        input_schema={"type": "object"},
        output_schema={
            "type": "object",
            "properties": {"record": {"$ref": "#/$defs/record"}},
            "$defs": {
                "uuid": {"type": "string", "format": "uuid"},
                "record": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "$ref": "#/$defs/uuid",
                            "x-identifier-kind": "release_id",
                        }
                    },
                },
            },
        },
        side_effect=SideEffectClass.READ_ONLY,
    )
    unannotated_tool = ToolDefinition(
        name="records.unannotated.v1",
        version="v1",
        feature_key="student-1-feature",
        description="Return an ambiguous bare identifier",
        input_schema={"type": "object"},
        output_schema={"type": "object", "properties": {"id": {"type": "string"}}},
        side_effect=SideEffectClass.READ_ONLY,
    )
    runner, store, _ = _runner([], tools=(inspect_tool, annotated_tool, unannotated_tool))

    def evidence(tool_name: str, content: dict[str, object]) -> AgentStep:
        return AgentStep(
            id=uuid4(),
            run_id=store.run.id,
            sequence=1,
            phase=StepPhase.ACT,
            status=StepStatus.SUCCEEDED,
            input={"tool_call": {"tool_name": tool_name, "arguments": {}}},
            output={"tool_result": {"outcome": "succeeded", "content": content}},
        )

    runner._validate_exact_identifiers(
        store.run,
        inspect_tool,
        {"release_id": release_id},
        (evidence(annotated_tool.name, {"record": {"id": release_id}}),),
    )
    with pytest.raises(ModelOutputValidationError, match="release_id must copy"):
        runner._validate_exact_identifiers(
            store.run,
            inspect_tool,
            {"release_id": release_id},
            (evidence(unannotated_tool.name, {"id": release_id}),),
        )


@pytest.mark.parametrize(
    "composed_schema",
    [
        {"allOf": [{"type": "string", "x-identifier-kind": "property_ref"}]},
        {"anyOf": [{"type": "string", "x-identifier-kind": "property_ref"}]},
        {"oneOf": [{"type": "string", "x-identifier-kind": "property_ref"}]},
        {"if": {}, "then": {"type": "string", "x-identifier-kind": "property_ref"}},
    ],
)
def test_identifier_provenance_fails_closed_for_composed_schema_annotations(
    composed_schema: dict[str, object],
) -> None:
    guessed_ref = "a0000000-0000-0000-0000-000000000090"
    inspect_tool = ToolDefinition(
        name="records.inspect.v1",
        version="v1",
        feature_key="student-1-feature",
        description="Inspect one typed subject",
        input_schema={"type": "object", "properties": {"subject": composed_schema}},
        output_schema={"type": "object"},
        side_effect=SideEffectClass.READ_ONLY,
    )
    runner, store, _ = _runner([], tool=inspect_tool)

    with pytest.raises(ModelOutputValidationError, match="subject must copy"):
        runner._validate_exact_identifiers(
            store.run,
            inspect_tool,
            {"subject": guessed_ref},
            (),
        )


def test_identifier_provenance_supports_pattern_properties_and_rejects_unknown_uuid_paths() -> None:
    trusted_ref = "a0000000-0000-0000-0000-000000000091"
    inspect_tool = ToolDefinition(
        name="records.inspect.v1",
        version="v1",
        feature_key="student-1-feature",
        description="Inspect one typed subject",
        input_schema={
            "type": "object",
            "patternProperties": {
                "^subject$": {"type": "string", "x-identifier-kind": "property_ref"}
            },
            "properties": {"opaque": {"type": "string"}},
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        side_effect=SideEffectClass.READ_ONLY,
    )
    runner, store, _ = _runner(
        [],
        tool=inspect_tool,
        trusted_identifiers=(TrustedIdentifier(kind="property_ref", value=UUID(trusted_ref)),),
    )

    runner._validate_exact_identifiers(
        store.run,
        inspect_tool,
        {"subject": trusted_ref},
        (),
    )
    with pytest.raises(ModelOutputValidationError, match="opaque must copy"):
        runner._validate_exact_identifiers(
            store.run,
            inspect_tool,
            {"opaque": trusted_ref},
            (),
        )


@pytest.mark.parametrize(
    ("input_schema", "arguments", "field"),
    [
        (
            {
                "type": "object",
                "properties": {
                    "subject": {
                        "oneOf": [
                            {
                                "type": "string",
                                "pattern": "^6",
                                "x-identifier-kind": "release_id",
                            },
                            {"type": "string", "pattern": "^7"},
                        ]
                    }
                },
            },
            {"subject": "70000000-0000-0000-0000-000000000099"},
            "subject",
        ),
        (
            {
                "type": "object",
                "properties": {"subject": {"type": "string"}},
                "additionalProperties": {
                    "type": "string",
                    "x-identifier-kind": "release_id",
                },
            },
            {"subject": "70000000-0000-0000-0000-000000000099"},
            "subject",
        ),
        (
            {
                "type": "object",
                "properties": {"subject": True},
                "additionalProperties": {
                    "type": "string",
                    "x-identifier-kind": "release_id",
                },
            },
            {"subject": "70000000-0000-0000-0000-000000000099"},
            "subject",
        ),
        (
            {
                "type": "object",
                "patternProperties": {"^subject$": True},
                "additionalProperties": {
                    "type": "string",
                    "x-identifier-kind": "release_id",
                },
            },
            {"subject": "70000000-0000-0000-0000-000000000099"},
            "subject",
        ),
        (
            {
                "type": "object",
                "properties": {
                    "values": {
                        "type": "array",
                        "prefixItems": [{"type": "string"}],
                        "items": {
                            "type": "string",
                            "x-identifier-kind": "release_id",
                        },
                    }
                },
            },
            {"values": ["70000000-0000-0000-0000-000000000099"]},
            "values",
        ),
    ],
)
def test_identifier_provenance_does_not_authorize_non_applicable_schema_paths(
    input_schema: dict[str, object],
    arguments: dict[str, object],
    field: str,
) -> None:
    trusted = UUID("70000000-0000-0000-0000-000000000099")
    inspect_tool = ToolDefinition(
        name="records.inspect.v1",
        version="v1",
        feature_key="student-1-feature",
        description="Inspect one typed subject",
        input_schema=input_schema,
        output_schema={"type": "object"},
        side_effect=SideEffectClass.READ_ONLY,
    )
    runner, store, _ = _runner(
        [],
        tool=inspect_tool,
        trusted_identifiers=(TrustedIdentifier(kind="release_id", value=trusted),),
    )

    with pytest.raises(ModelOutputValidationError, match=rf"{field} must copy"):
        runner._validate_exact_identifiers(
            store.run,
            inspect_tool,
            arguments,
            (),
        )


def test_identifier_provenance_rejects_untrusted_uuid_object_keys() -> None:
    guessed_ref = "a0000000-0000-0000-0000-000000000092"
    inspect_tool = ToolDefinition(
        name="records.inspect.v1",
        version="v1",
        feature_key="student-1-feature",
        description="Inspect a keyed record map",
        input_schema={
            "type": "object",
            "properties": {
                "records": {
                    "type": "object",
                    "propertyNames": {
                        "format": "uuid",
                        "x-identifier-kind": "record_ref",
                    },
                    "additionalProperties": {"type": "boolean"},
                }
            },
        },
        output_schema={"type": "object"},
        side_effect=SideEffectClass.READ_ONLY,
    )
    runner, store, _ = _runner([], tool=inspect_tool)

    with pytest.raises(ModelOutputValidationError, match="identifier-valued object key"):
        runner._validate_exact_identifiers(
            store.run,
            inspect_tool,
            {"records": {guessed_ref: True}},
            (),
        )


def test_identifier_provenance_normalizes_compact_uuid_representations() -> None:
    canonical = "60000000-0000-0000-0000-000000000099"
    compact = canonical.replace("-", "")
    inspect_tool = ToolDefinition(
        name="records.inspect.v1",
        version="v1",
        feature_key="student-1-feature",
        description="Inspect one release",
        input_schema={
            "type": "object",
            "properties": {"release_id": {"type": "string"}},
        },
        output_schema={"type": "object"},
        side_effect=SideEffectClass.READ_ONLY,
    )
    runner, store, _ = _runner([], tool=inspect_tool)

    with pytest.raises(ModelOutputValidationError, match="release_id must copy"):
        runner._validate_exact_identifiers(
            store.run,
            inspect_tool,
            {"release_id": compact},
            (),
        )

    trusted_runner, trusted_store, _ = _runner(
        [],
        tool=inspect_tool,
        trusted_identifiers=(TrustedIdentifier(kind="release_id", value=UUID(canonical)),),
    )
    trusted_runner._validate_exact_identifiers(
        trusted_store.run,
        inspect_tool,
        {"release_id": compact},
        (),
    )


def test_identifier_provenance_preserves_ref_sibling_properties() -> None:
    release_id = "60000000-0000-0000-0000-000000000016"
    inspect_tool = ToolDefinition(
        name="records.inspect.v1",
        version="v1",
        feature_key="student-1-feature",
        description="Inspect one release",
        input_schema={
            "type": "object",
            "properties": {"release_id": {"type": "string", "format": "uuid"}},
        },
        output_schema={"type": "object"},
        side_effect=SideEffectClass.READ_ONLY,
    )
    discovery_tool = ToolDefinition(
        name="records.list.v1",
        version="v1",
        feature_key="student-1-feature",
        description="Return a release with additional sibling fields",
        input_schema={"type": "object"},
        output_schema={
            "type": "object",
            "properties": {
                "record": {
                    "$ref": "#/$defs/record",
                    "properties": {"label": {"type": "string"}},
                }
            },
            "$defs": {
                "record": {
                    "type": "object",
                    "properties": {"id": {"type": "string", "x-identifier-kind": "release_id"}},
                }
            },
        },
        side_effect=SideEffectClass.READ_ONLY,
    )
    runner, store, _ = _runner([], tools=(inspect_tool, discovery_tool))
    evidence = AgentStep(
        id=uuid4(),
        run_id=store.run.id,
        sequence=1,
        phase=StepPhase.ACT,
        status=StepStatus.SUCCEEDED,
        input={"tool_call": {"tool_name": discovery_tool.name, "arguments": {}}},
        output={
            "tool_result": {
                "outcome": "succeeded",
                "content": {"record": {"id": release_id, "label": "candidate"}},
            }
        },
    )

    runner._validate_exact_identifiers(
        store.run,
        inspect_tool,
        {"release_id": release_id},
        (evidence,),
    )


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


def test_interrupted_parallel_read_only_batch_replays_the_full_original_batch() -> None:
    tools = _parallel_tools(2)
    runner, store, executor = _runner(
        [_model_result(_parallel_plan(tools)), _model_result(_adaptation("complete"))],
        tools=tools,
    )
    ready = runner.advance(store.get(store.run.id))  # type: ignore[arg-type]
    step_id = uuid4()
    calls = tuple(
        ToolCall(
            id=uuid4(),
            run_id=ready.id,
            step_id=step_id,
            tool_name=definition.name,
            tool_version=definition.version,
            arguments={"query": f"query-{index}"},
            approval_status=ApprovalStatus.NOT_REQUIRED,
        )
        for index, definition in enumerate(tools, start=1)
    )
    step = AgentStep(
        id=step_id,
        run_id=ready.id,
        sequence=2,
        phase=StepPhase.ACT,
        status=StepStatus.RUNNING,
        started_at=NOW,
        input={"stage": 1, "tool_calls": [call.model_dump(mode="json") for call in calls]},
    )
    dispatching = ready.evolve(tool_call_count=2)
    acting = transition_run(dispatching, RunStatus.ACTING, now=NOW)
    store.save(acting, expected_version=ready.version, step=step)

    detail = store.get(store.run.id)
    assert detail is not None
    decision = runner.recover_interrupted(detail)

    assert decision.disposition is RecoveryDisposition.REENQUEUE
    assert store.run.status is RunStatus.READY
    assert store.steps[-1].status is StepStatus.PENDING

    result = runner.run_until_blocked(store.run.id)

    assert result.status is RunStatus.SUCCEEDED
    assert result.tool_call_count == 4
    assert {call.id for call in executor.calls} == {call.id for call in calls}
    assert store.steps[-3].output["recovery"]["code"] == "action_outcome_unknown"


class _SummaryLengthValidator:
    """Prompt-set output contract double: summaries must mention a verified record."""

    def __init__(self) -> None:
        self.seen: list[dict[str, object]] = []

    def validate_completion(self, run: AgentRun, final_result: dict[str, JsonValue]) -> None:
        self.seen.append(dict(final_result))
        if "verified" not in str(final_result.get("summary", "")):
            raise ValueError("summary must cite the verified record")


def test_completion_validator_repairs_then_accepts_a_contract_final_result() -> None:
    invalid = _adaptation("complete")
    invalid["final_result"] = {"summary": "Found something"}
    validator = _SummaryLengthValidator()
    runner, store, _ = _runner(
        [
            _model_result(_plan()),
            _model_result(invalid),
            _model_result(_adaptation("complete")),
        ],
        completion_validator=validator,
    )

    result = runner.run_until_blocked(store.run.id)

    assert result.status is RunStatus.SUCCEEDED
    assert result.final_result == {"summary": "Found one verified record"}
    assert len(validator.seen) == 2


def test_completion_validator_fails_the_run_after_bounded_repair() -> None:
    invalid = _adaptation("complete")
    invalid["final_result"] = {"summary": "Found something"}
    runner, store, _ = _runner(
        [_model_result(_plan()), _model_result(invalid), _model_result(invalid)],
        completion_validator=_SummaryLengthValidator(),
    )

    result = runner.run_until_blocked(store.run.id)

    assert result.status is RunStatus.FAILED
    assert result.error is not None
    assert result.error.code == "invalid_model_or_tool_data"
