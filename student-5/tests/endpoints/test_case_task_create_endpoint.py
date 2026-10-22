"""Case-task creation and missing-parent rejection over the public HTTP boundary."""

from __future__ import annotations

import pytest

from shared_testkit.endpoints import EndpointClient, expect_json, expect_problem

pytestmark = pytest.mark.endpoint
API = "/api/buyer-workspaces/v1/buyer-cases"


def test_create_case_task_and_read_back(
    endpoint_client: EndpointClient, created_buyer_cases: list[str]
) -> None:
    case = expect_json(endpoint_client.post(API, json={"name": "Endpoint task parent"}), status=201)
    created_buyer_cases.append(case["id"])
    tasks = f"{API}/{case['id']}/tasks"
    request_id = endpoint_client.new_request_id()
    response = endpoint_client.post(
        tasks,
        json={"title": "Confirm inspection follow-up", "due_date": "2026-12-01"},
        request_id=request_id,
    )
    created = expect_json(response, status=201)
    assert response.headers["X-Request-ID"] == request_id
    assert created["title"] == "Confirm inspection follow-up"
    assert created["due_date"] == "2026-12-01"
    assert created["buyer_case_id"] == case["id"]
    assert created["completed"] is False
    assert created["version"] == 1
    assert created["case_property_id"] is None
    assert "owner_ref" not in created
    assert endpoint_client.get_json(f"{tasks}/{created['id']}") == created
    assert endpoint_client.get_json(tasks)["items"] == [created]


def test_create_case_task_rejects_unknown_case(endpoint_client: EndpointClient) -> None:
    path = f"{API}/00000000-0000-0000-0000-000000000000"
    expect_problem(endpoint_client.get(path), status=404, code="resource_not_found")
    request_id = endpoint_client.new_request_id()
    response = endpoint_client.post(
        f"{path}/tasks", json={"title": "Missing case task"}, request_id=request_id
    )
    expect_problem(response, status=404, code="resource_not_found", request_id=request_id)
    assert response.headers["X-Request-ID"] == request_id
