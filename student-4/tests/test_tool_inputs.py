"""Tool input validation does not need a running web service."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

# Load the pure boundary module without importing the package's Flask application.
SPEC = importlib.util.spec_from_file_location(
    "due_diligence_tool_inputs",
    Path(__file__).parents[1]
    / "backend"
    / "src"
    / "propertyscope_due_diligence"
    / "tool_inputs.py",
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


@pytest.mark.parametrize(
    "body",
    [
        None,
        [],
        ["x"],
        "x",
        {},
        {"site_review_id": "../site-reviews"},
        {"site_review_id": "x?limit=100"},
        {"site_review_id": 42},
        {"site_review_id": ""},
        {"site_review_id": "00000000-0000-0000-0000-000000000001", "other": True},
    ],
)
def test_tool_rejects_non_contract_values(body: object) -> None:
    with pytest.raises(ValueError):
        module.review_identifier(body)


def test_tool_normalises_a_valid_uuid() -> None:
    result = module.review_identifier({"site_review_id": "AAAAAAAA-0000-0000-0000-000000000001"})
    assert result == "aaaaaaaa-0000-0000-0000-000000000001"
