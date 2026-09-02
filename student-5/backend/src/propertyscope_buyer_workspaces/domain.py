"""Public Buyer Case command validation independent of database implementation."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

CASE_STATUSES = ("active", "paused", "closed")
PREFERENCE_ARRAY_FIELDS = ("dwelling_types", "priorities")
MAX_PREFERENCE_ITEMS = 20
MAX_PREFERENCE_TEXT_LENGTH = 100
JOURNEY_STAGES = ("Shortlisted", "Inspecting", "Reviewing", "Offer Considered", "Closed")
PRIORITIES = ("low", "medium", "high")


class PublicInputError(ValueError):
    """A browser command does not satisfy the public Buyer Case contract."""


def _object(body: object) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise PublicInputError("request body must be a JSON object")
    if "owner_ref" in body:
        raise PublicInputError("Owner selection is server controlled and cannot be submitted")
    return dict(body)


def _reject_unexpected(value: dict[str, Any], allowed: set[str]) -> None:
    if unexpected := set(value) - allowed:
        raise PublicInputError(f"unsupported fields: {', '.join(sorted(unexpected))}")


def _text(value: object, field: str, *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PublicInputError(f"{field} must be a non-empty string")
    result = value.strip()
    if len(result) > maximum:
        raise PublicInputError(f"{field} must contain at most {maximum} characters")
    return result


def _optional_budget(value: object, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PublicInputError(f"{field} must be a non-negative integer or null")
    return value


def _status(value: object) -> str:
    if not isinstance(value, str) or value not in CASE_STATUSES:
        raise PublicInputError(f"status must be one of: {', '.join(CASE_STATUSES)}")
    return value


def _choice(value: object, field: str, choices: tuple[str, ...]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise PublicInputError(f"{field} must be one of: {', '.join(choices)}")
    return value


def _uuid_text(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise PublicInputError(f"{field} must be a UUID string")
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise PublicInputError(f"{field} must be a UUID string") from exc


def _optional_property_id(value: object) -> str | None:
    return None if value is None else _uuid_text(value, "case_property_id")


def _versioned(body: object, allowed: set[str]) -> tuple[int, dict[str, Any]]:
    value = _object(body)
    version = value.pop("version", None)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise PublicInputError("version must be a positive integer")
    _reject_unexpected(value, allowed)
    if not value:
        raise PublicInputError("at least one field must be updated")
    return version, value


def _preference_array(value: object, field: str) -> list[str]:
    if not isinstance(value, list):
        raise PublicInputError(f"preferences.{field} must be a string array")
    if len(value) > MAX_PREFERENCE_ITEMS:
        raise PublicInputError(
            f"preferences.{field} must contain at most {MAX_PREFERENCE_ITEMS} items"
        )
    result: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise PublicInputError(f"preferences.{field}[{index}] must be non-empty text")
        trimmed = item.strip()
        if len(trimmed) > MAX_PREFERENCE_TEXT_LENGTH:
            raise PublicInputError(
                f"preferences.{field}[{index}] must contain at most "
                f"{MAX_PREFERENCE_TEXT_LENGTH} characters"
            )
        deduplication_key = trimmed.casefold()
        if deduplication_key not in seen:
            seen.add(deduplication_key)
            result.append(trimmed)
    return result


def normalize_preferences(value: object) -> dict[str, Any]:
    """Normalise known preference arrays while retaining unknown structured keys."""

    if value is None:
        return {}
    if not isinstance(value, dict):
        raise PublicInputError("preferences must be a JSON object")
    result = dict(value)
    for field in PREFERENCE_ARRAY_FIELDS:
        if field in result:
            result[field] = _preference_array(result[field], field)
    return result


def _target_suburbs(value: object) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise PublicInputError("target_suburbs must be a JSON array")
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict) or set(item) != {"state", "locality"}:
            raise PublicInputError(f"target_suburbs[{index}] must contain only state and locality")
        state = item.get("state")
        locality = item.get("locality")
        if state != "NSW":
            raise PublicInputError(f"target_suburbs[{index}].state must be NSW")
        if not isinstance(locality, str) or not locality.strip() or len(locality.strip()) > 100:
            raise PublicInputError(f"target_suburbs[{index}].locality must be 1 to 100 characters")
        key = (state, locality.strip().upper())
        if key not in seen:
            seen.add(key)
            result.append({"state": key[0], "locality": key[1]})
    return result


def _validate_budget_range(minimum: int | None, maximum: int | None) -> None:
    if minimum is not None and maximum is not None and maximum < minimum:
        raise PublicInputError("budget_max_aud cannot be less than budget_min_aud")


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
    minimum = _optional_budget(value.get("budget_min_aud"), "budget_min_aud")
    maximum = _optional_budget(value.get("budget_max_aud"), "budget_max_aud")
    _validate_budget_range(minimum, maximum)
    return {
        "name": _text(value.get("name"), "name", maximum=120),
        "preferences": normalize_preferences(value.get("preferences")),
        "budget_min_aud": minimum,
        "budget_max_aud": maximum,
        "target_suburbs": _target_suburbs(value.get("target_suburbs")),
        "status": _status(value.get("status", "active")),
    }


def validate_case_update(body: object) -> dict[str, Any]:
    value = _object(body)
    _reject_unexpected(
        value,
        {
            "version",
            "name",
            "preferences",
            "budget_min_aud",
            "budget_max_aud",
            "target_suburbs",
            "status",
        },
    )
    version = value.pop("version", None)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise PublicInputError("version must be a positive integer")
    changes: dict[str, Any] = {"version": version}
    if "name" in value:
        changes["name"] = _text(value["name"], "name", maximum=120)
    if "preferences" in value:
        changes["preferences"] = normalize_preferences(value["preferences"])
    if "budget_min_aud" in value:
        changes["budget_min_aud"] = _optional_budget(value["budget_min_aud"], "budget_min_aud")
    if "budget_max_aud" in value:
        changes["budget_max_aud"] = _optional_budget(value["budget_max_aud"], "budget_max_aud")
    if "target_suburbs" in value:
        changes["target_suburbs"] = _target_suburbs(value["target_suburbs"])
    if "status" in value:
        changes["status"] = _status(value["status"])
    if len(changes) == 1:
        raise PublicInputError("at least one buyer case field must be updated")
    _validate_budget_range(changes.get("budget_min_aud"), changes.get("budget_max_aud"))
    return changes


def validate_property_create(body: object) -> dict[str, Any]:
    value = _object(body)
    _reject_unexpected(
        value, {"property_ref", "property_label", "journey_stage", "rating", "priority"}
    )
    rating = value.get("rating")
    if rating is not None and (
        isinstance(rating, bool) or not isinstance(rating, int) or not 1 <= rating <= 5
    ):
        raise PublicInputError("rating must be null or an integer from 1 to 5")
    label = value.get("property_label")
    return {
        "property_ref": _uuid_text(value.get("property_ref"), "property_ref"),
        "property_label": (
            None if label is None else _text(label, "property_label", maximum=500)
        ),
        "property_validation_state": "pending",
        "journey_stage": _choice(
            value.get("journey_stage", "Shortlisted"), "journey_stage", JOURNEY_STAGES
        ),
        "rating": rating,
        "priority": _choice(value.get("priority", "medium"), "priority", PRIORITIES),
    }


def validate_property_update(body: object) -> dict[str, Any]:
    version, value = _versioned(
        body, {"property_label", "journey_stage", "rating", "priority"}
    )
    changes: dict[str, Any] = {"version": version}
    if "property_label" in value:
        label = value["property_label"]
        changes["property_label"] = (
            None if label is None else _text(label, "property_label", maximum=500)
        )
    if "journey_stage" in value:
        changes["journey_stage"] = _choice(
            value["journey_stage"], "journey_stage", JOURNEY_STAGES
        )
    if "rating" in value:
        rating = value["rating"]
        if rating is not None and (
            isinstance(rating, bool) or not isinstance(rating, int) or not 1 <= rating <= 5
        ):
            raise PublicInputError("rating must be null or an integer from 1 to 5")
        changes["rating"] = rating
    if "priority" in value:
        changes["priority"] = _choice(value["priority"], "priority", PRIORITIES)
    return changes


def validate_note_create(body: object) -> dict[str, Any]:
    value = _object(body)
    _reject_unexpected(value, {"case_property_id", "content"})
    return {
        "case_property_id": _optional_property_id(value.get("case_property_id")),
        "content": _text(value.get("content"), "content", maximum=4000),
    }


def validate_note_update(body: object) -> dict[str, Any]:
    version, value = _versioned(body, {"case_property_id", "content"})
    changes: dict[str, Any] = {"version": version}
    if "case_property_id" in value:
        changes["case_property_id"] = _optional_property_id(value["case_property_id"])
    if "content" in value:
        changes["content"] = _text(value["content"], "content", maximum=4000)
    return changes


def _due_date(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise PublicInputError("due_date must be an ISO date or null")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise PublicInputError("due_date must be an ISO date or null") from exc
    return value


def validate_task_create(body: object) -> dict[str, Any]:
    value = _object(body)
    _reject_unexpected(value, {"case_property_id", "title", "due_date", "completed"})
    completed = value.get("completed", False)
    if not isinstance(completed, bool):
        raise PublicInputError("completed must be a boolean")
    return {
        "case_property_id": _optional_property_id(value.get("case_property_id")),
        "title": _text(value.get("title"), "title", maximum=300),
        "due_date": _due_date(value.get("due_date")),
        "completed": completed,
    }


def validate_task_update(body: object) -> dict[str, Any]:
    version, value = _versioned(body, {"case_property_id", "title", "due_date", "completed"})
    changes: dict[str, Any] = {"version": version}
    if "case_property_id" in value:
        changes["case_property_id"] = _optional_property_id(value["case_property_id"])
    if "title" in value:
        changes["title"] = _text(value["title"], "title", maximum=300)
    if "due_date" in value:
        changes["due_date"] = _due_date(value["due_date"])
    if "completed" in value:
        if not isinstance(value["completed"], bool):
            raise PublicInputError("completed must be a boolean")
        changes["completed"] = value["completed"]
    return changes


def validate_pagination(page: object, page_size: object) -> dict[str, int]:
    try:
        page_value = int(str(page if page is not None else 1))
        size_value = int(str(page_size if page_size is not None else 50))
    except ValueError as exc:
        raise PublicInputError("page and page_size must be integers") from exc
    if page_value < 1 or not 1 <= size_value <= 100:
        raise PublicInputError("page must be positive and page_size must be between 1 and 100")
    return {"page": page_value, "page_size": size_value}
