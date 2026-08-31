"""Pure startup-recovery policy for persisted run boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from agent_core.errors import AgentCoreError, UnknownToolError
from agent_core.state_machine import TERMINAL_STATUSES, transition_run
from agent_core.tools import ToolRegistry
from shared_contracts import (
    AgentRun,
    AgentRunDetail,
    AgentStep,
    ApprovalStatus,
    RunStatus,
    SideEffectClass,
    StepPhase,
    StepStatus,
    ToolCall,
    ToolError,
)


class RecoveryDisposition(StrEnum):
    """Operational action required after reconciling one persisted run."""

    REENQUEUE = "reenqueue"
    AWAIT_REVIEW = "await_review"
    IGNORE = "ignore"


@dataclass(frozen=True, slots=True)
class RecoveryDecision:
    """Optional atomic update plus the next operational action."""

    run: AgentRun
    disposition: RecoveryDisposition
    step: AgentStep | None = None
    changed: bool = False


def plan_recovery(
    detail: AgentRunDetail,
    *,
    tools: ToolRegistry,
    now: datetime,
) -> RecoveryDecision:
    """Classify an interrupted snapshot without performing I/O.

    Model calls and read-only tools are safe to repeat. An effectful tool may have
    completed before its result was persisted, so it is paused for explicit review
    and may only be replayed with its original idempotency key.
    """
    run = detail.run
    if run.status in TERMINAL_STATUSES or run.status is RunStatus.REVIEW_REQUIRED:
        return RecoveryDecision(run=run, disposition=RecoveryDisposition.IGNORE)
    if run.status in {RunStatus.QUEUED, RunStatus.READY, RunStatus.OBSERVING}:
        return RecoveryDecision(run=run, disposition=RecoveryDisposition.REENQUEUE)
    if run.status is RunStatus.PLANNING:
        return _retry_model_phase(detail, StepPhase.PLAN, now=now)
    if run.status is RunStatus.ADAPTING:
        return _retry_model_phase(detail, StepPhase.ADAPT, now=now)
    if run.status is RunStatus.ACTING:
        return _recover_action(detail, tools=tools, now=now)
    raise AgentCoreError(f"unsupported recovery status: {run.status.value}")


def _retry_model_phase(
    detail: AgentRunDetail,
    phase: StepPhase,
    *,
    now: datetime,
) -> RecoveryDecision:
    running_steps = _running_steps(detail, phase)
    if not running_steps:
        # PLANNING and ADAPTING are also stable boundaries: an adaptation can commit
        # PLANNING before the next PLAN attempt starts, and observation commits
        # ADAPTING before the ADAPT attempt starts. A process can stop between those
        # transactions, in which case there is no interrupted effect to close.
        return RecoveryDecision(
            run=detail.run,
            disposition=RecoveryDisposition.REENQUEUE,
        )
    if len(running_steps) != 1:
        raise AgentCoreError(
            f"{detail.run.status.value} run must have at most one running {phase.value} step"
        )
    step = running_steps[0]
    interrupted = ToolError(
        code="execution_interrupted",
        message="The process stopped before this model phase completed; the phase will be retried",
    )
    recovered_step = step.evolve(
        status=StepStatus.FAILED,
        completed_at=now,
        error=interrupted,
    )
    recovered_run = detail.run.evolve(
        version=detail.run.version + 1,
        updated_at=now,
    )
    return RecoveryDecision(
        run=recovered_run,
        step=recovered_step,
        disposition=RecoveryDisposition.REENQUEUE,
        changed=True,
    )


def _recover_action(
    detail: AgentRunDetail,
    *,
    tools: ToolRegistry,
    now: datetime,
) -> RecoveryDecision:
    step = _single_running_step(detail, StepPhase.ACT)
    try:
        calls_value = step.input.get("tool_calls")
        if isinstance(calls_value, list):
            calls = tuple(ToolCall.model_validate(value) for value in calls_value)
        else:
            calls = (ToolCall.model_validate(step.input.get("tool_call")),)
    except ValueError as exc:
        raise AgentCoreError("interrupted action has no valid persisted tool call") from exc
    if not calls:
        raise AgentCoreError("interrupted action has no valid persisted tool call")

    try:
        definitions = tuple(
            tools.resolve(
                detail.run.feature_key,
                call.tool_name,
                version=call.tool_version,
            )
            for call in calls
        )
        replay_is_safe = all(
            definition.version == call.tool_version
            and definition.side_effect is SideEffectClass.READ_ONLY
            for call, definition in zip(calls, definitions, strict=True)
        )
    except UnknownToolError:
        replay_is_safe = False

    recovery_evidence = {
        **step.output,
        "recovery": {
            "code": "action_outcome_unknown",
            "message": "The process stopped after action dispatch and before result persistence",
        },
    }
    if replay_is_safe:
        pending_step = step.evolve(
            status=StepStatus.PENDING,
            completed_at=None,
            output=recovery_evidence,
            error=None,
        )
        ready = transition_run(detail.run, RunStatus.READY, now=now)
        return RecoveryDecision(
            run=ready,
            step=pending_step,
            disposition=RecoveryDisposition.REENQUEUE,
            changed=True,
        )

    if len(calls) != 1:
        raise AgentCoreError("interrupted parallel batch was not entirely read-only")
    call = calls[0]
    if call.idempotency_key is None:
        raise AgentCoreError("interrupted effectful action has no idempotency key")
    review_call = call.evolve(approval_status=ApprovalStatus.PENDING)
    pending_step = step.evolve(
        status=StepStatus.PENDING,
        completed_at=None,
        input={**step.input, "tool_call": review_call.model_dump(mode="json")},
        output=recovery_evidence,
        error=None,
    )
    review = transition_run(detail.run, RunStatus.REVIEW_REQUIRED, now=now)
    return RecoveryDecision(
        run=review,
        step=pending_step,
        disposition=RecoveryDisposition.AWAIT_REVIEW,
        changed=True,
    )


def _single_running_step(detail: AgentRunDetail, phase: StepPhase) -> AgentStep:
    candidates = _running_steps(detail, phase)
    if len(candidates) != 1:
        raise AgentCoreError(
            f"{detail.run.status.value} run must have exactly one running {phase.value} step"
        )
    return candidates[0]


def _running_steps(detail: AgentRunDetail, phase: StepPhase) -> list[AgentStep]:
    return [
        step for step in detail.steps if step.phase is phase and step.status is StepStatus.RUNNING
    ]
