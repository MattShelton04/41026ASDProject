"""Boundary validation and canonical JSON projections for buyer-workspace persistence."""

from __future__ import annotations

import json
import uuid
from datetime import date
from typing import Any

CASE_STATUSES = ("active", "paused", "closed")
JOURNEY_STAGES = ("Shortlisted", "Inspecting", "Reviewing", "Offer Considered", "Closed")
PRIORITIES = ("low", "medium", "high")
PROPERTY_VALIDATION_STATES = ("validated", "pending", "unavailable")


class InputValidationError(ValueError):
    """A request body does not satisfy the database boundary contract."""


def _object(body: object) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise InputValidationError("request body must be a JSON object")
    if "owner_ref" in body:
        raise InputValidationError("owner_ref is server configured and cannot be submitted")
    return dict(body)


def _reject_unexpected(value: dict[str, Any], allowed: set[str]) -> None:
    if unexpected := set(value) - allowed:
        raise InputValidationError(f"unsupported fields: {', '.join(sorted(unexpected))}")


def _text(value: object, field: str, *, maximum: int, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.strip():
        raise InputValidationError(f"{field} must be a non-empty string")
    result = value.strip()
    if len(result) > maximum:
        raise InputValidationError(f"{field} must contain at most {maximum} characters")
    return result


def _integer(value: object, field: str, *, optional: bool = False) -> int | None:
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise InputValidationError(f"{field} must be an integer")
    return value


def _choice(value: object, field: str, choices: tuple[str, ...]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise InputValidationError(f"{field} must be one of: {', '.join(choices)}")
    return value


def _uuid_text(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise InputValidationError(f"{field} must be a UUID string")
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise InputValidationError(f"{field} must be a UUID string") from exc


def _preferences(value: object) -> str:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise InputValidationError("preferences must be a JSON object")
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _target_suburbs(value: object) -> str:
    if value is None:
        value = []
    if not isinstance(value, list):
        raise InputValidationError("target_suburbs must be a JSON array")
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict) or set(item) != {"state", "locality"}:
            raise InputValidationError(
                f"target_suburbs[{index}] must contain only state and locality"
            )
        state = item.get("state")
        locality = item.get("locality")
        if state != "NSW":
            raise InputValidationError(f"target_suburbs[{index}].state must be NSW")
        if not isinstance(locality, str) or not locality.strip() or len(locality.strip()) > 100:
            raise InputValidationError(
                f"target_suburbs[{index}].locality must be 1 to 100 characters"
            )
        canonical = (state, locality.strip().upper())
        if canonical not in seen:
            seen.add(canonical)
            result.append({"state": canonical[0], "locality": canonical[1]})
    return json.dumps(result, sort_keys=True, separators=(",", ":"))


def validate_case_create(body: object) -> dict[str, Any]:
    value = _object(body)
    _reject_unexpected(
        value,
        {
            "name",
            "preferences",
            "budget_min_aud",
            "budget_max_aud",
            "target_suburbs",
            "status",
        },
    )
    budget_min = _integer(value.get("budget_min_aud"), "budget_min_aud", optional=True)
    budget_max = _integer(value.get("budget_max_aud"), "budget_max_aud", optional=True)
    if budget_min is not None and budget_min < 0:
        raise InputValidationError("budget_min_aud must be non-negative")
    if budget_max is not None and budget_max < 0:
        raise InputValidationError("budget_max_aud must be non-negative")
    if budget_min is not None and budget_max is not None and budget_max < budget_min:
        raise InputValidationError("budget_max_aud cannot be less than budget_min_aud")
    return {
        "name": _text(value.get("name"), "name", maximum=120),
        "preferences_json": _preferences(value.get("preferences")),
        "budget_min_aud": budget_min,
        "budget_max_aud": budget_max,
        "target_suburbs_json": _target_suburbs(value.get("target_suburbs")),
        "status": _choice(value.get("status", "active"), "status", CASE_STATUSES),
    }


def validate_case_update(body: object) -> tuple[int, dict[str, Any]]:
    value = _object(body)
    version = _integer(value.pop("version", None), "version")
    assert version is not None
    if version < 1:
        raise InputValidationError("version must be at least 1")
    allowed = {
        "name",
        "preferences",
        "budget_min_aud",
        "budget_max_aud",
        "target_suburbs",
        "status",
    }
    if unexpected := set(value) - allowed:
        raise InputValidationError(f"unsupported fields: {', '.join(sorted(unexpected))}")
    changes: dict[str, Any] = {}
    if "name" in value:
        changes["name"] = _text(value["name"], "name", maximum=120)
    if "preferences" in value:
        changes["preferences_json"] = _preferences(value["preferences"])
    if "budget_min_aud" in value:
        changes["budget_min_aud"] = _integer(
            value["budget_min_aud"], "budget_min_aud", optional=True
        )
    if "budget_max_aud" in value:
        changes["budget_max_aud"] = _integer(
            value["budget_max_aud"], "budget_max_aud", optional=True
        )
    if "target_suburbs" in value:
        changes["target_suburbs_json"] = _target_suburbs(value["target_suburbs"])
    if "status" in value:
        changes["status"] = _choice(value["status"], "status", CASE_STATUSES)
    if not changes:
        raise InputValidationError("at least one case field must be updated")
    for field in ("budget_min_aud", "budget_max_aud"):
        if changes.get(field) is not None and changes[field] < 0:
            raise InputValidationError(f"{field} must be non-negative")
    return version, changes


def validate_property_create(body: object) -> dict[str, Any]:
    value = _object(body)
    _reject_unexpected(
        value,
        {
            "property_ref",
            "property_label",
            "property_validation_state",
            "journey_stage",
            "rating",
            "priority",
        },
    )
    rating = _integer(value.get("rating"), "rating", optional=True)
    if rating is not None and not 1 <= rating <= 5:
        raise InputValidationError("rating must be null or between 1 and 5")
    return {
        "property_ref": _uuid_text(value.get("property_ref"), "property_ref"),
        "property_label": _text(
            value.get("property_label"), "property_label", maximum=500, optional=True
        ),
        "property_validation_state": _choice(
            value.get("property_validation_state", "pending"),
            "property_validation_state",
            PROPERTY_VALIDATION_STATES,
        ),
        "journey_stage": _choice(
            value.get("journey_stage", "Shortlisted"), "journey_stage", JOURNEY_STAGES
        ),
        "rating": rating,
        "priority": _choice(value.get("priority", "medium"), "priority", PRIORITIES),
    }


def validate_property_update(body: object) -> tuple[int, dict[str, Any]]:
    value = _object(body)
    version = _integer(value.pop("version", None), "version")
    assert version is not None
    if version < 1:
        raise InputValidationError("version must be at least 1")
    allowed = {
        "property_label",
        "property_validation_state",
        "journey_stage",
        "rating",
        "priority",
    }
    if unexpected := set(value) - allowed:
        raise InputValidationError(f"unsupported fields: {', '.join(sorted(unexpected))}")
    changes: dict[str, Any] = {}
    if "property_label" in value:
        changes["property_label"] = _text(
            value["property_label"], "property_label", maximum=500, optional=True
        )
    if "property_validation_state" in value:
        changes["property_validation_state"] = _choice(
            value["property_validation_state"],
            "property_validation_state",
            PROPERTY_VALIDATION_STATES,
        )
    if "journey_stage" in value:
        changes["journey_stage"] = _choice(value["journey_stage"], "journey_stage", JOURNEY_STAGES)
    if "rating" in value:
        changes["rating"] = _integer(value["rating"], "rating", optional=True)
        if changes["rating"] is not None and not 1 <= changes["rating"] <= 5:
            raise InputValidationError("rating must be null or between 1 and 5")
    if "priority" in value:
        changes["priority"] = _choice(value["priority"], "priority", PRIORITIES)
    if not changes:
        raise InputValidationError("at least one property field must be updated")
    return version, changes


def validate_note_create(body: object) -> dict[str, Any]:
    value = _object(body)
    _reject_unexpected(value, {"case_property_id", "content"})
    property_id = value.get("case_property_id")
    return {
        "case_property_id": None
        if property_id is None
        else _uuid_text(property_id, "case_property_id"),
        "content": _text(value.get("content"), "content", maximum=4000),
    }


def validate_note_update(body: object) -> tuple[int, dict[str, Any]]:
    value = _object(body)
    version = _integer(value.pop("version", None), "version")
    assert version is not None
    if version < 1:
        raise InputValidationError("version must be at least 1")
    if unexpected := set(value) - {"case_property_id", "content"}:
        raise InputValidationError(f"unsupported fields: {', '.join(sorted(unexpected))}")
    changes: dict[str, Any] = {}
    if "case_property_id" in value:
        changes["case_property_id"] = (
            None
            if value["case_property_id"] is None
            else _uuid_text(value["case_property_id"], "case_property_id")
        )
    if "content" in value:
        changes["content"] = _text(value["content"], "content", maximum=4000)
    if not changes:
        raise InputValidationError("at least one note field must be updated")
    return version, changes


def validate_task_create(body: object) -> dict[str, Any]:
    value = _object(body)
    _reject_unexpected(value, {"case_property_id", "title", "due_date", "completed"})
    property_id = value.get("case_property_id")
    due_date = value.get("due_date")
    if due_date is not None:
        if not isinstance(due_date, str):
            raise InputValidationError("due_date must be an ISO date or null")
        try:
            date.fromisoformat(due_date)
        except ValueError as exc:
            raise InputValidationError("due_date must be an ISO date or null") from exc
    completed = value.get("completed", False)
    if not isinstance(completed, bool):
        raise InputValidationError("completed must be a boolean")
    return {
        "case_property_id": None
        if property_id is None
        else _uuid_text(property_id, "case_property_id"),
        "title": _text(value.get("title"), "title", maximum=300),
        "due_date": due_date,
        "completed": completed,
    }


def validate_task_update(body: object) -> tuple[int, dict[str, Any]]:
    value = _object(body)
    version = _integer(value.pop("version", None), "version")
    assert version is not None
    if version < 1:
        raise InputValidationError("version must be at least 1")
    if unexpected := set(value) - {"case_property_id", "title", "due_date", "completed"}:
        raise InputValidationError(f"unsupported fields: {', '.join(sorted(unexpected))}")
    changes: dict[str, Any] = {}
    if "case_property_id" in value:
        changes["case_property_id"] = (
            None
            if value["case_property_id"] is None
            else _uuid_text(value["case_property_id"], "case_property_id")
        )
    if "title" in value:
        changes["title"] = _text(value["title"], "title", maximum=300)
    if "due_date" in value:
        due_date = value["due_date"]
        if due_date is not None:
            if not isinstance(due_date, str):
                raise InputValidationError("due_date must be an ISO date or null")
            try:
                date.fromisoformat(due_date)
            except ValueError as exc:
                raise InputValidationError("due_date must be an ISO date or null") from exc
        changes["due_date"] = due_date
    if "completed" in value:
        if not isinstance(value["completed"], bool):
            raise InputValidationError("completed must be a boolean")
        changes["completed"] = value["completed"]
    if not changes:
        raise InputValidationError("at least one task field must be updated")
    return version, changes


def decode_case(row: dict[str, Any]) -> dict[str, Any]:
    """Project stored canonical JSON into the internal API representation."""

    value = dict(row)
    value["preferences"] = json.loads(value.pop("preferences_json"))
    value["target_suburbs"] = json.loads(value.pop("target_suburbs_json"))
    return value
