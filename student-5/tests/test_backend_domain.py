"""Public Buyer Case validation tests."""

from __future__ import annotations

import pytest

from propertyscope_buyer_workspaces.domain import (
    MAX_PREFERENCE_ITEMS,
    PublicInputError,
    validate_case_create,
    validate_case_update,
    validate_note_create,
    validate_note_update,
    validate_pagination,
    validate_property_create,
    validate_property_update,
    validate_task_create,
    validate_task_update,
)


def test_create_defaults_active_and_canonicalises_nsw_suburbs() -> None:
    value = validate_case_create(
        {
            "name": "  First home  ",
            "target_suburbs": [
                {"state": "NSW", "locality": " Mascot "},
                {"state": "NSW", "locality": "MASCOT"},
            ],
        }
    )
    assert value["name"] == "First home"
    assert value["status"] == "active"
    assert value["target_suburbs"] == [{"state": "NSW", "locality": "MASCOT"}]


@pytest.mark.parametrize(
    "body",
    [
        {"name": ""},
        {"name": "Case", "status": "draft"},
        {"name": "Case", "budget_min_aud": -1},
        {"name": "Case", "budget_min_aud": 900000, "budget_max_aud": 800000},
        {"name": "Case", "target_suburbs": [{"state": "VIC", "locality": "RICHMOND"}]},
        {"name": "Case", "target_suburbs": [{"state": "NSW"}]},
        {"name": "Case", "owner_ref": "browser-selected"},
        {"name": "Case", "statuz": "closed"},
    ],
)
def test_invalid_create_commands_are_rejected(body: object) -> None:
    with pytest.raises(PublicInputError):
        validate_case_create(body)


def test_update_requires_current_version_and_a_change() -> None:
    with pytest.raises(PublicInputError, match="version"):
        validate_case_update({"status": "paused"})
    with pytest.raises(PublicInputError, match="at least one"):
        validate_case_update({"version": 1})
    assert validate_case_update({"version": 3, "status": "closed"}) == {
        "version": 3,
        "status": "closed",
    }


def test_preferences_are_trimmed_deduplicated_bounded_and_preserve_unknown_keys() -> None:
    value = validate_case_create(
        {
            "name": "Preferences",
            "preferences": {
                "dwelling_types": [" apartment ", "Apartment", "terrace"],
                "priorities": ["transport", " planning evidence "],
                "pets": {"required": True},
            },
        }
    )
    assert value["preferences"] == {
        "dwelling_types": ["apartment", "terrace"],
        "priorities": ["transport", "planning evidence"],
        "pets": {"required": True},
    }
    updated = validate_case_update({"version": 1, "preferences": value["preferences"]})
    assert updated["preferences"]["pets"] == {"required": True}


def test_preferences_reject_wrong_types_and_bounds() -> None:
    with pytest.raises(PublicInputError, match="string array"):
        validate_case_create({"name": "Case", "preferences": {"priorities": "transport"}})
    with pytest.raises(PublicInputError, match="at most 20"):
        validate_case_create(
            {
                "name": "Case",
                "preferences": {
                    "dwelling_types": [f"type-{index}" for index in range(MAX_PREFERENCE_ITEMS + 1)]
                },
            }
        )
    with pytest.raises(PublicInputError, match="100 characters"):
        validate_case_create({"name": "Case", "preferences": {"priorities": ["x" * 101]}})


def test_pagination_is_bounded() -> None:
    assert validate_pagination(None, None) == {"page": 1, "page_size": 50}
    assert validate_pagination("2", "25") == {"page": 2, "page_size": 25}
    with pytest.raises(PublicInputError):
        validate_pagination("0", "101")


def test_property_commands_cover_journey_rating_priority_and_reopening() -> None:
    created = validate_property_create(
        {
            "property_ref": "f1000000-0000-4000-8000-000000000001",
            "property_label": "  Personal shortlist label  ",
            "journey_stage": "Closed",
            "rating": 5,
            "priority": "high",
        }
    )
    assert created["property_validation_state"] == "pending"
    assert created["property_label"] == "Personal shortlist label"
    assert validate_property_update(
        {"version": 2, "journey_stage": "Shortlisted", "rating": None, "priority": "low"}
    ) == {"version": 2, "journey_stage": "Shortlisted", "rating": None, "priority": "low"}


@pytest.mark.parametrize(
    "body",
    [
        {"property_ref": "not-a-uuid"},
        {"property_ref": "f1000000-0000-4000-8000-000000000001", "journey_stage": "Offer"},
        {"property_ref": "f1000000-0000-4000-8000-000000000001", "rating": 6},
        {"property_ref": "f1000000-0000-4000-8000-000000000001", "priority": "urgent"},
        {
            "property_ref": "f1000000-0000-4000-8000-000000000001",
            "property_validation_state": "validated",
        },
    ],
)
def test_invalid_property_commands_are_rejected(body: object) -> None:
    with pytest.raises(PublicInputError):
        validate_property_create(body)


def test_note_commands_trim_content_and_support_property_association() -> None:
    property_id = "f5000000-0000-4000-8000-000000000010"
    assert validate_note_create(
        {"case_property_id": property_id, "content": "  Inspect again  "}
    ) == {
        "case_property_id": property_id,
        "content": "Inspect again",
    }
    assert validate_note_update({"version": 2, "case_property_id": None}) == {
        "version": 2,
        "case_property_id": None,
    }
    with pytest.raises(PublicInputError):
        validate_note_create({"content": " "})


def test_task_commands_validate_due_date_completion_and_updates() -> None:
    created = validate_task_create({"title": "  Book inspection  ", "due_date": "2026-09-10"})
    assert created["title"] == "Book inspection"
    assert created["completed"] is False
    assert validate_task_update({"version": 4, "completed": True}) == {
        "version": 4,
        "completed": True,
    }
    with pytest.raises(PublicInputError, match="ISO date"):
        validate_task_create({"title": "Task", "due_date": "10/09/2026"})
    with pytest.raises(PublicInputError, match="boolean"):
        validate_task_update({"version": 1, "completed": "yes"})
