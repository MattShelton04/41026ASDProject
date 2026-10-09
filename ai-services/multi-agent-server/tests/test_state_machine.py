"""Every state pair is either an allowed transition or a structured 409 error."""

from __future__ import annotations

import itertools

import pytest

from multi_agent_server.errors import InvalidTransitionError
from multi_agent_server.state_machine import (
    TRANSITIONS,
    available_actions,
    can_transition,
    decision_target,
    require_transition,
)
from shared_contracts.multi_agent import (
    TERMINAL_WORKFLOW_STATES,
    HumanDecisionKind,
    WorkflowState,
)

S = WorkflowState
ALLOWED = {
    (S.PLANNING, S.WORKING),
    (S.PLANNING, S.FAILED),
    (S.PLANNING, S.CANCELLED),
    (S.WORKING, S.REVIEWING),
    (S.WORKING, S.FAILED),
    (S.WORKING, S.CANCELLED),
    (S.REVIEWING, S.AWAITING_HUMAN),
    (S.REVIEWING, S.FAILED),
    (S.REVIEWING, S.CANCELLED),
    (S.AWAITING_HUMAN, S.APPROVED),
    (S.AWAITING_HUMAN, S.CORRECTED),
    (S.AWAITING_HUMAN, S.PARTIALLY_ACCEPTED),
    (S.AWAITING_HUMAN, S.REJECTED),
    (S.AWAITING_HUMAN, S.WORKING),
    (S.AWAITING_HUMAN, S.CANCELLED),
}


def test_every_state_has_a_transition_entry() -> None:
    assert set(TRANSITIONS) == set(WorkflowState)


@pytest.mark.parametrize(("current", "target"), list(itertools.product(S, S)))
def test_transition_table_is_exactly_the_documented_machine(
    current: WorkflowState, target: WorkflowState
) -> None:
    allowed = (current, target) in ALLOWED
    assert can_transition(current, target) is allowed
    if allowed:
        require_transition(current, target)
    else:
        with pytest.raises(InvalidTransitionError) as error:
            require_transition(current, target)
        assert error.value.status == 409
        assert error.value.code == "invalid_state_transition"
        assert (error.value.current, error.value.target) == (current.value, target.value)


@pytest.mark.parametrize("state", sorted(TERMINAL_WORKFLOW_STATES))
def test_terminal_states_are_final(state: WorkflowState) -> None:
    assert TRANSITIONS[state] == frozenset()
    assert available_actions(state) == ()


@pytest.mark.parametrize(
    ("decision", "round_number", "expected"),
    [
        (HumanDecisionKind.APPROVE, 1, S.APPROVED),
        (HumanDecisionKind.APPROVE, 2, S.APPROVED),
        (HumanDecisionKind.REJECT, 1, S.REJECTED),
        (HumanDecisionKind.REJECT, 2, S.REJECTED),
        (HumanDecisionKind.PARTIAL, 1, S.PARTIALLY_ACCEPTED),
        (HumanDecisionKind.PARTIAL, 2, S.PARTIALLY_ACCEPTED),
        (HumanDecisionKind.CORRECT, 1, S.WORKING),
        (HumanDecisionKind.CORRECT, 2, S.CORRECTED),
    ],
)
def test_decisions_map_to_states_with_one_correction_round(
    decision: HumanDecisionKind, round_number: int, expected: WorkflowState
) -> None:
    assert decision_target(decision, round_number) is expected
    assert can_transition(S.AWAITING_HUMAN, expected)


@pytest.mark.parametrize("round_number", [0, 3])
def test_decisions_outside_the_correction_budget_are_rejected(round_number: int) -> None:
    with pytest.raises(ValueError, match="correction budget"):
        decision_target(HumanDecisionKind.CORRECT, round_number)


def test_available_actions_follow_the_state() -> None:
    assert available_actions(S.AWAITING_HUMAN) == (
        "approve",
        "correct",
        "partial",
        "reject",
        "cancel",
    )
    for state in (S.PLANNING, S.WORKING, S.REVIEWING):
        assert available_actions(state) == ("cancel",)
