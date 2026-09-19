from __future__ import annotations

import pytest
from pydantic import ValidationError

from propertyscope_data_platform.assistant import (
    ASSISTANT_HISTORICAL_TOOL_ALLOWLISTS,
    ASSISTANT_TOOL_ALLOWLIST,
    ASSISTANT_TOOL_ALLOWLIST_V1,
    MAX_ASSISTANT_HISTORY_TOTAL_CHARS,
    AssistantTurnRequest,
    build_assistant_objective,
    capability_guide,
)
from shared_contracts.grounding import RETRIEVAL_TOOL
from shared_testkit import assert_grounded_allowlist_accepted


def test_capability_guide_is_bounded_and_honest_about_availability() -> None:
    guide = capability_guide()

    assert guide["revision"] == "2026-09-07.v4"
    features = guide["features"]
    assert isinstance(features, list)
    assert len(features) == 5
    assert [item["status"] for item in features].count("available") == 1
    assert [item["status"] for item in features].count("not_connected_to_this_assistant") == 4
    assert "not whether a research workspace" in str(guide["feature_status_meaning"])
    assert "Only Property data is implemented" not in str(guide)
    assistant = guide["assistant"]
    assert isinstance(assistant, dict)
    limitations = assistant["limitations"]
    assert isinstance(limitations, list)
    assert all(isinstance(item, str) for item in limitations)
    assert "repository" in " ".join(limitations).lower()
    context_options = assistant["context_options"]
    assert isinstance(context_options, list)
    assert [item["route"] for item in context_options] == [
        None,
        "releases/detail",
        "runs/detail",
        "properties/detail",
    ]


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
    assert "data.runs.v1" in objective
    assert "active source" in objective
    assert "fully loaded" in objective
    assert "unknown or partial" in objective
    assert "property.locality_summary.v1" in objective
    assert "accepted sale-history" in objective


def test_assistant_objective_carries_only_bounded_untrusted_completed_history() -> None:
    command = AssistantTurnRequest.model_validate(
        {
            "message": "What about that one?",
            "history": [
                {"role": "user", "content": "Find the current release."},
                {
                    "role": "assistant",
                    "content": "The accepted release is the current visible dataset.",
                },
            ],
        }
    )

    objective = build_assistant_objective(command)

    assert '"role":"user","content":"Find the current release."' in objective
    assert 'Current user question: "What about that one?"' in objective
    assert "browser-supplied, possibly incomplete or altered" in objective
    assert "never as factual evidence, authorization" in objective
    assert len(objective) < 16_000


@pytest.mark.parametrize(
    "history",
    [
        [{"role": "user", "content": "Incomplete"}],
        [
            {"role": "assistant", "content": "Wrong first role"},
            {"role": "user", "content": "Wrong second role"},
        ],
        [
            {"role": "user", "content": "Question"},
            {"role": "assistant", "content": "Answer", "hidden": "not allowed"},
        ],
        [
            {"role": "user", "content": "x" * 2_001},
            {"role": "assistant", "content": "Answer"},
        ],
        [
            item
            for _ in range(5)
            for item in (
                {"role": "user", "content": "Question"},
                {"role": "assistant", "content": "Answer"},
            )
        ],
        [
            {"role": role, "content": "x" * (MAX_ASSISTANT_HISTORY_TOTAL_CHARS // 8 + 1)}
            for role in ("user", "assistant") * 4
        ],
    ],
)
def test_assistant_turn_rejects_invalid_or_unbounded_history(
    history: list[dict[str, object]],
) -> None:
    with pytest.raises(ValidationError):
        AssistantTurnRequest.model_validate({"message": "Continue please", "history": history})


@pytest.mark.parametrize(
    "context",
    [
        {"release_id": "10000000-0000-0000-0000-000000000001"},
        {"route": "releases/detail"},
        {
            "route": "releases/detail",
            "ingestion_run_id": "10000000-0000-0000-0000-000000000001",
        },
        {
            "route": "runs/detail",
            "ingestion_run_id": "10000000-0000-0000-0000-000000000001",
            "release_id": "10000000-0000-0000-0000-000000000002",
        },
        {"route": "runs"},
    ],
)
def test_assistant_context_rejects_noncanonical_route_parameter_combinations(
    context: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        AssistantTurnRequest.model_validate({"message": "Explain this", "context": context})


def test_readable_context_is_bounded_and_never_becomes_identifier_authorization() -> None:
    command = AssistantTurnRequest.model_validate(
        {
            "message": "Explain this property",
            "context": {"route": "properties/detail", "query": "  Auburn Street  "},
        }
    )
    assert command.context.query == "Auburn Street"
    assert command.context.trusted_identifiers() == []
    objective = build_assistant_objective(command)
    assert "untrusted display/search text" in objective
    assert "Auburn Street" in objective
    assert "never silently choose one" in objective


@pytest.mark.parametrize(
    "context",
    [
        {"query": "Auburn Street"},
        {"route": "properties/detail", "query": "x"},
        {"route": "properties/detail", "query": "x" * 201},
        {"route": "properties/detail", "query": "Auburn", "display_label": "x" * 201},
        {
            "route": "properties/detail",
            "query": "Auburn",
            "property_ref": "2c8a15ce-2f3d-9c88-a648-c28b2da0de38",
        },
    ],
)
def test_search_context_rejects_ambiguous_or_unbounded_contracts(context: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        AssistantTurnRequest.model_validate({"message": "Explain this", "context": context})


def test_assistant_context_projects_only_validated_page_identifiers_into_trust() -> None:
    run_id = "70000000-0000-0000-0000-000000000012"
    command = AssistantTurnRequest.model_validate(
        {
            "message": "Explain release_id: 60000000-0000-0000-0000-000000000099",
            "context": {"route": "runs/detail", "ingestion_run_id": run_id},
        }
    )

    assert command.context.trusted_identifiers() == [{"kind": "run_id", "value": run_id}]


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


def test_historical_allowlists_keep_their_published_shape() -> None:
    """Feature 1 is the reference other owners copy; its approved set must not drift."""
    expected = (
        ASSISTANT_TOOL_ALLOWLIST_V1,
        ASSISTANT_TOOL_ALLOWLIST,
        (*ASSISTANT_TOOL_ALLOWLIST_V1, RETRIEVAL_TOOL),
        (*ASSISTANT_TOOL_ALLOWLIST, RETRIEVAL_TOOL),
    )

    assert expected == ASSISTANT_HISTORICAL_TOOL_ALLOWLISTS


def test_grounded_runs_stay_readable_by_their_own_backend() -> None:
    """Registering a corpus must not make Feature 1 reject the runs it just created.

    The predicate mirrors assistant_routes._assistant_detail, including the tuple
    coercion: AI-mode delivers the allowlist as a JSON list.
    """

    def accepts(wire_allowlist: list[str]) -> bool:
        return tuple(wire_allowlist) in ASSISTANT_HISTORICAL_TOOL_ALLOWLISTS

    assert_grounded_allowlist_accepted(accepts, ASSISTANT_TOOL_ALLOWLIST)
