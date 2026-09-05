"""Validate read-only tool input before it is interpolated into an HTTP path."""

from __future__ import annotations

from uuid import UUID


def review_identifier(body: object) -> str:
    """Require the exact UUID-object shape declared by the feature tool catalogue."""
    if not isinstance(body, dict) or set(body) != {"site_review_id"}:
        raise ValueError("A site_review_id UUID is required; no other fields are accepted")
    value = body["site_review_id"]
    if not isinstance(value, str) or len(value) != 36:
        raise ValueError("site_review_id must be a UUID")
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise ValueError("site_review_id must be a UUID") from exc
    if str(parsed) != value.lower():
        raise ValueError("site_review_id must be a canonical UUID")
    return str(parsed)
