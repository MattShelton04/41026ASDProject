"""Endpoint function 1: ``GET /api/data-platform/v1/properties/search`` on the live service."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from shared_contracts import REQUEST_ID_HEADER
from shared_testkit.endpoints import EndpointClient, expect_json, expect_problem

pytestmark = pytest.mark.endpoint

ContractValidator = Callable[[object, dict[str, Any]], None]
SEARCH = "/api/data-platform/v1/properties/search"
SEARCH_PAGE = {"$ref": "#/components/schemas/PropertySearchPage"}
PROBLEM = {"$ref": "#/components/schemas/Problem"}


def test_seeded_address_returns_typed_ranked_matches(
    endpoint_client: EndpointClient, validate_contract: ContractValidator, search_query: str
) -> None:
    request_id = endpoint_client.new_request_id()
    response = endpoint_client.get(
        SEARCH,
        params={"q": search_query, "state": "NSW", "limit": 10},
        request_id=request_id,
    )

    page = expect_json(response, status=200)
    validate_contract(page, SEARCH_PAGE)
    assert response.headers[REQUEST_ID_HEADER] == request_id
    assert page["supported"] is True
    assert page["query"] == search_query
    assert page["items"], f"no accepted property matched {search_query!r}: {page}"
    assert page["count"] == len(page["items"])
    assert page["limit"] == 10
    assert page["total"] >= page["count"]
    assert len({item["property_ref"] for item in page["items"]}) == page["count"]
    best = page["items"][0]
    assert best["state"] == "NSW"
    assert best["score"] > 0
    matched = best["matched_address"].lower()
    missing = [term for term in search_query.lower().split() if term not in matched]
    assert not missing, f"best match {best['matched_address']!r} lacks query terms {missing}"


@pytest.mark.parametrize(
    "params",
    [
        pytest.param({}, id="missing-q"),
        pytest.param({"q": "1"}, id="one-character-q"),
        pytest.param({"q": "  a  "}, id="whitespace-padded-short-q"),
        pytest.param({"q": "x" * 201}, id="over-long-q"),
    ],
)
def test_invalid_query_is_a_structured_problem(
    endpoint_client: EndpointClient,
    validate_contract: ContractValidator,
    params: dict[str, str],
) -> None:
    request_id = endpoint_client.new_request_id()
    response = endpoint_client.get(SEARCH, params=params, request_id=request_id)

    problem = expect_problem(response, status=422, code="invalid_request", request_id=request_id)
    validate_contract(response.json(), PROBLEM)
    assert problem.detail == "q must contain 2 to 200 characters"
    assert response.headers[REQUEST_ID_HEADER] == request_id
