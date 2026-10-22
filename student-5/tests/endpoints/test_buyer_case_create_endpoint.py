"""Buyer-case creation against a running public API; no AI services required."""

from __future__ import annotations

import pytest

from shared_testkit.endpoints import EndpointClient, expect_json, expect_problem

pytestmark = pytest.mark.endpoint
API = "/api/buyer-workspaces/v1/buyer-cases"


def test_create_buyer_case_and_read_back(
    endpoint_client: EndpointClient, created_buyer_cases: list[str]
) -> None:
    payload = {
        "name": "Endpoint buyer-case creation",
        "budget_min_aud": 700000,
        "budget_max_aud": 900000,
        "target_suburbs": [{"state": "NSW", "locality": "MASCOT"}],
        "preferences": {"dwelling_types": ["apartment"], "priorities": ["transport"]},
    }
    request_id = endpoint_client.new_request_id()
    response = endpoint_client.post(API, json=payload, request_id=request_id)
    created = expect_json(response, status=201)
    created_buyer_cases.append(created["id"])
    assert response.headers["X-Request-ID"] == request_id
    assert created["status"] == "active"
    assert created["version"] == 1
    assert "owner_ref" not in created
    assert "X-PropertyScope-Internal-Token" not in response.headers
    for key, value in payload.items():
        assert created[key] == value
    assert endpoint_client.get_json(f"{API}/{created['id']}") == created


def test_create_buyer_case_rejects_inverted_budget(endpoint_client: EndpointClient) -> None:
    request_id = endpoint_client.new_request_id()
    response = endpoint_client.post(
        API,
        json={"name": "Rejected budget", "budget_min_aud": 900000, "budget_max_aud": 700000},
        request_id=request_id,
    )
    expect_problem(response, status=422, code="validation_failed", request_id=request_id)
    assert response.headers["X-Request-ID"] == request_id
    assert "owner_ref" not in response.json()
