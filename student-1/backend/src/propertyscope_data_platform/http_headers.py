"""Canonical cross-service HTTP header propagation for Feature 1."""

from __future__ import annotations

from collections.abc import Mapping

from werkzeug.datastructures import Headers

from shared_contracts import (
    AGENT_RUN_ID_HEADER,
    IDEMPOTENCY_KEY_HEADER,
    REQUEST_ID_HEADER,
    TRACEPARENT_HEADER,
    is_valid_request_id,
    is_valid_traceparent,
)

_CANONICAL_FORWARDED_HEADERS = {
    REQUEST_ID_HEADER.lower(): REQUEST_ID_HEADER,
    AGENT_RUN_ID_HEADER.lower(): AGENT_RUN_ID_HEADER,
    TRACEPARENT_HEADER.lower(): TRACEPARENT_HEADER,
    IDEMPOTENCY_KEY_HEADER.lower(): IDEMPOTENCY_KEY_HEADER,
}


def forwarded_headers(headers: Mapping[str, str] | Headers) -> dict[str, str]:
    """Return the allowlisted headers using canonical, case-insensitive names.

    WSGI title-cases inbound names (for example ``X-Request-Id``), so comparing
    iterated names with their display spelling loses correlation metadata. Values
    used for cross-service correlation are validated before they are forwarded.
    """
    forwarded: dict[str, str] = {}
    for name, raw_value in headers.items():
        canonical = _CANONICAL_FORWARDED_HEADERS.get(name.lower())
        if canonical is None:
            continue
        value = raw_value.strip()
        if not value:
            continue
        if canonical == REQUEST_ID_HEADER and not is_valid_request_id(value):
            continue
        if canonical == TRACEPARENT_HEADER:
            value = value.lower()
            if not is_valid_traceparent(value):
                continue
        forwarded[canonical] = value
    return forwarded
