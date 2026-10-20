"""Endpoint function 2: ``PUT /api/market-intelligence/v1/market-cases/{id}``.

Updates use optimistic concurrency: the caller sends the version it read, and a stale version is
refused rather than silently overwriting someone else's edit. Both paths run against the Feature
2 service in the Compose stack.
"""

from __future__ import annotations

from typing import Any

import pytest

from shared_testkit.endpoints import EndpointClient

pytestmark = pytest.mark.endpoint

API = "/api/market-intelligence/v1"
FIXTURE_PROPERTY = "a0000000-0000-0000-0000-000000000001"


def _create(endpoint_client: EndpointClient, created_cases: list[str]) -> dict[str, Any]:
    response = endpoint_client.post(
        f"{API}/market-cases",
        json={
            "name": "Endpoint update case",
            "property_ref": FIXTURE_PROPERTY,
            "address_display": "11 Example Street, Sydney NSW 2000",
            "date_from": "2024-01-01",
            "date_to": "2025-12-31",
            "status": "draft",
            "filters": {"minimum_match_tier": "B"},
        },
    )
    assert response.status_code == 201, response.text[:400]
    case: dict[str, Any] = response.json()
    created_cases.append(str(case["id"]))
    return case


def test_an_update_with_the_current_version_succeeds(
    endpoint_client: EndpointClient, created_cases: list[str]
) -> None:
    """Happy path: the change is applied and the version advances."""
    case = _create(endpoint_client, created_cases)

    response = endpoint_client.put(
        f"{API}/market-cases/{case['id']}",
        json={"version": case["version"], "name": "Renamed by endpoint test", "status": "active"},
    )
    assert response.status_code == 200, response.text[:400]

    updated = response.json()
    assert updated["name"] == "Renamed by endpoint test"
    assert updated["status"] == "active"
    # The version advances so the next writer cannot reuse the one we just consumed.
    assert updated["version"] == case["version"] + 1

    reread = endpoint_client.get_json(f"{API}/market-cases/{case['id']}")
    assert reread["name"] == "Renamed by endpoint test"
    assert reread["version"] == updated["version"]


def test_a_stale_version_is_refused_and_changes_nothing(
    endpoint_client: EndpointClient, created_cases: list[str]
) -> None:
    """Failure path: a second writer holding the old version is refused with a conflict."""
    case = _create(endpoint_client, created_cases)
    stale_version = case["version"]

    first = endpoint_client.put(
        f"{API}/market-cases/{case['id']}",
        json={"version": stale_version, "name": "First writer wins"},
    )
    assert first.status_code == 200, first.text[:400]

    # The second writer still holds the version it read before the first write landed.
    conflict = endpoint_client.put(
        f"{API}/market-cases/{case['id']}",
        json={"version": stale_version, "name": "Second writer should not win"},
    )
    assert conflict.status_code == 409, conflict.text[:400]
    assert conflict.json()["code"] == "version_conflict"
    assert conflict.headers["content-type"].startswith("application/problem+json")

    # The refused write left the first writer's value in place.
    reread = endpoint_client.get_json(f"{API}/market-cases/{case['id']}")
    assert reread["name"] == "First writer wins"
