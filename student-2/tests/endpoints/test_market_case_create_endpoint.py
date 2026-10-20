"""Endpoint function 1: ``POST /api/market-intelligence/v1/market-cases``.

These run against the Feature 2 service in the Compose stack, not a Flask test client, so they
exercise the real nginx -> backend -> database path. The shared plugin skips them unless
``PROPERTYSCOPE_ENDPOINT_BASE_URL`` is set, which keeps the default quality gate free of Docker.

Both cases are answered by Feature 2 alone. The service does call Feature 1 to check the
property, but that check cannot decide either assertion here: the CI job starts only the Feature 2
services, matching every other feature's workflow, and an unreachable Feature 1 is a recorded
state rather than a refusal. Asserting on it would make this job fail whenever another student's
service is down.
"""

from __future__ import annotations

import pytest

from shared_testkit.endpoints import EndpointClient

pytestmark = pytest.mark.endpoint

API = "/api/market-intelligence/v1"
# The fixture property Feature 1 seeds; the UI pre-selects it for the Release 0 demonstration.
FIXTURE_PROPERTY = "a0000000-0000-0000-0000-000000000001"
# What the create path can store: Feature 1 answered (`verified`), or could not be reached or
# errored (`unavailable`). A property Feature 1 reports as missing is refused before any row is
# written, and `fixture_verified` is written only by the seed migration, never by this endpoint.
CREATABLE_VALIDATION_STATES = {"verified", "unavailable"}


def _payload(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "name": "Endpoint test case",
        "property_ref": FIXTURE_PROPERTY,
        "address_display": "11 Example Street, Sydney NSW 2000",
        "date_from": "2024-01-01",
        "date_to": "2025-12-31",
        "status": "draft",
        "notes": "Created by the Feature 2 endpoint tests.",
        "filters": {"minimum_match_tier": "B"},
    }
    body.update(overrides)
    return body


def test_a_valid_case_is_created_and_readable_at_its_own_url(
    endpoint_client: EndpointClient, created_cases: list[str]
) -> None:
    """Happy path: a case is created, persisted and readable at its own URL."""
    response = endpoint_client.post(f"{API}/market-cases", json=_payload())
    assert response.status_code == 201, response.text[:400]

    case = response.json()
    created_cases.append(case["id"])
    assert case["name"] == "Endpoint test case"
    assert case["address_display"] == "11 Example Street, Sydney NSW 2000"
    # A new case starts at version 1; optimistic concurrency depends on it.
    assert case["version"] == 1
    # The state is recorded by the service from its own check, not taken from the request.
    assert case["property_validation_state"] in CREATABLE_VALIDATION_STATES

    reread = endpoint_client.get(f"{API}/market-cases/{case['id']}")
    assert reread.status_code == 200
    assert reread.json()["id"] == case["id"]
    assert reread.json()["version"] == 1


def test_an_invalid_date_window_is_refused_and_creates_nothing(
    endpoint_client: EndpointClient,
) -> None:
    """Failure path: the service refuses a window that ends before it starts, and writes no row.

    The window is checked while the request is being parsed, before the property check and before
    the database is touched, so this holds whatever Feature 1 is doing.
    """
    before = endpoint_client.get_json(f"{API}/market-cases")["items"]

    response = endpoint_client.post(
        f"{API}/market-cases",
        json=_payload(
            name="Endpoint reversed window", date_from="2025-12-31", date_to="2024-01-01"
        ),
    )
    assert response.status_code == 422, response.text[:400]

    problem = response.json()
    assert problem["code"] == "invalid_market_case"
    assert response.headers["content-type"].startswith("application/problem+json")

    after = endpoint_client.get_json(f"{API}/market-cases")["items"]
    assert len(after) == len(before)
    assert all(item["name"] != "Endpoint reversed window" for item in after)
