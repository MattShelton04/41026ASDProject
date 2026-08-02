"""Cross-service HTTP headers, health responses, and error contracts."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated

from pydantic import AfterValidator, Field

from shared_contracts.base import ContractModel

REQUEST_ID_HEADER = "X-Request-ID"
AGENT_RUN_ID_HEADER = "X-Agent-Run-ID"
IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"
TRACEPARENT_HEADER = "traceparent"
LAST_EVENT_ID_HEADER = "Last-Event-ID"
PROBLEM_DETAIL_MEDIA_TYPE = "application/problem+json"

MAX_IDEMPOTENCY_KEY_LENGTH = 200
MAX_REQUEST_ID_LENGTH = 200
REQUEST_ID_PATTERN_TEXT = r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$"
TRACEPARENT_PATTERN_TEXT = r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$"

_REQUEST_ID_PATTERN = re.compile(REQUEST_ID_PATTERN_TEXT)
_TRACEPARENT_PATTERN = re.compile(TRACEPARENT_PATTERN_TEXT)


def is_valid_request_id(value: str) -> bool:
    """Return whether a request ID is safe to echo, persist, and forward."""
    return _REQUEST_ID_PATTERN.fullmatch(value) is not None


def is_valid_traceparent(value: str) -> bool:
    """Validate the supported W3C version-00 shape and non-zero identifiers."""
    if _TRACEPARENT_PATTERN.fullmatch(value) is None:
        return False
    _, trace_id, parent_id, _ = value.split("-")
    return trace_id != "0" * 32 and parent_id != "0" * 16


def trace_id_from_traceparent(value: str | None) -> str | None:
    """Return the safe trace identifier used for correlation-only log fields."""
    if value is None or not is_valid_traceparent(value):
        return None
    return value.split("-")[1]


def _validated_traceparent(value: str) -> str:
    if not is_valid_traceparent(value):
        raise ValueError("traceparent must contain non-zero trace and parent identifiers")
    return value


IdempotencyKey = Annotated[
    str,
    Field(min_length=1, max_length=MAX_IDEMPOTENCY_KEY_LENGTH),
]
RequestId = Annotated[
    str,
    Field(
        min_length=1,
        max_length=MAX_REQUEST_ID_LENGTH,
        pattern=REQUEST_ID_PATTERN_TEXT,
    ),
]
Traceparent = Annotated[
    str,
    Field(pattern=TRACEPARENT_PATTERN_TEXT),
    AfterValidator(_validated_traceparent),
]


class HealthStatus(StrEnum):
    """Portable health state used by liveness and readiness endpoints."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class HealthCheck(ContractModel):
    """State of one readiness dependency or internal component."""

    status: HealthStatus
    detail: str | None = None


class HealthResponse(ContractModel):
    """Standard service health payload."""

    service: str = Field(min_length=1, max_length=100)
    status: HealthStatus
    version: str = Field(min_length=1, max_length=50)
    checks: dict[str, HealthCheck] = Field(default_factory=dict)


class FieldIssue(ContractModel):
    """Validation issue associated with a request field."""

    field: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=500)
    code: str = Field(min_length=1, max_length=100)


class ProblemDetail(ContractModel):
    """Problem Details-compatible error response with stable project extensions."""

    type: str = "about:blank"
    title: str = Field(min_length=1, max_length=200)
    status: int = Field(ge=400, le=599)
    detail: str | None = Field(default=None, max_length=2_000)
    instance: str | None = Field(default=None, max_length=500)
    code: str = Field(min_length=1, max_length=100)
    request_id: str | None = Field(default=None, max_length=200)
    errors: tuple[FieldIssue, ...] = ()
