from __future__ import annotations

import pytest
from pydantic import ValidationError

from propertyscope_data_platform.assistant import (
    AssistantTurnRequest,
    build_assistant_objective,
    capability_guide,
)


def test_capability_guide_is_bounded_and_honest_about_availability() -> None:
    guide = capability_guide()

    assert guide["revision"] == "2026-08-26.v1"
    features = guide["features"]
    assert isinstance(features, list)
    assert len(features) == 5
    assert [item["status"] for item in features].count("available") == 1
    assistant = guide["assistant"]
    assert isinstance(assistant, dict)
    limitations = assistant["limitations"]
    assert isinstance(limitations, list)
    assert all(isinstance(item, str) for item in limitations)
    assert "repository" in " ".join(limitations).lower()


def test_assistant_objective_preserves_exact_validated_context() -> None:
    command = AssistantTurnRequest.model_validate(
        {
            "message": "Why did this update stop?",
            "scope": "feature",
            "context": {
                "route": "runs/detail",
                "ingestion_run_id": "10000000-0000-0000-0000-000000000004",
            },
        }
    )

    objective = build_assistant_objective(command)

    assert "Why did this update stop?" in objective
    assert "10000000-0000-0000-0000-000000000004" in objective
    assert "fixed-objective Data review" in objective
    assert "Do not propose or call a write tool" in objective
    assert "data.releases.v1" in objective
    assert "active source" in objective


@pytest.mark.parametrize(
    "payload",
    [
        {"message": "x"},
        {"message": "   "},
        {"message": "What can it do?", "scope": "everything"},
        {"message": "What can it do?", "context": {"unknown_id": "value"}},
        {"message": "What can it do?", "context": {"release_id": "not-a-uuid"}},
    ],
)
def test_assistant_turn_rejects_ambiguous_or_unbounded_input(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        AssistantTurnRequest.model_validate(payload)
