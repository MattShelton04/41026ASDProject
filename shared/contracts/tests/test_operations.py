"""Contract tests for the domain-neutral operations read model."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from shared_contracts import AgentRunPage, AgentRunSummary, RunStatus


def _summary() -> AgentRunSummary:
    now = datetime(2026, 8, 2, tzinfo=UTC)
    return AgentRunSummary(
        id=uuid4(),
        feature_key="student-1-feature",
        objective_preview="Inspect a safe run",
        status=RunStatus.QUEUED,
        model_profile="remote-standard.v1",
        prompt_set="default.v3",
        iteration_count=0,
        tool_call_count=0,
        version=0,
        review_required=False,
        created_at=now,
        updated_at=now,
        duration_ms=0,
    )


def test_operations_contracts_are_frozen_strict_and_bounded() -> None:
    summary = _summary()

    with pytest.raises(ValidationError, match="Instance is frozen"):
        summary.status = RunStatus.FAILED  # type: ignore[misc]
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AgentRunSummary(**summary.model_dump(), private_prompt="never")
    with pytest.raises(ValidationError, match="at most 160 characters"):
        AgentRunSummary(**{**summary.model_dump(), "objective_preview": "x" * 161})
    with pytest.raises(ValidationError, match="at most 100 items"):
        AgentRunPage(
            items=tuple(summary for _ in range(101)),
            as_of=datetime(2026, 8, 2, tzinfo=UTC),
        )
