"""The cross-feature browser adapter is isolated, explicit and deterministic."""

from __future__ import annotations

import pytest
from scripts.ui_experience_fixtures import BUYER_ID, MARKET_ID, ExperienceFixtures


def test_sessions_and_empty_collections_do_not_share_state() -> None:
    first, second = ExperienceFixtures(), ExperienceFixtures()
    first.records["market-cases"].clear()
    assert len(second.records["market-cases"]) == 1
    empty = ExperienceFixtures("empty")
    empty.records["notes"].append({"id": "isolated"})
    assert not empty.records["tasks"]


def test_unknown_api_fails_and_scenario_names_are_validated() -> None:
    fixture = ExperienceFixtures()
    assert fixture.response("GET", "/api/unknown")[0] == 404
    with pytest.raises(ValueError, match="Unknown scenario"):
        ExperienceFixtures("pretend-live")


def test_validation_failure_keeps_records_unchanged() -> None:
    fixture = ExperienceFixtures("validation-error")
    before = fixture.records["market-cases"][0].copy()
    status, _ = fixture.response(
        "PATCH", f"/api/market-intelligence/v1/market-cases/{MARKET_ID}",
        body={"name": "Must not save"},
    )
    assert status == 422
    assert fixture.records["market-cases"][0] == before


def test_buyer_children_are_scoped_to_their_parent() -> None:
    fixture = ExperienceFixtures()
    path = f"/api/buyer-workspaces/v1/buyer-cases/{BUYER_ID}/tasks"
    status, task = fixture.response("POST", path, body={"title": "Verify source"})
    assert status == 201
    assert task["buyer_case_id"] == BUYER_ID
    missing = path.replace(BUYER_ID, "unknown")
    assert fixture.response("GET", missing)[0] == 404
    assert fixture.response("DELETE", path.rsplit("/", 1)[0])[0] == 204
    assert not fixture.records["tasks"]


def test_cancelled_turn_cannot_be_resurrected_by_polling() -> None:
    fixture = ExperienceFixtures()
    base = "/api/data-platform/v1/assistant/turns"
    status, run = fixture.response("POST", base, body={"message": "Check evidence"})
    assert status == 202
    path = f"{base}/{run['id']}"
    assert fixture.response("POST", f"{path}/cancel")[0] == 200
    for _ in range(5):
        assert fixture.response("GET", path)[1]["run"]["status"] == "cancelled"


def test_provider_unavailable_never_creates_a_run() -> None:
    fixture = ExperienceFixtures("provider-unavailable")
    assert fixture.response("POST", "/api/data-platform/v1/assistant/turns")[0] == 503
    assert not fixture.turns


def test_large_and_long_scenarios_are_bounded() -> None:
    fixture = ExperienceFixtures("large")
    assert len(fixture.records["market-cases"]) == 100
    assert len({row["id"] for row in fixture.records["market-cases"]}) == 100
    long = ExperienceFixtures("long-content")
    assert len(long.records["market-cases"][0]["name"]) <= 120
