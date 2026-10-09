"""Endpoint function 2: source-definition CRUD under ``/api/data-platform/v1/sources``.

Every test creates uniquely named draft definitions and deletes them again (the API
deletes only unused drafts), so repeated runs against a shared stack leave nothing behind.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import pytest

from shared_contracts import REQUEST_ID_HEADER
from shared_testkit.endpoints import EndpointClient, expect_json, expect_problem, expect_status

pytestmark = pytest.mark.endpoint

ContractValidator = Callable[[object, dict[str, Any]], None]
SOURCES = "/api/data-platform/v1/sources"
PAGE = {"$ref": "#/components/responses/Page/content/application~1json/schema"}
PROBLEM = {"$ref": "#/components/schemas/Problem"}
# The committed request fields plus the identity and optimistic-concurrency columns the
# service adds when it persists a definition.
STORED_SOURCE = {
    "allOf": [
        {"$ref": "#/components/schemas/SourceDefinitionFields"},
        {
            "type": "object",
            "required": [
                "id",
                "name",
                "publisher",
                "source_url",
                "adapter_key",
                "cadence",
                "licence_id",
                "licence_url",
                "redistribution_policy",
                "target_features_json",
                "status",
                "notes",
                "created_at",
                "updated_at",
                "version",
            ],
            "properties": {
                "id": {"type": "string", "format": "uuid"},
                "target_features_json": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 5,
                    "uniqueItems": True,
                    "items": {"type": "string"},
                },
                "created_at": {"type": "string", "minLength": 1},
                "updated_at": {"type": "string", "minLength": 1},
                "version": {"type": "integer", "minimum": 1},
            },
        },
    ]
}


def _unique_name(purpose: str) -> str:
    return f"Endpoint test {purpose} {uuid.uuid4().hex[:12]}"


def _definition(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "publisher": "PropertyScope CI endpoint tests",
        "source_url": "https://example.com/propertyscope/endpoint-test/source",
        "adapter_key": "endpoint-test-adapter",
        "cadence": "on-demand",
        "licence_id": "cc-by-4-0",
        "licence_url": "https://creativecommons.org/licenses/by/4.0/",
        "redistribution_policy": "internal-only",
        "target_features": ["feature-1"],
        "notes": "Created and deleted by the student-1 endpoint tests.",
    }


def _listed(
    client: EndpointClient, validate_contract: ContractValidator, name: str
) -> list[dict[str, Any]]:
    page = client.get_json(SOURCES, params={"q": name, "limit": 100})
    validate_contract(page, PAGE)
    assert page["count"] == len(page["items"])
    return [item for item in page["items"] if item["name"] == name]


def test_source_definition_create_list_read_update_delete(
    endpoint_client: EndpointClient,
    validate_contract: ContractValidator,
    created_sources: list[str],
) -> None:
    definition = _definition(_unique_name("lifecycle"))
    request_id = endpoint_client.new_request_id()

    created_response = endpoint_client.post(SOURCES, json=definition, request_id=request_id)
    created = expect_json(created_response, status=201)["source"]
    created_sources.append(created["id"])
    validate_contract(created, STORED_SOURCE)
    assert created_response.headers[REQUEST_ID_HEADER] == request_id
    assert (created["status"], created["version"]) == ("draft", 1)
    assert created["target_features_json"] == definition["target_features"]
    for field in ("name", "publisher", "source_url", "adapter_key", "licence_id", "notes"):
        assert created[field] == definition[field]

    listed = _listed(endpoint_client, validate_contract, definition["name"])
    assert [item["id"] for item in listed] == [created["id"]]

    item_path = f"{SOURCES}/{created['id']}"
    read = endpoint_client.get_json(item_path)["source"]
    validate_contract(read, STORED_SOURCE)
    assert read == created

    update = {**definition, "notes": "Updated by the endpoint test.", "version": 1}
    updated = expect_json(endpoint_client.put(item_path, json=update), status=200)["source"]
    validate_contract(updated, STORED_SOURCE)
    assert (updated["id"], updated["version"]) == (created["id"], 2)
    assert updated["notes"] == "Updated by the endpoint test."

    expect_status(endpoint_client.delete(item_path), 204)
    missing_id = endpoint_client.new_request_id()
    expect_problem(
        endpoint_client.get(item_path, request_id=missing_id),
        status=404,
        code="not_found",
        request_id=missing_id,
    )
    assert _listed(endpoint_client, validate_contract, definition["name"]) == []


def _without(field: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    return lambda body: {key: value for key, value in body.items() if key != field}


def _with(field: str, value: object) -> Callable[[dict[str, Any]], dict[str, Any]]:
    return lambda body: {**body, field: value}


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(_without("publisher"), id="missing-required-field"),
        pytest.param(_with("adapter_key", "Not A Key!"), id="adapter-key-pattern"),
        pytest.param(_with("source_url", "not-a-url"), id="source-url-not-http"),
        pytest.param(_with("target_features", []), id="no-target-features"),
        pytest.param(_with("target_features", ["feature-1"] * 2), id="duplicate-targets"),
        pytest.param(_with("status", "published"), id="unknown-status"),
        pytest.param(_with("owner", "someone"), id="unexpected-field"),
    ],
)
def test_invalid_source_definition_is_rejected_and_not_persisted(
    endpoint_client: EndpointClient,
    validate_contract: ContractValidator,
    created_sources: list[str],
    mutate: Callable[[dict[str, Any]], dict[str, Any]],
) -> None:
    name = _unique_name("invalid")
    request_id = endpoint_client.new_request_id()

    response = endpoint_client.post(SOURCES, json=mutate(_definition(name)), request_id=request_id)

    if response.status_code == 201:
        created_sources.append(response.json()["source"]["id"])
    expect_problem(response, status=422, code="invalid_request", request_id=request_id)
    validate_contract(response.json(), PROBLEM)
    assert _listed(endpoint_client, validate_contract, name) == []


def test_non_json_body_is_rejected(endpoint_client: EndpointClient) -> None:
    request_id = endpoint_client.new_request_id()
    response = endpoint_client.post(
        SOURCES,
        content=b"name=not-json",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        request_id=request_id,
    )

    problem = expect_problem(response, status=422, code="invalid_request", request_id=request_id)
    assert problem.detail == "request body must be a JSON object"


def test_duplicate_name_conflicts_and_keeps_the_original(
    endpoint_client: EndpointClient,
    validate_contract: ContractValidator,
    created_sources: list[str],
) -> None:
    definition = _definition(_unique_name("duplicate"))
    original = expect_json(endpoint_client.post(SOURCES, json=definition), status=201)["source"]
    created_sources.append(original["id"])
    request_id = endpoint_client.new_request_id()

    response = endpoint_client.post(
        SOURCES, json={**definition, "publisher": "Another publisher"}, request_id=request_id
    )

    if response.status_code == 201:
        created_sources.append(response.json()["source"]["id"])
    expect_problem(response, status=409, code="conflict", request_id=request_id)
    listed = _listed(endpoint_client, validate_contract, definition["name"])
    assert [(item["id"], item["publisher"]) for item in listed] == [
        (original["id"], definition["publisher"])
    ]
