"""Tests for the shared HTTP contracts."""

import pytest
from pydantic import ValidationError

from shared_contracts import (
    FieldIssue,
    HealthResponse,
    HealthStatus,
    ProblemDetail,
    is_valid_request_id,
    is_valid_traceparent,
    trace_id_from_traceparent,
)


def test_health_response_serialises_to_plain_json_values() -> None:
    response = HealthResponse(
        service="ai-mode",
        status=HealthStatus.HEALTHY,
        version="0.1.0",
    )

    assert response.model_dump(mode="json") == {
        "service": "ai-mode",
        "status": "healthy",
        "version": "0.1.0",
        "checks": {},
    }


def test_problem_detail_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ProblemDetail.model_validate(
            {
                "title": "Invalid request",
                "status": 400,
                "code": "invalid_request",
                "unexpected": True,
            }
        )


def test_problem_detail_contains_typed_field_issues() -> None:
    problem = ProblemDetail(
        title="Invalid request",
        status=422,
        code="validation_failed",
        errors=(FieldIssue(field="objective", message="Required", code="missing"),),
    )

    assert problem.errors[0].field == "objective"


def test_contract_snapshots_are_immutable() -> None:
    response = HealthResponse(service="ai-mode", status=HealthStatus.HEALTHY, version="1")

    with pytest.raises(ValidationError, match="Instance is frozen"):
        response.status = HealthStatus.UNHEALTHY


def test_correlation_identifiers_share_strict_safe_validation() -> None:
    valid_traceparent = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"

    assert is_valid_request_id("feature/request:123")
    assert not is_valid_request_id("unsafe request")
    assert is_valid_traceparent(valid_traceparent)
    assert trace_id_from_traceparent(valid_traceparent) == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert not is_valid_traceparent("00-" + "0" * 32 + "-00f067aa0ba902b7-01")
    assert trace_id_from_traceparent("invalid") is None
