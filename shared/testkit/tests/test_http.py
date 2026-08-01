"""Tests for shared HTTP assertions."""

import pytest

from shared_testkit import assert_problem_detail


def test_assert_problem_detail_accepts_matching_payload() -> None:
    assert_problem_detail(
        {"title": "Missing", "status": 404, "code": "not_found"},
        status=404,
        code="not_found",
    )


def test_assert_problem_detail_rejects_wrong_code() -> None:
    with pytest.raises(AssertionError):
        assert_problem_detail(
            {"title": "Missing", "status": 404, "code": "not_found"},
            status=404,
            code="different_code",
        )
