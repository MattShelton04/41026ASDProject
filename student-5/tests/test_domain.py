"""Boundary validation tests for buyer workspace inputs."""

from __future__ import annotations

from pathlib import Path

import pytest

from propertyscope_buyer_store.configuration import StoreSettings
from propertyscope_buyer_store.domain import (
    InputValidationError,
    validate_case_create,
    validate_case_update,
    validate_note_create,
    validate_property_create,
    validate_property_update,
    validate_task_create,
    validate_task_update,
)


def test_store_settings_fail_closed_for_empty_security_scope() -> None:
    with pytest.raises(ValueError, match="internal_token"):
        StoreSettings(Path("buyer.sqlite3"), " ", "owner")
    with pytest.raises(ValueError, match="demo_owner_ref"):
        StoreSettings(Path("buyer.sqlite3"), "token", " ")


def test_case_defaults_and_canonical_suburbs() -> None:
    value = validate_case_create(
        {
            "name": "  Search  ",
            "target_suburbs": [
                {"state": "NSW", "locality": " Sydney "},
                {"state": "NSW", "locality": "SYDNEY"},
            ],
        }
    )
    assert value["name"] == "Search"
    assert value["status"] == "active"
    assert value["target_suburbs_json"] == '[{"locality":"SYDNEY","state":"NSW"}]'


@pytest.mark.parametrize(
    "body",
    [
        {"name": ""},
        {"name": "x", "owner_ref": "browser-owner"},
        {"name": "x", "budget_min_aud": 10, "budget_max_aud": 9},
        {"name": "x", "status": "draft"},
        {"name": "x", "target_suburbs": [{"state": "VIC", "locality": "Melbourne"}]},
        {"name": "x", "target_suburbs": [{"state": "NSW", "locality": "S", "extra": 1}]},
    ],
)
def test_invalid_cases_are_rejected(body: object) -> None:
    with pytest.raises(InputValidationError):
        validate_case_create(body)


def test_every_create_validator_rejects_unsupported_fields() -> None:
    with pytest.raises(InputValidationError, match="statuz"):
        validate_case_create({"name": "Example", "statuz": "closed"})
    with pytest.raises(InputValidationError, match="unexpected"):
        validate_property_create(
            {
                "property_ref": "a0000000-0000-0000-0000-000000000001",
                "unexpected": True,
            }
        )
    with pytest.raises(InputValidationError, match="unexpected"):
        validate_note_create({"content": "Note", "unexpected": True})
    with pytest.raises(InputValidationError, match="unexpected"):
        validate_task_create({"title": "Task", "unexpected": True})


def test_case_update_requires_version_and_changes() -> None:
    with pytest.raises(InputValidationError):
        validate_case_update({"name": "Changed"})
    with pytest.raises(InputValidationError):
        validate_case_update({"version": 1})
    version, changes = validate_case_update({"version": 2, "status": "closed"})
    assert version == 2
    assert changes == {"status": "closed"}


def test_property_contract_allows_reopening_and_nullable_rating() -> None:
    created = validate_property_create(
        {"property_ref": "a0000000-0000-0000-0000-000000000001", "rating": None}
    )
    assert created["journey_stage"] == "Shortlisted"
    assert created["property_validation_state"] == "pending"
    version, changes = validate_property_update({"version": 1, "journey_stage": "Closed"})
    assert (version, changes) == (1, {"journey_stage": "Closed"})
    _, reopened = validate_property_update({"version": 2, "journey_stage": "Shortlisted"})
    assert reopened == {"journey_stage": "Shortlisted"}


@pytest.mark.parametrize(
    "body",
    [
        {"property_ref": "not-a-uuid"},
        {"property_ref": "a0000000-0000-0000-0000-000000000001", "rating": 6},
        {
            "property_ref": "a0000000-0000-0000-0000-000000000001",
            "property_validation_state": "invalid",
        },
        {"property_ref": "a0000000-0000-0000-0000-000000000001", "priority": "urgent"},
    ],
)
def test_invalid_properties_are_rejected(body: object) -> None:
    with pytest.raises(InputValidationError):
        validate_property_create(body)


def test_note_and_task_values_are_trimmed_and_typed() -> None:
    assert validate_note_create({"content": "  Keep evidence  "})["content"] == "Keep evidence"
    task = validate_task_create({"title": "  Inspect  ", "due_date": "2026-09-10"})
    assert task["title"] == "Inspect"
    assert task["completed"] is False
    version, changes = validate_task_update({"version": 1, "completed": True})
    assert version == 1
    assert changes == {"completed": True}


@pytest.mark.parametrize(
    "body",
    [
        {"title": "Task", "due_date": "10/09/2026"},
        {"title": "Task", "completed": 1},
        {"title": ""},
    ],
)
def test_invalid_tasks_are_rejected(body: object) -> None:
    with pytest.raises(InputValidationError):
        validate_task_create(body)
