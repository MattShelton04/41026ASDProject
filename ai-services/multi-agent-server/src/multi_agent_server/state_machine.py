"""The workflow state machine: the only place that decides which transitions are legal.

```
planning ─▶ working ─▶ reviewing ─▶ awaiting_human ─┬─▶ approved
    │          │  ▲         │             │          ├─▶ partially_accepted
    │          │  └─────────┼─────────────┘ correct  ├─▶ rejected
    │          │            │          (round 1 only)└─▶ corrected (correct in round 2)
    └──────────┴────────────┴──▶ failed | cancelled (from any non-terminal state)
```

Correction rule: the first ``correct`` decision (round 1) sends the run back to ``working``; the
Worker and the Reviewer run once more with the human's note, then the run returns to
``awaiting_human`` in round 2. A ``correct`` decision in round 2 ends the run as ``corrected``,
recording the note as the human's final correction. ``failed`` is never reachable from
``awaiting_human`` because no agent is running there; ``cancelled`` is.
"""

from __future__ import annotations

from collections.abc import Mapping

from multi_agent_server.errors import InvalidTransitionError
from shared_contracts.multi_agent import (
    MAX_WORKFLOW_ROUNDS,
    TERMINAL_WORKFLOW_STATES,
    HumanDecisionKind,
    WorkflowAction,
    WorkflowState,
)

S = WorkflowState
TRANSITIONS: Mapping[WorkflowState, frozenset[WorkflowState]] = {
    S.PLANNING: frozenset({S.WORKING, S.FAILED, S.CANCELLED}),
    S.WORKING: frozenset({S.REVIEWING, S.FAILED, S.CANCELLED}),
    S.REVIEWING: frozenset({S.AWAITING_HUMAN, S.FAILED, S.CANCELLED}),
    S.AWAITING_HUMAN: frozenset(
        {
            S.APPROVED,
            S.CORRECTED,
            S.PARTIALLY_ACCEPTED,
            S.REJECTED,
            S.WORKING,
            S.CANCELLED,
        }
    ),
    **{state: frozenset() for state in TERMINAL_WORKFLOW_STATES},
}
DECISION_ACTIONS: tuple[WorkflowAction, ...] = ("approve", "correct", "partial", "reject")


def can_transition(current: WorkflowState, target: WorkflowState) -> bool:
    """Whether the state machine allows ``current → target``."""
    return target in TRANSITIONS[current]


def require_transition(current: WorkflowState, target: WorkflowState) -> None:
    """Raise a structured 409 error for any transition the machine does not allow."""
    if not can_transition(current, target):
        raise InvalidTransitionError(current.value, target.value)


def decision_target(decision: HumanDecisionKind, round_number: int) -> WorkflowState:
    """Map a human decision in a given round onto the state it produces."""
    if not 1 <= round_number <= MAX_WORKFLOW_ROUNDS:
        raise ValueError("round is outside the supported correction budget")
    if decision is HumanDecisionKind.APPROVE:
        return S.APPROVED
    if decision is HumanDecisionKind.REJECT:
        return S.REJECTED
    if decision is HumanDecisionKind.PARTIAL:
        return S.PARTIALLY_ACCEPTED
    return S.WORKING if round_number < MAX_WORKFLOW_ROUNDS else S.CORRECTED


def available_actions(state: WorkflowState) -> tuple[WorkflowAction, ...]:
    """Actions a client may offer for a run in ``state``."""
    if state is S.AWAITING_HUMAN:
        return (*DECISION_ACTIONS, "cancel")
    if state in TERMINAL_WORKFLOW_STATES:
        return ()
    return ("cancel",)
