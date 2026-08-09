"""Shared Flask translation for safe Problem Details responses."""

from __future__ import annotations

from flask import Response, g, jsonify, request
from pydantic import ValidationError

from shared_contracts import PROBLEM_DETAIL_MEDIA_TYPE, FieldIssue, ProblemDetail

PROBLEM_TITLES = {
    400: "Invalid request",
    404: "Not found",
    409: "Conflict",
    413: "Request too large",
    415: "Unsupported media type",
    422: "Invalid request",
    500: "Internal server error",
    503: "Service unavailable",
}


def validation_issues(error: ValidationError) -> tuple[FieldIssue, ...]:
    """Convert Pydantic diagnostics to the stable public field-issue contract."""
    return tuple(
        FieldIssue(
            field=".".join(str(part) for part in issue["loc"]),
            message=issue["msg"],
            code=issue["type"],
        )
        for issue in error.errors(include_url=False)
    )


def problem_response(
    status: int,
    code: str,
    detail: str,
    *,
    title: str | None = None,
    errors: tuple[FieldIssue, ...] = (),
) -> tuple[Response, int]:
    """Build the one AI-mode Problem Details representation."""
    problem = ProblemDetail(
        title=title or PROBLEM_TITLES.get(status, "Request failed"),
        status=status,
        detail=detail,
        code=code,
        instance=request.path,
        request_id=g.get("request_id"),
        errors=errors,
    )
    response = jsonify(problem.model_dump(mode="json"))
    response.content_type = PROBLEM_DETAIL_MEDIA_TYPE
    return response, status
