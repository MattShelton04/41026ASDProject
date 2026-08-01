"""Persisted, bounded Plan -> Act -> Observe -> Adapt execution engine."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import NoReturn
from uuid import UUID

from pydantic import BaseModel, JsonValue

from agent_core.errors import (
    AgentCoreError,
    ModelProviderError,
    RunLimitExceededError,
    ToolSchemaValidationError,
)
from agent_core.generation import ValidatedModelOutput, generate_validated
from agent_core.limits import ensure_within_limits
from agent_core.ports import (
    Clock,
    IdGenerator,
    LLMProvider,
    PromptBuilder,
    RunStore,
    StructuredModelRequest,
    ToolExecutor,
)
from agent_core.state_machine import TERMINAL_STATUSES, transition_run
from agent_core.tools import ToolPolicyDecision, ToolRegistry, authorize_tool
from shared_contracts import (
    Adaptation,
    AdaptationDecision,
    AgentRun,
    AgentRunDetail,
    AgentStep,
    ApprovalStatus,
    Observation,
    Plan,
    RunStatus,
    SideEffectClass,
    StepPhase,
    StepStatus,
    ToolCall,
    ToolError,
    ToolOutcome,
    ToolResult,
)

BLOCKED_STATUSES = TERMINAL_STATUSES | {RunStatus.REVIEW_REQUIRED}


class AgentRunner:
    """Advance persisted runs only across explicit, recoverable boundaries."""

    def __init__(
        self,
        *,
        store: RunStore,
        provider: LLMProvider,
        prompt_builder: PromptBuilder,
        tools: ToolRegistry,
        tool_executor: ToolExecutor,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._store = store
        self._provider = provider
        self._prompt_builder = prompt_builder
        self._tools = tools
        self._tool_executor = tool_executor
        self._clock = clock
        self._ids = ids

    def run_until_blocked(self, run_id: UUID) -> AgentRun:
        """Advance until terminal state or human review, never beyond configured limits."""
        while True:
            detail = self._required_detail(run_id)
            if detail.run.status in BLOCKED_STATUSES:
                return detail.run
            self.advance(detail)

    def advance(self, detail: AgentRunDetail) -> AgentRun:
        """Advance one complete phase from the supplied persisted snapshot."""
        run = detail.run
        if run.status in BLOCKED_STATUSES:
            return run
        if run.cancel_requested and run.status in {
            RunStatus.QUEUED,
            RunStatus.PLANNING,
            RunStatus.READY,
            RunStatus.ADAPTING,
        }:
            cancelled = transition_run(run, RunStatus.CANCELLED, now=self._clock.now())
            self._store.save(cancelled, expected_version=run.version)
            return cancelled
        if run.status is RunStatus.QUEUED:
            return self._plan(detail)
        if run.status is RunStatus.PLANNING:
            return self._plan(detail)
        if run.status is RunStatus.READY:
            return self._act(detail)
        if run.status is RunStatus.OBSERVING:
            return self._observe(detail)
        if run.status is RunStatus.ADAPTING:
            return self._adapt(detail)
        raise AgentCoreError(f"run is not at an automatically resumable boundary: {run.status}")

    def _plan(self, detail: AgentRunDetail) -> AgentRun:
        run = detail.run
        now = self._clock.now()
        step = self._running_step(
            run, detail.steps, StepPhase.PLAN, now, {"objective": run.objective}
        )
        if run.status is RunStatus.QUEUED:
            planning = transition_run(run, RunStatus.PLANNING, now=now)
        else:
            planning = run.model_copy(update={"version": run.version + 1, "updated_at": now})
        self._store.save(planning, expected_version=run.version, step=step)
        try:
            ensure_within_limits(planning, now=now)
        except AgentCoreError as exc:
            return self._fail_with_step(planning, step, exc, code="run_limit_reached")
        try:
            request = self._prompt_builder.build_plan_request(planning, self._tools.definitions)
            generated = generate_validated(
                self._provider,
                request,
                Plan,
                max_repairs=run.limits.max_model_repairs,
            )
            for action in generated.value.actions:
                definition = self._tools.resolve(action.tool_name)
                self._tools.validate_input(definition, action.arguments)
        except AgentCoreError as exc:
            return self._fail_with_step(planning, step, exc, code=self._error_code(exc))

        completed = self._complete_step(
            step,
            now=self._clock.now(),
            output={
                "plan": generated.value.model_dump(mode="json"),
                "model_invocation": self._invocation_summary(request, generated),
            },
        )
        ready = transition_run(planning, RunStatus.READY, now=self._clock.now())
        self._store.save(ready, expected_version=planning.version, step=completed)
        return ready

    def _act(self, detail: AgentRunDetail) -> AgentRun:
        run = detail.run
        try:
            ensure_within_limits(run, now=self._clock.now())
            plan, action_index = self._active_plan(detail.steps)
            action = plan.actions[action_index]
            definition = self._tools.resolve(action.tool_name)
            self._tools.validate_input(definition, action.arguments)
        except IndexError as exc:
            return self._fail(run, exc, code="plan_exhausted")
        except AgentCoreError as exc:
            return self._fail(run, exc, code=self._error_code(exc))

        approved = self._approved_pending_action(detail.steps)
        if approved is None:
            is_write = definition.side_effect is not SideEffectClass.READ_ONLY
            idempotency_key = (
                f"{run.id}:{action.sequence}:{definition.version}" if is_write else None
            )
            protected = definition.requires_approval or definition.side_effect in {
                SideEffectClass.DESTRUCTIVE_WRITE,
                SideEffectClass.EXTERNAL_EFFECT,
            }
            approval = ApprovalStatus.PENDING if protected else ApprovalStatus.NOT_REQUIRED
            call = ToolCall(
                id=self._ids.new(),
                run_id=run.id,
                step_id=self._ids.new(),
                tool_name=definition.name,
                tool_version=definition.version,
                arguments=action.arguments,
                idempotency_key=idempotency_key,
                approval_status=approval,
            )
            step = AgentStep(
                id=call.step_id,
                run_id=run.id,
                sequence=len(detail.steps) + 1,
                phase=StepPhase.ACT,
                status=StepStatus.RUNNING,
                started_at=self._clock.now(),
                input={"tool_call": call.model_dump(mode="json")},
            )
        else:
            step, call = approved
            if call.tool_name != action.tool_name or call.arguments != action.arguments:
                return self._fail(
                    run,
                    AgentCoreError("approved action no longer matches the active plan"),
                    code="review_action_mismatch",
                )
            step = step.model_copy(update={"status": StepStatus.RUNNING})
        try:
            policy = authorize_tool(
                definition,
                idempotency_key=call.idempotency_key,
                approval_status=call.approval_status,
            )
        except AgentCoreError as exc:
            return self._fail(run, exc, code="tool_policy_rejected")

        if policy is ToolPolicyDecision.DENY:
            return self._fail_with_step(
                run, step, AgentCoreError("tool call denied"), code="tool_denied"
            )
        if policy is ToolPolicyDecision.REQUIRE_REVIEW:
            step = step.model_copy(update={"status": StepStatus.PENDING})
            review = transition_run(run, RunStatus.REVIEW_REQUIRED, now=self._clock.now())
            self._store.save(review, expected_version=run.version, step=step)
            return review

        acting = transition_run(run, RunStatus.ACTING, now=self._clock.now())
        self._store.save(acting, expected_version=run.version, step=step)
        result = self._tool_executor.execute(call, definition)
        if result.call_id != call.id:
            return self._fail_with_step(
                acting,
                step,
                AgentCoreError("tool executor returned a result for a different call"),
                code="invalid_tool_result",
            )
        if result.outcome is ToolOutcome.SUCCEEDED:
            try:
                self._tools.validate_output(definition, result.content)
            except ToolSchemaValidationError as exc:
                result = ToolResult(
                    call_id=call.id,
                    outcome=ToolOutcome.FAILED,
                    error=ToolError(code="invalid_tool_output", message=str(exc)),
                    duration_ms=result.duration_ms,
                    retryable=False,
                )

        counted = acting.model_copy(update={"tool_call_count": acting.tool_call_count + 1})
        completed = self._complete_step(
            step,
            now=self._clock.now(),
            output={"tool_result": result.model_dump(mode="json")},
        )
        if result.outcome is ToolOutcome.FAILED and not result.retryable:
            error = result.error or ToolError(code="tool_failed", message="Tool execution failed")
            failed = transition_run(counted, RunStatus.FAILED, now=self._clock.now(), error=error)
            failed_step = completed.model_copy(update={"status": StepStatus.FAILED, "error": error})
            self._store.save(failed, expected_version=acting.version, step=failed_step)
            return failed

        observing = transition_run(counted, RunStatus.OBSERVING, now=self._clock.now())
        self._store.save(observing, expected_version=acting.version, step=completed)
        return observing

    def _observe(self, detail: AgentRunDetail) -> AgentRun:
        run = detail.run
        plan, _ = self._active_plan(detail.steps, include_current_action=True)
        result = self._last_tool_result(detail.steps)
        outcome_fact = f"Tool call {result.outcome.value}."
        error_fact = f"Error code: {result.error.code}." if result.error else "No tool error."
        observation = Observation(
            facts=(outcome_fact, error_fact),
            unassessed_criteria=plan.success_criteria,
        )
        now = self._clock.now()
        step = AgentStep(
            id=self._ids.new(),
            run_id=run.id,
            sequence=len(detail.steps) + 1,
            phase=StepPhase.OBSERVE,
            status=StepStatus.SUCCEEDED,
            started_at=now,
            completed_at=now,
            input={"tool_result": result.model_dump(mode="json")},
            output={"observation": observation.model_dump(mode="json")},
        )
        adapting = transition_run(run, RunStatus.ADAPTING, now=now)
        self._store.save(adapting, expected_version=run.version, step=step)
        return adapting

    def _adapt(self, detail: AgentRunDetail) -> AgentRun:
        run = detail.run
        plan, _ = self._active_plan(detail.steps, include_current_action=True)
        result = self._last_tool_result(detail.steps)
        observation = self._last_observation(detail.steps)
        now = self._clock.now()
        step = self._running_step(
            run,
            detail.steps,
            StepPhase.ADAPT,
            now,
            {"observation": observation.model_dump(mode="json")},
        )
        in_progress = run.model_copy(update={"version": run.version + 1, "updated_at": now})
        self._store.save(in_progress, expected_version=run.version, step=step)
        try:
            request = self._prompt_builder.build_adaptation_request(
                in_progress, plan, result, observation
            )
            generated = generate_validated(
                self._provider,
                request,
                Adaptation,
                max_repairs=run.limits.max_model_repairs,
            )
        except AgentCoreError as exc:
            return self._fail_with_step(in_progress, step, exc, code=self._error_code(exc))

        completed = self._complete_step(
            step,
            now=self._clock.now(),
            output={
                "adaptation": generated.value.model_dump(mode="json"),
                "model_invocation": self._invocation_summary(request, generated),
            },
        )
        counted = in_progress.model_copy(
            update={"iteration_count": in_progress.iteration_count + 1}
        )
        target, final_result, error = self._adaptation_transition(generated.value)
        next_run = transition_run(
            counted,
            target,
            now=self._clock.now(),
            final_result=final_result,
            error=error,
        )
        self._store.save(next_run, expected_version=in_progress.version, step=completed)
        return next_run

    @staticmethod
    def _adaptation_transition(
        adaptation: Adaptation,
    ) -> tuple[RunStatus, dict[str, JsonValue] | None, ToolError | None]:
        mapping = {
            AdaptationDecision.CONTINUE: RunStatus.READY,
            AdaptationDecision.REPLAN: RunStatus.PLANNING,
            AdaptationDecision.REQUEST_REVIEW: RunStatus.REVIEW_REQUIRED,
            AdaptationDecision.COMPLETE: RunStatus.SUCCEEDED,
            AdaptationDecision.FAIL: RunStatus.FAILED,
        }
        error = None
        if adaptation.decision is AdaptationDecision.FAIL:
            error = ToolError(code="adaptation_failed", message=adaptation.justification)
        return mapping[adaptation.decision], adaptation.final_result, error

    def _fail(self, run: AgentRun, exc: Exception, *, code: str) -> AgentRun:
        error = ToolError(code=code, message=self._safe_message(exc))
        failed = transition_run(run, RunStatus.FAILED, now=self._clock.now(), error=error)
        self._store.save(failed, expected_version=run.version)
        return failed

    def _fail_with_step(
        self, run: AgentRun, step: AgentStep, exc: Exception, *, code: str
    ) -> AgentRun:
        error = ToolError(code=code, message=self._safe_message(exc))
        failed_step = step.model_copy(
            update={
                "status": StepStatus.FAILED,
                "completed_at": self._clock.now(),
                "error": error,
            }
        )
        failed = transition_run(run, RunStatus.FAILED, now=self._clock.now(), error=error)
        self._store.save(failed, expected_version=run.version, step=failed_step)
        return failed

    @staticmethod
    def _safe_message(exc: Exception) -> str:
        if isinstance(exc, ModelProviderError):
            return str(exc)
        if isinstance(exc, (AgentCoreError, IndexError)):
            return str(exc) or type(exc).__name__
        return "Unexpected orchestration failure"

    @staticmethod
    def _error_code(exc: AgentCoreError) -> str:
        if isinstance(exc, ModelProviderError):
            return exc.code
        if isinstance(exc, RunLimitExceededError):
            return "run_limit_reached"
        return "invalid_model_or_tool_data"

    @staticmethod
    def _invocation_summary[OutputT: BaseModel](
        request: StructuredModelRequest,
        generated: ValidatedModelOutput[OutputT],
    ) -> dict[str, JsonValue]:
        return {
            "provider": generated.invocation.provider,
            "model": generated.invocation.model,
            "model_digest": generated.invocation.model_digest,
            "metrics": generated.invocation.metrics.model_dump(mode="json"),
            "prompt_id": request.prompt_id,
            "prompt_version": request.prompt_version,
            "prompt_hash": request.prompt_hash,
            "rendered_input_hash": request.rendered_input_hash,
            "repair_count": generated.repair_count,
        }

    def _running_step(
        self,
        run: AgentRun,
        existing: tuple[AgentStep, ...],
        phase: StepPhase,
        now: datetime,
        input_data: Mapping[str, JsonValue],
    ) -> AgentStep:
        return AgentStep(
            id=self._ids.new(),
            run_id=run.id,
            sequence=len(existing) + 1,
            phase=phase,
            status=StepStatus.RUNNING,
            started_at=now,
            input=dict(input_data),
        )

    @staticmethod
    def _complete_step(
        step: AgentStep, *, now: datetime, output: Mapping[str, JsonValue]
    ) -> AgentStep:
        return step.model_copy(
            update={
                "status": StepStatus.SUCCEEDED,
                "completed_at": now,
                "output": dict(output),
            }
        )

    @staticmethod
    def _active_plan(
        steps: tuple[AgentStep, ...], *, include_current_action: bool = False
    ) -> tuple[Plan, int]:
        plan_position, plan = next(
            (
                (index, Plan.model_validate(step.output["plan"]))
                for index, step in reversed(list(enumerate(steps)))
                if step.phase is StepPhase.PLAN and "plan" in step.output
            ),
            (None, None),
        )
        if plan_position is None or plan is None:
            raise AgentCoreError("run has no persisted valid plan")
        action_count = sum(
            step.phase is StepPhase.ACT and step.status is not StepStatus.PENDING
            for step in steps[plan_position + 1 :]
        )
        if include_current_action:
            action_count = max(0, action_count - 1)
        return plan, action_count

    @staticmethod
    def _last_tool_result(steps: tuple[AgentStep, ...]) -> ToolResult:
        for step in reversed(steps):
            if step.phase is StepPhase.ACT and "tool_result" in step.output:
                return ToolResult.model_validate(step.output["tool_result"])
        raise AgentCoreError("run has no persisted tool result")

    @staticmethod
    def _last_observation(steps: tuple[AgentStep, ...]) -> Observation:
        for step in reversed(steps):
            if step.phase is StepPhase.OBSERVE and "observation" in step.output:
                return Observation.model_validate(step.output["observation"])
        raise AgentCoreError("run has no persisted observation")

    @staticmethod
    def _approved_pending_action(steps: tuple[AgentStep, ...]) -> tuple[AgentStep, ToolCall] | None:
        for step in reversed(steps):
            if step.phase is not StepPhase.ACT or step.status is not StepStatus.PENDING:
                continue
            call = ToolCall.model_validate(step.input.get("tool_call"))
            if call.approval_status is ApprovalStatus.APPROVED:
                return step, call
        return None

    def _required_detail(self, run_id: UUID) -> AgentRunDetail:
        detail = self._store.get(run_id)
        if detail is None:
            self._missing_run(run_id)
        return detail

    @staticmethod
    def _missing_run(run_id: UUID) -> NoReturn:
        raise AgentCoreError(f"agent run not found: {run_id}")
