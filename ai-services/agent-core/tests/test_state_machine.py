"""State-model tests for legal and illegal run transitions."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from agent_core import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATUSES,
    InvalidStateTransitionError,
    can_transition,
    create_run,
    transition_run,
)
from shared_contracts import AgentRun, AgentRunRequest, RunStatus, ToolError

NOW = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)


def _run() -> AgentRun:
    return create_run(
        AgentRunRequest(feature_key="student-1-feature", objective="Find verified records"),
        run_id=uuid4(),
        request_id="request-1",
        now=NOW,
    )


@given(st.sampled_from(list(RunStatus)), st.sampled_from(list(RunStatus)))
def test_transition_decision_exactly_matches_explicit_graph(
    current: RunStatus, target: RunStatus
) -> None:
    assert can_transition(current, target) is (target in ALLOWED_TRANSITIONS[current])


def test_terminal_states_have_no_outgoing_transitions() -> None:
    assert all(not ALLOWED_TRANSITIONS[status] for status in TERMINAL_STATUSES)


def test_valid_transition_advances_version_and_timestamp() -> None:
    run = _run()
    planning = transition_run(run, RunStatus.PLANNING, now=NOW + timedelta(seconds=1))

    assert planning.status is RunStatus.PLANNING
    assert planning.version == 1
    assert planning.updated_at == NOW + timedelta(seconds=1)


def test_invalid_transition_is_rejected() -> None:
    run = _run()

    with pytest.raises(InvalidStateTransitionError, match="queued to succeeded"):
        transition_run(run, RunStatus.SUCCEEDED, now=NOW, final_result={"ok": True})


def test_terminal_payload_invariants_are_enforced() -> None:
    planning = transition_run(_run(), RunStatus.PLANNING, now=NOW)
    ready = transition_run(planning, RunStatus.READY, now=NOW)
    acting = transition_run(ready, RunStatus.ACTING, now=NOW)
    observing = transition_run(acting, RunStatus.OBSERVING, now=NOW)
    adapting = transition_run(observing, RunStatus.ADAPTING, now=NOW)

    with pytest.raises(InvalidStateTransitionError, match="require a final result"):
        transition_run(adapting, RunStatus.SUCCEEDED, now=NOW)

    with pytest.raises(InvalidStateTransitionError, match="require a structured error"):
        transition_run(planning, RunStatus.FAILED, now=NOW)

    failed = transition_run(
        planning,
        RunStatus.FAILED,
        now=NOW,
        error=ToolError(code="invalid_plan", message="Planner output was invalid"),
    )
    assert failed.error is not None
