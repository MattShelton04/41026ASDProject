"""Focused tests for bounded Feature 1/2/4 and shared AI-mode adapters."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import pytest
from propertyscope_buyer_workspaces.clients import ClientResponse, UrllibTransport
from propertyscope_buyer_workspaces.integrations import (
    AiModeClient,
    IntegrationUnavailableError,
    PublicEvidenceClient,
)

PROPERTY = "a0000000-0000-0000-0000-000000000001"


def response(status: int, value: object) -> ClientResponse:
    return ClientResponse(status, json.dumps(value).encode(), {})


class FakeTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Mapping[str, str], Mapping[str, Any] | None]] = []

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
        self.calls.append((method, url, headers, json_body))
        if "report-section" in url:
            return response(
                200,
                {
                    "property_ref": PROPERTY,
                    "address_display": "1 Test Street, Mascot NSW 2020",
                    "identity": {"resolution_status": "verified", "state": "NSW"},
                    "release_evidence": [{"dataset_release_id": "release-1"}],
                },
            )
        if url.endswith("/market-cases"):
            return response(200, {"items": [{"id": "market-1", "property_ref": PROPERTY}]})
        if "/market-cases/market-1/evidence" in url:
            return response(200, {"market_case": {}, "summary": {}, "sales": [{"id": "sale-1"}]})
        if url.endswith("/site-reviews"):
            return response(200, {"items": [{"id": "review-1", "property_ref": PROPERTY}]})
        if "/site-reviews/review-1/evidence" in url:
            return response(200, {"site_review": {}, "constraints": [], "buildings": []})
        return response(404, {})


def test_evidence_collection_is_bounded_and_projects_feature_three_honestly() -> None:
    transport = FakeTransport()
    client = PublicEvidenceClient("http://f1", "http://f2", "http://f4", transport=transport)
    result = client.collect([PROPERTY] * 20, request_id="request-evidence-123")
    assert result["sections"]["feature_1"]["state"] == "complete"
    assert result["sections"]["feature_2"]["state"] == "complete"
    assert result["sections"]["feature_3"]["state"] == "unavailable"
    assert result["sections"]["feature_4"]["state"] == "partial"
    assert all(call[2]["X-Request-ID"] == "request-evidence-123" for call in transport.calls)


def test_property_validation_uses_feature_one_address_and_state() -> None:
    client = PublicEvidenceClient("http://f1", "http://f2", "http://f4", transport=FakeTransport())
    assert client.validate_property(PROPERTY, request_id="request-validation-1") == {
        "state": "validated",
        "label": "1 Test Street, Mascot NSW 2020",
    }


def test_conflicting_matches_are_explicit() -> None:
    class ConflictingTransport(FakeTransport):
        def request(self, method: str, url: str, **kwargs: Any) -> ClientResponse:
            if url.endswith("/market-cases"):
                return response(
                    200,
                    {
                        "items": [
                            {"id": "one", "property_ref": PROPERTY},
                            {"id": "two", "property_ref": PROPERTY},
                        ]
                    },
                )
            return super().request(method, url, **kwargs)

    client = PublicEvidenceClient(
        "http://f1", "http://f2", "http://f4", transport=ConflictingTransport()
    )
    result = client.collect([PROPERTY], request_id="request-conflict-1")
    assert result["sections"]["feature_2"]["state"] == "conflicting"


def test_ai_mode_client_forwards_only_correlation_and_idempotency() -> None:
    transport = FakeTransport()
    client = AiModeClient("http://shared-ai", transport=transport)
    client.create_run(
        {"feature_key": "student-5-buyer-journey"},
        request_id="request-ai-123",
        idempotency_key="summary-key-123",
    )
    _, url, headers, _ = transport.calls[-1]
    assert url == "http://shared-ai/api/v1/agent-runs"
    assert headers == {
        "X-Request-ID": "request-ai-123",
        "Idempotency-Key": "summary-key-123",
    }


def test_external_clients_reject_oversized_http_responses(monkeypatch: pytest.MonkeyPatch) -> None:
    class OversizedResponse:
        status = 200
        headers: Mapping[str, str] = {}

        def __enter__(self) -> OversizedResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, size: int = -1) -> bytes:
            assert size == 9
            return b"x" * 9

    monkeypatch.setattr(
        "propertyscope_buyer_workspaces.clients.urlopen",
        lambda request, timeout: OversizedResponse(),
    )
    bounded = UrllibTransport(max_response_bytes=8)
    evidence = PublicEvidenceClient("http://f1", "http://f2", "http://f4", transport=bounded)
    ai_mode = AiModeClient("http://ai", transport=bounded)
    with pytest.raises(IntegrationUnavailableError):
        evidence.validate_property(PROPERTY, request_id="bounded-evidence")
    with pytest.raises(IntegrationUnavailableError):
        ai_mode.create_run({}, request_id="bounded-ai", idempotency_key=None)
