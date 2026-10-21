"""Endpoint function 1: create a site review with ``POST /api/due-diligence/v1/site-reviews``.

The happy path creates a uniquely titled review against the seeded property, reads it back and
deletes it. The failure cases send invalid payloads and prove that each is refused with a
structured ``422`` and that nothing was persisted.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import pytest

from shared_testkit.endpoints import EndpointClient, expect_json, expect_problem

from .site_reviews import SEEDED_REVIEW_ID, SITE_REVIEW, SITE_REVIEWS, validate_schema

pytestmark = pytest.mark.endpoint


def _unique_title(purpose: str) -> str:
    return f"Endpoint test {purpose} {uuid.uuid4().hex[:12]}"


def _new_review(client: EndpointClient, title: str) -> dict[str, Any]:
    """A valid payload for the seeded property, so Feature 1 validation accepts it too."""
    seeded = client.get_json(f"{SITE_REVIEWS}/{SEEDED_REVIEW_ID}")
    return {
        "property_ref": seeded["property_ref"],
        "address_display": seeded["address_display"],
        "title": title,
        "notes": "Created and deleted by the student-4 endpoint tests.",
    }


def _titled(client: EndpointClient, title: str) -> list[dict[str, Any]]:
    page = client.get_json(SITE_REVIEWS, params={"limit": 200})
    assert isinstance(page["items"], list)
    return [item for item in page["items"] if item["title"] == title]


def test_create_site_review_persists_a_draft_that_can_be_read_and_deleted(
    endpoint_client: EndpointClient, created_reviews: list[str]
) -> None:
    payload = _new_review(endpoint_client, _unique_title("create"))

    created = expect_json(endpoint_client.post(SITE_REVIEWS, json=payload), status=201)
    created_reviews.append(created["id"])

    validate_schema(created, SITE_REVIEW)
    for field in ("property_ref", "address_display", "title", "notes"):
        assert created[field] == payload[field]
    assert (created["status"], created["disposition"], created["version"]) == (
        "draft",
        "undecided",
        1,
    )
    assert (created["checklist"], created["verification_questions"]) == ([], [])

    item_path = f"{SITE_REVIEWS}/{created['id']}"
    assert endpoint_client.get_json(item_path) == created
    assert [item["id"] for item in _titled(endpoint_client, payload["title"])] == [created["id"]]

    deleted = expect_json(endpoint_client.delete(item_path), status=200)
    assert deleted == {"deleted": created["id"]}
    expect_problem(endpoint_client.get(item_path), status=404, code="site_review_not_found")
    assert _titled(endpoint_client, payload["title"]) == []


def _without(field: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    return lambda body: {key: value for key, value in body.items() if key != field}


def _with(field: str, value: object) -> Callable[[dict[str, Any]], dict[str, Any]]:
    return lambda body: {**body, field: value}


@pytest.mark.parametrize(
    ("mutate", "detail"),
    [
        pytest.param(_without("title"), "title is required", id="missing-title"),
        pytest.param(_with("property_ref", "   "), "property_ref is required", id="blank-ref"),
        pytest.param(
            _with("status", "published"), "status is not a supported value", id="unknown-status"
        ),
        pytest.param(
            _with("disposition", "buy"),
            "disposition is not a supported value",
            id="unknown-disposition",
        ),
        pytest.param(
            _with("checklist", "check zoning"),
            "checklist and verification_questions must be arrays",
            id="checklist-not-array",
        ),
    ],
)
def test_invalid_site_review_is_rejected_and_not_persisted(
    endpoint_client: EndpointClient,
    created_reviews: list[str],
    mutate: Callable[[dict[str, Any]], dict[str, Any]],
    detail: str,
) -> None:
    title = _unique_title("invalid")
    body = mutate(_new_review(endpoint_client, title))

    response = endpoint_client.post(SITE_REVIEWS, json=body)

    if response.status_code == 201:
        created_reviews.append(response.json()["id"])
    problem = expect_problem(response, status=422, code="invalid_site_review")
    assert problem.detail == detail
    assert _titled(endpoint_client, title) == []


def test_non_json_body_is_rejected(endpoint_client: EndpointClient) -> None:
    response = endpoint_client.post(
        SITE_REVIEWS,
        content=b"title=not-json",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    problem = expect_problem(response, status=422, code="invalid_site_review")
    assert problem.detail == "request body must be a JSON object"
