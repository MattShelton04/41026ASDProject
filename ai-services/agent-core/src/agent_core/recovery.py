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
    step = _single_running_step(detail, phase)
    interrupted = ToolError(
        code="execution_interrupted",
        message="The process stopped before this model phase completed; the phase will be retried",
    )
    recovered_step = step.model_copy(
        update={
            "status": StepStatus.FAILED,
            "completed_at": now,
            "error": interrupted,
        }
    )
    recovered_run = detail.run.model_copy(
        update={"version": detail.run.version + 1, "updated_at": now}
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
        call = ToolCall.model_validate(step.input.get("tool_call"))
    except ValueError as exc:
        raise AgentCoreError("interrupted action has no valid persisted tool call") from exc

    try:
        definition = tools.resolve(call.tool_name)
        replay_is_safe = (
            definition.version == call.tool_version
            and definition.side_effect is SideEffectClass.READ_ONLY
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
        pending_step = step.model_copy(
            update={
                "status": StepStatus.PENDING,
                "completed_at": None,
                "output": recovery_evidence,
                "error": None,
            }
        )
        ready = transition_run(detail.run, RunStatus.READY, now=now)
        return RecoveryDecision(
            run=ready,
            step=pending_step,
            disposition=RecoveryDisposition.REENQUEUE,
            changed=True,
        )

    if call.idempotency_key is None:
        raise AgentCoreError("interrupted effectful action has no idempotency key")
    review_call = call.model_copy(update={"approval_status": ApprovalStatus.PENDING})
    pending_step = step.model_copy(
        update={
            "status": StepStatus.PENDING,
            "completed_at": None,
            "input": {**step.input, "tool_call": review_call.model_dump(mode="json")},
            "output": recovery_evidence,
            "error": None,
        }
    )
    review = transition_run(detail.run, RunStatus.REVIEW_REQUIRED, now=now)
    return RecoveryDecision(
        run=review,
        step=pending_step,
        disposition=RecoveryDisposition.AWAIT_REVIEW,
        changed=True,
    )


def _single_running_step(detail: AgentRunDetail, phase: StepPhase) -> AgentStep:
    candidates = [
        step for step in detail.steps if step.phase is phase and step.status is StepStatus.RUNNING
    ]
    if len(candidates) != 1:
        raise AgentCoreError(
            f"{detail.run.status.value} run must have exactly one running {phase.value} step"
        )
    return candidates[0]
