"""Deterministic tests for the injected database HTTP client."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import pytest

from propertyscope_buyer_workspaces.clients import (
    BuyerStoreClient,
    ClientResponse,
    DatabaseProtocolError,
    DatabaseUnavailableError,
)


class RecordingTransport:
    def __init__(
        self,
        response: ClientResponse | None = None,
        *,
        error: DatabaseUnavailableError | None = None,
    ) -> None:
        self.response = response or response_json(200, {})
        self.error = error
        self.calls: list[dict[str, object]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        params: Mapping[str, int] | None,
        json_body: Mapping[str, Any] | None,
        timeout_seconds: float,
    ) -> ClientResponse:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "params": params,
                "json_body": json_body,
                "timeout_seconds": timeout_seconds,
            }
        )
        if self.error is not None:
            raise self.error
        return self.response


def response_json(status: int, payload: object) -> ClientResponse:
    return ClientResponse(
        status_code=status,
        body=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )


def test_internal_request_forwards_token_and_request_id() -> None:
    transport = RecordingTransport(response_json(200, {"items": []}))
    client = BuyerStoreClient("http://buyer-db:5502/", "internal-secret", transport=transport)
    response = client.list_cases(page=2, page_size=25, request_id="request-42")
    call = transport.calls[0]
    assert response.json() == {"items": []}
    assert call["url"] == "http://buyer-db:5502/internal/buyer-workspaces/v1/buyer-cases"
    assert call["params"] == {"page": 2, "page_size": 25}
    assert call["headers"] == {
        "X-PropertyScope-Internal-Token": "internal-secret",
        "X-Request-ID": "request-42",
    }


def test_crud_methods_use_only_internal_database_routes() -> None:
    transport = RecordingTransport()
    client = BuyerStoreClient("http://buyer-db", "secret", transport=transport)
    case_id = "b5000000-0000-4000-8000-000000000001"
    client.create_case({"name": "Case"}, request_id="r1")
    client.get_case(case_id, request_id="r2")
    client.update_case(case_id, {"version": 1, "status": "paused"}, request_id="r3")
    client.delete_case(case_id, request_id="r4")
    assert [call["method"] for call in transport.calls] == ["POST", "GET", "PUT", "DELETE"]
    assert all(
        "/internal/buyer-workspaces/v1/buyer-cases" in str(call["url"]) for call in transport.calls
    )


def test_child_crud_methods_use_scoped_internal_routes() -> None:
    transport = RecordingTransport()
    client = BuyerStoreClient("http://buyer-db", "secret", transport=transport)
    case_id = "b5000000-0000-4000-8000-000000000001"
    child_id = "b5000000-0000-4000-8000-000000000002"
    client.list_children(case_id, "properties", page=1, page_size=50, request_id="r1")
    client.create_child(case_id, "notes", {"content": "Note"}, request_id="r2")
    client.get_child(case_id, "tasks", child_id, request_id="r3")
    client.update_child(
        case_id, "tasks", child_id, {"version": 1, "completed": True}, request_id="r4"
    )
    client.delete_child(case_id, "properties", child_id, request_id="r5")
    assert [call["method"] for call in transport.calls] == ["GET", "POST", "GET", "PUT", "DELETE"]
    assert str(transport.calls[0]["url"]).endswith(f"/{case_id}/properties")
    assert str(transport.calls[3]["url"]).endswith(f"/{case_id}/tasks/{child_id}")


def test_readiness_does_not_send_internal_credentials() -> None:
    transport = RecordingTransport(response_json(200, {"status": "healthy"}))
    client = BuyerStoreClient("http://buyer-db", "secret", transport=transport)
    assert client.ready() is True
    assert transport.calls[0]["url"] == "http://buyer-db/health/ready"
    assert transport.calls[0]["headers"] == {}


def test_transport_failure_is_safe_and_readiness_becomes_false() -> None:
    transport = RecordingTransport(error=DatabaseUnavailableError("down"))
    client = BuyerStoreClient("http://buyer-db", "secret", transport=transport)
    with pytest.raises(DatabaseUnavailableError):
        client.get_case("case-id", request_id="r")
    assert client.ready() is False


def test_invalid_json_is_reported_as_protocol_failure() -> None:
    response = ClientResponse(200, b"not-json", {})
    with pytest.raises(DatabaseProtocolError):
        response.json()
