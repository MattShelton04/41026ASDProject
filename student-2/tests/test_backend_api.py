"""Public API, tool and AI-boundary tests."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
from flask.testing import FlaskClient

from propertyscope_market_intelligence.app import create_app as create_backend
from propertyscope_market_store.app import create_app as create_database
from propertyscope_market_store.configuration import StoreSettings


class LocalStoreClient:
    def __init__(self, tmp_path: Path) -> None:
        self._client = create_database(
            StoreSettings(tmp_path / "local.sqlite3", "local-token")
        ).test_client()

    def ready(self) -> bool:
        return self._client.get("/health/ready").status_code == 200

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Any = None,
        json: Any = None,
    ) -> httpx.Response:
        response = self._client.open(
            path,
            method=method,
            query_string=params,
            json=json,
            headers={"X-PropertyScope-Internal-Token": "local-token"},
        )
        return httpx.Response(
            response.status_code,
            content=response.data,
            headers={"content-type": response.content_type},
        )


class FakeFeature1:
    def __init__(self, state: str = "verified", artifact: bytes = b"") -> None:
        self.state = state
        self._artifact = artifact

    def validate_property(self, _property_ref: str) -> str:
        return self.state

    def artifact(self, _path: str) -> bytes:
        return self._artifact


class FakeAiMode:
    def __init__(self) -> None:
        self.payload: dict[str, Any] | None = None

    def create_run(self, payload: dict[str, Any]) -> httpx.Response:
        self.payload = payload
        return httpx.Response(
            202, json={"id": "90000000-0000-4000-8000-000000000001", "status": "queued"}
        )

    def get(self, _path: str, *, params: Any = None) -> httpx.Response:
        del params
        return httpx.Response(
            200,
            json={
                "run": {
                    "id": "90000000-0000-4000-8000-000000000001",
                    "feature_key": "student-2-market-intelligence",
                    "tool_allowlist": ["market.cases.inspect.v1", "market.sales.summary.v1"],
                    "status": "succeeded",
                    "final_result": {"summary": "Evidence explained."},
                }
            },
        )

    def cancel(self, _run_id: str) -> httpx.Response:
        return httpx.Response(202, json={"status": "cancelling"})


def _client(
    tmp_path: Path, feature1: FakeFeature1 | None = None, ai: FakeAiMode | None = None
) -> FlaskClient:
    return create_backend(
        store=LocalStoreClient(tmp_path),
        feature1=feature1 or FakeFeature1(),
        ai_mode=ai or FakeAiMode(),
    ).test_client()


def test_public_case_evidence_and_tools(tmp_path: Path) -> None:
    client = _client(tmp_path)
    case_id = "60000000-0000-4000-8000-000000000001"
    assert len(client.get("/api/market-intelligence/v1/market-cases").get_json()["items"]) == 10
    evidence = client.get(f"/api/market-intelligence/v1/market-cases/{case_id}/evidence")
    assert evidence.status_code == 200
    assert evidence.get_json()["summary"]["eligible_sale_count"] == 10
    case_tool = client.post(
        "/api/market-intelligence/v1/tools/market.cases.inspect.v1",
        json={"market_case_id": case_id},
    )
    agent_case = case_tool.get_json()["market_case"]
    assert agent_case["name"].startswith("Sydney example")
    assert agent_case["address_display"] == "11 Example Street, Sydney NSW 2000"
    assert "id" not in agent_case
    assert "property_ref" not in agent_case
    summary_tool = client.post(
        "/api/market-intelligence/v1/tools/market.sales.summary.v1",
        json={"market_case_id": case_id},
    )
    agent_evidence = summary_tool.get_json()
    assert agent_evidence["summary"]["median_price_aud"] == 992500
    assert agent_evidence["summary"]["source_release_count"] == 1
    assert "source_release_ids" not in agent_evidence["summary"]
    assert all("property_ref" not in sale for sale in agent_evidence["sales"])
    assert all("release_id" not in sale for sale in agent_evidence["sales"])


def test_public_crud_validates_feature_1(tmp_path: Path) -> None:
    payload = {
        "name": "Created case",
        "property_ref": "11111111-1111-4111-8111-111111111111",
        "address_display": "11 Example Street",
        "date_from": "2024-01-01",
        "date_to": "2025-12-31",
    }
    assert (
        _client(tmp_path, FakeFeature1("not_found"))
        .post("/api/market-intelligence/v1/market-cases", json=payload)
        .status_code
        == 422
    )
    client = _client(tmp_path, FakeFeature1("unavailable"))
    created = client.post("/api/market-intelligence/v1/market-cases", json=payload)
    assert created.status_code == 201
    item = created.get_json()
    assert item["property_validation_state"] == "unavailable"
    updated = client.put(
        f"/api/market-intelligence/v1/market-cases/{item['id']}",
        json={"version": 1, "status": "active"},
    )
    assert updated.get_json()["status"] == "active"
    assert (
        client.delete(f"/api/market-intelligence/v1/market-cases/{item['id']}").status_code == 200
    )


def test_assistant_run_is_bounded_and_owned(tmp_path: Path) -> None:
    ai = FakeAiMode()
    client = _client(tmp_path, ai=ai)
    case_id = "60000000-0000-4000-8000-000000000001"
    created = client.post(
        "/api/market-intelligence/v1/assistant/turns",
        json={"case_id": case_id, "message": "Explain this case"},
    )
    assert created.status_code == 202
    assert ai.payload is not None
    assert ai.payload["tool_allowlist"] == ["market.cases.inspect.v1", "market.sales.summary.v1"]
    assert ai.payload["limits"]["max_iterations"] == 4
    assert case_id not in ai.payload["objective"]
    assert "Never display UUIDs" in ai.payload["objective"]
    assert "Refer to the case by its name" in ai.payload["objective"]
    run_id = created.get_json()["id"]
    assert client.get(f"/api/market-intelligence/v1/assistant/turns/{run_id}").status_code == 200
    assert (
        client.post(f"/api/market-intelligence/v1/assistant/turns/{run_id}/cancel").status_code
        == 202
    )


def test_sales_publication_import_receipt(tmp_path: Path) -> None:
    release_id = "70000000-0000-4000-8000-000000000001"
    record = {
        "source_business_key": "published:1",
        "source_revision": 1,
        "source_era": "post-2001",
        "property_ref": "11111111-1111-4111-8111-111111111111",
        "contract_date": "2026-04-01",
        "price_aud": 1200000,
        "house_number": "11",
        "street_name": "EXAMPLE",
        "street_type": "STREET",
        "locality": "SYDNEY",
        "postcode": "2000",
        "match_tier": "A",
        "match_confidence": "1.0000",
        "geographic_precision": "exact_address",
        "provenance": {
            "release_id": release_id,
            "release_version": "published-r1",
            "candidate_generation_id": release_id,
            "source_record_sha256": "b" * 64,
            "normalisation_version": "1.0.0",
        },
    }
    compressed = gzip.compress((json.dumps(record) + "\n").encode())
    digest = hashlib.sha256(compressed).hexdigest()
    payload = {
        "release_id": release_id,
        "dataset_id": "nsw-psi-sales",
        "schema_version": "propertyscope.property-sales.v3",
        "content_sha256": digest,
        "record_count": 1,
        "manifest": {
            "product_schema_version": "propertyscope.property-sales.v3",
            "release_id": release_id,
            "dataset_id": "nsw-psi-sales",
            "target_feature": "feature-2",
            "record_count": 1,
            "content_sha256": digest,
            "content_encoding": "gzip",
            "source": "Synthetic test fixture",
        },
        "artifact_path": f"/api/data-platform/v1/dataset-releases/{release_id}/artifact",
        "idempotency_key": "feature-2-publication-test",
    }
    response = _client(tmp_path, FakeFeature1(artifact=compressed)).post(
        "/api/data-import/v1/propertyscope-releases", json=payload
    )
    assert response.status_code == 200
    assert response.get_json()["status"] == "accepted"
    assert response.get_json()["rows_accepted"] == 1
