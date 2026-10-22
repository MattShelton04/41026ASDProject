"""Endpoint function 2: create a saved suburb comparison."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from shared_testkit.endpoints import EndpointClient, expect_json, expect_problem

pytestmark = pytest.mark.endpoint

COMPARISONS = "/api/suburb-analytics/v1/suburb-comparisons"


@pytest.fixture
def created_comparisons(endpoint_client: EndpointClient) -> Iterator[list[str]]:
    created: list[str] = []
    yield created
    for comparison_id in created:
        response = endpoint_client.delete(f"{COMPARISONS}/{comparison_id}")
        if response.status_code not in {200, 404}:
            raise AssertionError(
                f"could not clean up comparison {comparison_id}: "
                f"HTTP {response.status_code} {response.text[:300]}"
            )


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "Endpoint test comparison",
        "localities": ["Parramatta", "Newtown"],
        "from_month": "2026-01",
        "to_month": "2026-06",
        "measure": "count",
        "notes": "Created and deleted by the Feature 3 endpoint tests.",
    }
    payload.update(overrides)
    return payload


def test_valid_comparison_is_created_persisted_and_deleted(
    endpoint_client: EndpointClient,
    created_comparisons: list[str],
) -> None:
    created_body = expect_json(endpoint_client.post(COMPARISONS, json=_payload()), status=201)
    created = created_body["comparison"]
    created_comparisons.append(created["id"])

    assert created["name"] == "Endpoint test comparison"
    assert created["localities"] == ["Parramatta", "Newtown"]
    assert created["measure"] == "count"
    assert created["version"] == 1

    reread = expect_json(endpoint_client.get(f"{COMPARISONS}/{created['id']}"), status=200)[
        "comparison"
    ]
    assert reread == created

    expect_json(endpoint_client.delete(f"{COMPARISONS}/{created['id']}"), status=200)
    created_comparisons.remove(created["id"])
    expect_problem(
        endpoint_client.get(f"{COMPARISONS}/{created['id']}"),
        status=404,
        code="comparison_not_found",
    )


def test_invalid_measure_is_rejected_without_creating_a_comparison(
    endpoint_client: EndpointClient,
) -> None:
    before = expect_json(endpoint_client.get(COMPARISONS), status=200)

    response = endpoint_client.post(COMPARISONS, json=_payload(measure="score"))
    problem = expect_problem(response, status=422, code="invalid_request")
    assert problem.detail == "measure must be count or rate"

    after = expect_json(endpoint_client.get(COMPARISONS), status=200)
    assert after["count"] == before["count"]
    assert all(item["name"] != "Endpoint test comparison" for item in after["items"])
