"""Tests for the shared HTTP contracts."""

import pytest
from pydantic import ValidationError

from shared_contracts import FieldIssue, HealthResponse, HealthStatus, ProblemDetail


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
