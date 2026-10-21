"""Endpoint function 2: read a review's evidence with ``GET .../site-reviews/{id}/evidence``.

The happy path reads the seeded review's planning, environmental and building evidence and checks
that every record belongs to the review's property and carries a known evidence state. The
failure cases prove that an unknown or deleted review is a structured ``404``, not an empty
success.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from shared_testkit.endpoints import EndpointClient, expect_json, expect_problem

from .site_reviews import (
    EVIDENCE_STATES,
    SEEDED_REVIEW_ID,
    SITE_REVIEW,
    SITE_REVIEWS,
    validate_schema,
)

pytestmark = pytest.mark.endpoint

_OBSERVATION_FIELDS: dict[str, Any] = {
    "id": {"type": "string", "format": "uuid"},
    "property_ref": {"type": "string", "minLength": 1},
    "evidence_state": {"enum": EVIDENCE_STATES},
    "source_name": {"type": "string", "minLength": 1},
    "source_url": {"type": ["string", "null"]},
    "summary": {"type": "string", "minLength": 1},
    "confidence": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
}
CONSTRAINT: dict[str, Any] = {
    "type": "object",
    "required": [*_OBSERVATION_FIELDS, "constraint_type"],
    "properties": {**_OBSERVATION_FIELDS, "constraint_type": {"type": "string", "minLength": 1}},
}
BUILDING: dict[str, Any] = {
    "type": "object",
    "required": [*_OBSERVATION_FIELDS, "record_type"],
    "properties": {**_OBSERVATION_FIELDS, "record_type": {"type": "string", "minLength": 1}},
}
EVIDENCE: dict[str, Any] = {
    "type": "object",
    "required": ["site_review", "constraints", "buildings"],
    "properties": {
        "site_review": SITE_REVIEW,
        "constraints": {"type": "array", "minItems": 1, "items": CONSTRAINT},
        "buildings": {"type": "array", "minItems": 1, "items": BUILDING},
    },
}


def test_seeded_review_returns_its_property_evidence(endpoint_client: EndpointClient) -> None:
    evidence = expect_json(
        endpoint_client.get(f"{SITE_REVIEWS}/{SEEDED_REVIEW_ID}/evidence"), status=200
    )

    validate_schema(evidence, EVIDENCE)
    review = evidence["site_review"]
    assert review["id"] == SEEDED_REVIEW_ID
    records = [*evidence["constraints"], *evidence["buildings"]]
    assert {record["property_ref"] for record in records} == {review["property_ref"]}
    assert len({record["id"] for record in records}) == len(records)


def test_unknown_review_evidence_is_not_found(endpoint_client: EndpointClient) -> None:
    response = endpoint_client.get(f"{SITE_REVIEWS}/{uuid.uuid4()}/evidence")

    problem = expect_problem(response, status=404, code="site_review_not_found")
    assert problem.detail == "No site review with that id"


def test_deleted_review_evidence_is_not_found(
    endpoint_client: EndpointClient, created_reviews: list[str]
) -> None:
    seeded = endpoint_client.get_json(f"{SITE_REVIEWS}/{SEEDED_REVIEW_ID}")
    created = expect_json(
        endpoint_client.post(
            SITE_REVIEWS,
            json={
                "property_ref": seeded["property_ref"],
                "address_display": seeded["address_display"],
                "title": f"Endpoint test evidence {uuid.uuid4().hex[:12]}",
            },
        ),
        status=201,
    )
    created_reviews.append(created["id"])
    evidence_path = f"{SITE_REVIEWS}/{created['id']}/evidence"
    assert expect_json(endpoint_client.get(evidence_path), status=200)["site_review"] == created

    expect_json(endpoint_client.delete(f"{SITE_REVIEWS}/{created['id']}"), status=200)

    expect_problem(endpoint_client.get(evidence_path), status=404, code="site_review_not_found")
