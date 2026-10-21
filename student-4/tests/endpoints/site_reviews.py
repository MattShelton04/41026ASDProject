"""Shared constants and schemas for the Feature 4 endpoint tests."""

from __future__ import annotations

from typing import Any

import jsonschema

SITE_REVIEWS = "/api/due-diligence/v1/site-reviews"
# The first deterministic seed review (002_seed.sql). Its property reference matches the
# Feature 1 fixture property a0000000-...-000000000001 and it has seeded evidence.
SEEDED_REVIEW_ID = "d4000000-0000-0000-0000-000000000001"
EVIDENCE_STATES = ["confirmed", "non_intersection", "partial_coverage", "unavailable"]

SITE_REVIEW: dict[str, Any] = {
    "type": "object",
    "required": [
        "id",
        "property_ref",
        "address_display",
        "title",
        "status",
        "disposition",
        "checklist",
        "verification_questions",
        "notes",
        "ai_run_ref",
        "created_at",
        "updated_at",
        "version",
    ],
    "properties": {
        "id": {"type": "string", "format": "uuid"},
        "property_ref": {"type": "string", "minLength": 1},
        "address_display": {"type": "string", "minLength": 1},
        "title": {"type": "string", "minLength": 1},
        "status": {"enum": ["draft", "in_review", "completed", "archived"]},
        "disposition": {"enum": ["undecided", "proceed", "hold", "do_not_proceed"]},
        "checklist": {"type": "array"},
        "verification_questions": {"type": "array"},
        "notes": {"type": "string"},
        "ai_run_ref": {"type": ["string", "null"]},
        "created_at": {"type": "string", "minLength": 1},
        "updated_at": {"type": "string", "minLength": 1},
        "version": {"type": "integer", "minimum": 1},
    },
}


def validate_schema(payload: object, schema: dict[str, Any]) -> None:
    """Validate a live payload with format checks, so contract drift fails the test."""
    jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER
    ).validate(payload)
