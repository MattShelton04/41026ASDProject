"""Assertions for shared HTTP response contracts."""

from collections.abc import Mapping

from shared_contracts import ProblemDetail


def assert_problem_detail(payload: Mapping[str, object], *, status: int, code: str) -> None:
    """Validate a response payload and its expected stable identifiers."""
    problem = ProblemDetail.model_validate(payload)
    assert problem.status == status
    assert problem.code == code
