"""Problem Details responses used by the executable feature fixture."""

from __future__ import annotations

from flask import Response, jsonify, request

from shared_contracts import REQUEST_ID_HEADER, ProblemDetail


def problem_response(status: int, code: str, detail: str) -> Response:
    """Return the shared safe error contract without coupling it to domain logic."""
    supplied_request_id = request.headers.get(REQUEST_ID_HEADER, "").strip()
    request_id = supplied_request_id if 1 <= len(supplied_request_id) <= 200 else None
    problem = ProblemDetail(
        title=_title(status),
        status=status,
        detail=detail,
        code=code,
        instance=request.path,
        request_id=request_id,
    )
    response = jsonify(problem.model_dump(mode="json"))
    response.status_code = status
    response.content_type = "application/problem+json"
    return response


def _title(status: int) -> str:
    return {
        404: "Not found",
        409: "Conflict",
        422: "Invalid request",
    }.get(status, "Request failed")
