"""Focused tests for bounded public evidence and shared AI-mode adapters."""

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


def suburb_context(locality: str) -> dict[str, Any]:
    return {
        "locality": locality,
        "population": [],
        "schools": [],
        "crime": [
            {
                "state": "NSW",
                "geography_kind": "suburb",
                "geography_value": locality,
                "provenance": {"release_id": "crime-release"},
                "observed_months": ["2025-01-01"],
                "observations": [],
                "blank_means_observed_zero": False,
            }
        ],
        "sources": [
            {
                "dataset_id": "bocsar-crime",
                "release_id": "crime-release",
                "publisher": "BOCSAR",
                "temporal_coverage": {"from": "2025-01-01"},
                "known_limitations": ["Partial source coverage"],
            }
        ],
        "limitations": ["Exact locality names only"],
    }


class SuburbTransport:
    def __init__(self, payload: dict[str, Any] | None = None, status: int = 200) -> None:
        self.payload = payload
        self.status = status
        self.localities: list[str] = []
        self.base = FakeTransport()

    def request(self, method: str, url: str, **kwargs: Any) -> ClientResponse:
        from urllib.parse import parse_qs, urlsplit

        if "/published/context?" in url:
            assert method == "GET"
            assert "Token" not in str(kwargs["headers"])
            locality = parse_qs(urlsplit(url).query)["locality"][0]
            self.localities.append(locality)
            return response(
                self.status, self.payload if self.payload is not None else suburb_context(locality)
            )
        return self.base.request(method, url, **kwargs)


def test_suburb_context_is_exact_bounded_and_not_substituted() -> None:
    transport = SuburbTransport()
    result = PublicEvidenceClient(
        "http://f1", "http://f2", "http://f4", transport=transport
    ).collect(
        [PROPERTY],
        request_id="suburbs",
        target_suburbs=[{"state": "NSW", "locality": "  Wollongong  "}],
    )
    section = result["sections"]["feature_3"]
    assert transport.localities == ["WOLLONGONG", "MASCOT"]
    assert section["state"] == "partial"
    target, property_item = section["items"]
    assert target["context_kind"] == "case_target" and "property_ref" not in target
    assert property_item["context_kind"] == "verified_property_location"
    assert property_item["property_ref"] == PROPERTY
    assert property_item["evidence"]["crime"] == suburb_context("MASCOT")["crime"]
    assert property_item["evidence"]["sources"] == suburb_context("MASCOT")["sources"]


def test_suburb_locality_deduplication_and_request_limit() -> None:
    transport = SuburbTransport()
    client = PublicEvidenceClient("http://f1", "http://f2", "http://f4", transport=transport)
    client.collect(
        [PROPERTY], request_id="dedup", target_suburbs=[{"state": "NSW", "locality": "Mascot"}]
    )
    assert transport.localities == ["MASCOT"]
    transport.localities.clear()
    result = client.collect(
        [PROPERTY],
        request_id="bounded",
        target_suburbs=[{"state": "NSW", "locality": f"AREA {i}"} for i in range(20)],
    )
    assert len(transport.localities) == 10
    assert result["sections"]["feature_3"]["items"][-1]["state"] == "partial"
    assert "limit" in result["sections"]["feature_3"]["items"][-1]["limitations"][0]


@pytest.mark.parametrize(
    "invalid", ["mismatch", "postcode", "provenance", "array", "missing", "outage", "empty"]
)
def test_suburb_invalid_or_missing_evidence_never_becomes_complete(invalid: str) -> None:
    payload = suburb_context("MASCOT")
    status = 200
    if invalid == "mismatch":
        payload["locality"] = "SYDNEY"
    if invalid == "postcode":
        payload["crime"][0]["geography_kind"] = "postcode"
    if invalid == "provenance":
        payload["crime"][0]["provenance"]["release_id"] = "other"
    if invalid == "array":
        payload["crime"] = "invalid"
    if invalid == "missing":
        del payload["sources"]
    if invalid == "outage":
        status = 503
    if invalid == "empty":
        payload.update(crime=[], sources=[])
    transport = SuburbTransport(payload, status)
    result = PublicEvidenceClient(
        "http://f1", "http://f2", "http://f4", transport=transport
    ).collect([PROPERTY], request_id="invalid")
    assert result["sections"]["feature_3"]["state"] == "unavailable"


