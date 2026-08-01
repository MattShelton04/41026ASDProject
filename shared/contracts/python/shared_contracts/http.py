"""Cross-service HTTP headers, health responses, and error contracts."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from shared_contracts.base import ContractModel

REQUEST_ID_HEADER = "X-Request-ID"
AGENT_RUN_ID_HEADER = "X-Agent-Run-ID"
IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"
TRACEPARENT_HEADER = "traceparent"


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
