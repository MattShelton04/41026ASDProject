"""Endpoint function: accepted suburb search, detail and map context for map consumers.

The tests work against any stack. A freshly seeded stack has no accepted suburb boundaries, so
the search answers ``dataset_unavailable`` and the data-dependent checks skip; a stack with the
real ``nsw-suburb-boundaries`` release also exercises detail, map context and revalidation.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from shared_testkit.endpoints import EndpointClient, expect_json, expect_problem

pytestmark = pytest.mark.endpoint

SUBURBS = "/api/data-platform/v1/suburbs"
CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"


@cache
def _schema(name: str) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(
        (CONTRACTS / f"{name}.v1.schema.json").read_text(encoding="utf-8")
    )
    return document


def _validate(payload: object, name: str) -> None:
    jsonschema.Draft202012Validator(_schema(name)).validate(payload)


@pytest.fixture(scope="module")
def accepted_suburb(endpoint_client: EndpointClient) -> dict[str, Any]:
    """A suburb with valid geometry from the accepted release, or skip without one."""
    for query in ("Parramatta", "Newtown", "Dubbo", "Mayfield"):
        page = endpoint_client.get_json(f"{SUBURBS}/search", params={"q": query})
        _validate(page, "suburb-search")
        if page["availability"]["status"] != "available":
            pytest.skip("this stack has no accepted nsw-suburb-boundaries release")
        for item in page["items"]:
            if item["geometry_status"] == "valid":
                return dict(item)
    pytest.skip("no sampled suburb has valid geometry in the accepted release")


def test_search_is_schema_valid_and_reports_availability(endpoint_client: EndpointClient) -> None:
    page = endpoint_client.get_json(f"{SUBURBS}/search", params={"q": "  mayfield "})

    _validate(page, "suburb-search")
    assert page["query"]["normalised"] == "MAYFIELD"
    assert page["count"] == len(page["items"])
    if page["availability"]["status"] == "dataset_unavailable":
        assert (page["match"], page["items"], page["release"]) == ("none", [], None)
    else:
        assert all(item["name"] == "MAYFIELD" for item in page["items"])


def test_detail_and_map_context_revalidate_with_their_etags(
    endpoint_client: EndpointClient, accepted_suburb: dict[str, Any]
) -> None:
    path = f"{SUBURBS}/{accepted_suburb['suburb_id']}"
    detail_response = endpoint_client.get(path)
    detail = expect_json(detail_response)
    _validate(detail, "suburb-detail")
    assert detail["suburb_id"] == accepted_suburb["suburb_id"]
    assert detail_response.headers["Cache-Control"] == "no-cache"
    revalidated = endpoint_client.get(
        path, headers={"If-None-Match": detail_response.headers["ETag"]}
    )
    assert revalidated.status_code == 304
    assert revalidated.headers["ETag"] == detail_response.headers["ETag"]

    context_response = endpoint_client.get(
        f"{path}/map-context", params={"categories": "schools,train-station", "zoom": 12}
    )
    context = expect_json(context_response)
    _validate(context, "suburb-map-context")
    assert context["request"]["detail"] == "medium"
    assert set(context["coverage"]) == {"boundary", "schools", "train-station"}
    assert context["coverage"]["boundary"] == "accepted"
    assert context["suburb"]["boundary"]["geometry"] is not None
    for layer in ("schools", "train-station"):
        details = context["layer_details"][layer]
        assert details["feature_count"] == len(context["layers"][layer]["features"])
    revalidated = endpoint_client.get(
        f"{path}/map-context",
        params={"categories": "schools,train-station", "zoom": 12},
        headers={"If-None-Match": context_response.headers["ETag"]},
    )
    assert revalidated.status_code == 304


@pytest.mark.parametrize(
    ("path", "params", "code"),
    [
        pytest.param("/108033054/map-context", {"categories": "parks"}, "unsupported_category"),
        pytest.param("/108033054/map-context", {"detail": "low", "zoom": 9}, "invalid_request"),
        pytest.param("/108033054/map-context", {"limit": 0}, "invalid_request"),
        pytest.param("/not-a-cadid", {}, "invalid_request"),
        pytest.param("/search", {"q": "x", "radius": 5}, "invalid_request"),
    ],
)
def test_invalid_requests_are_structured_problems(
    endpoint_client: EndpointClient, path: str, params: dict[str, Any], code: str
) -> None:
    request_id = endpoint_client.new_request_id()

    response = endpoint_client.get(f"{SUBURBS}{path}", params=params, request_id=request_id)

    expect_problem(response, status=422, code=code, request_id=request_id)


def test_unknown_suburb_is_not_found(
    endpoint_client: EndpointClient, accepted_suburb: dict[str, Any]
) -> None:
    request_id = endpoint_client.new_request_id()

    response = endpoint_client.get(f"{SUBURBS}/999999999999", request_id=request_id)

    expect_problem(response, status=404, code="suburb_not_found", request_id=request_id)
