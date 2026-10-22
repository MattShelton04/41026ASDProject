"""Endpoint function 1: list the available suburb summaries."""

from __future__ import annotations

import pytest

from shared_testkit.endpoints import EndpointClient, expect_json

pytestmark = pytest.mark.endpoint

SUBURBS = "/api/suburb-analytics/v1/suburbs"


def test_seeded_suburbs_are_returned_as_a_bounded_page(
    endpoint_client: EndpointClient,
) -> None:
    page = expect_json(endpoint_client.get(SUBURBS, params={"limit": 2}), status=200)

    assert page["count"] == 2
    assert len(page["items"]) == 2
    assert page["page"]["limit"] == 2
    assert page["page"]["total"] >= 10
    assert page["page"]["has_more"] is True
    assert all(item["state"] == "NSW" for item in page["items"])


def test_invalid_limit_is_returned_as_problem_details(
    endpoint_client: EndpointClient,
) -> None:
    response = endpoint_client.get(SUBURBS, params={"limit": "invalid"})

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    problem = response.json()
    assert problem["status"] == 422
    assert problem["code"]
    assert problem["type"].startswith("https://propertyscope.invalid/problems/")
    assert problem["detail"] == "The request could not be applied."