def test_suburb_ambiguity_and_truncation_remain_explicit() -> None:
    from propertyscope_buyer_workspaces.suburb_evidence import project_context

    value = suburb_context("MASCOT")
    value["crime"] *= 30
    projected = project_context(value, "MASCOT")
    assert len(projected["evidence"]["crime"]) == 25
    assert any("25" in item for item in projected["limitations"])
    value["sources"].append({"dataset_id": "abs-seifa-2021", "release_id": "population"})
    value["population"] = [
        {"state": "NSW", "locality_name": "MASCOT", "provenance": {"release_id": "population"}}
    ] * 2
    assert project_context(value, "MASCOT")["state"] == "needs_verification"


@pytest.mark.parametrize(
    "kind",
    [
        "wrong_property",
        "partial_coverage",
        "unavailable",
        "excluded_sales",
        "fixture",
        "missing_category",
    ],
)
def test_other_adapters_do_not_promote_partial_or_invalid_evidence(kind: str) -> None:
    class Changed(FakeTransport):
        def request(self, method: str, url: str, **kwargs: Any) -> ClientResponse:
            original = super().request(method, url, **kwargs)
            value = original.json()
            assert isinstance(value, dict)
            if "report-section" in url and kind == "fixture":
                value["release_evidence"][0]["coverage_scope"]["synthetic"] = True
            if "/site-reviews/" in url:
                if kind == "wrong_property":
                    value["site_review"]["property_ref"] = "wrong"
                elif kind in ("partial_coverage", "unavailable"):
                    value["constraints"] = [{"property_ref": PROPERTY, "evidence_state": kind}]
                elif kind == "missing_category":
                    value["constraints"] = [
                        {"property_ref": PROPERTY, "evidence_state": "confirmed"}
                    ]
                    value["buildings"] = []
            if "/market-cases/" in url and kind == "excluded_sales":
                value["summary"]["excluded_sale_count"] = 1
            return response(original.status_code, value)

    result = PublicEvidenceClient(
        "http://f1", "http://f2", "http://f4", transport=Changed()
    ).collect([PROPERTY], request_id="audit")
    feature = (
        "feature_1"
        if kind == "fixture"
        else "feature_2"
        if kind == "excluded_sales"
        else "feature_4"
    )
    assert result["sections"][feature]["state"] != "complete"


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
                    "identity": {
                        "resolution_status": "verified",
                        "state": "NSW",
                        "locality": "MASCOT",
                    },
                    "release_evidence": [
                        {
                            "dataset_release_id": "release-1",
                            "coverage_status": "supported",
                            "coverage_scope": {"complete": True},
                        }
                    ],
                },
            )
        if url.endswith("/market-cases"):
            assert params == {"limit": 25}
            return response(200, {"items": [{"id": PROPERTY, "property_ref": PROPERTY}]})
        if "/market-cases/" in url and url.endswith("/evidence"):
            return response(
                200,
                {
                    "market_case": {"id": PROPERTY, "property_ref": PROPERTY},
                    "summary": {
                        "eligible_sale_count": 3,
                        "excluded_sale_count": 0,
                        "limitations": [],
                    },
                    "sales": [{"id": str(i), "property_ref": PROPERTY} for i in range(3)],
                },
            )
        if url.endswith("/site-reviews"):
            assert params == {"limit": 25}
            return response(200, {"items": [{"id": PROPERTY, "property_ref": PROPERTY}]})
        if "/site-reviews/" in url and url.endswith("/evidence"):
            return response(
                200,
                {
                    "site_review": {"id": PROPERTY, "property_ref": PROPERTY},
                    "constraints": [],
                    "buildings": [],
                },
            )
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


def test_ai_read_events_and_cancel_preserve_host_auth_and_correlation() -> None:
    transport = FakeTransport()
    client = AiModeClient("http://127.0.0.1:5005", transport=transport, service_token="test-token")
    client.get_run("run-1", request_id="read-1")
    client.get_events("run-1", after=7, request_id="events-1")
    client.cancel_run("run-1", request_id="cancel-1")
    assert [call[0] for call in transport.calls] == ["GET", "GET", "POST"]
    assert transport.calls[1][1].endswith("/run-1/events?after=7&limit=100")
    assert transport.calls[2][1].endswith("/run-1/cancel")
    assert [call[2]["X-Request-ID"] for call in transport.calls] == [
        "read-1",
        "events-1",
        "cancel-1",
    ]
    assert all(call[2]["X-PropertyScope-AI-Token"] == "test-token" for call in transport.calls)
    assert all("X-PropertyScope-Internal-Token" not in call[2] for call in transport.calls)


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
