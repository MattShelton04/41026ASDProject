"""Database API contract tests."""

from __future__ import annotations

from pathlib import Path

from flask.testing import FlaskClient

from propertyscope_market_store.app import create_app
from propertyscope_market_store.configuration import StoreSettings


def _app(tmp_path: Path) -> FlaskClient:
    return create_app(
        StoreSettings(tmp_path / "database.sqlite3", "test-token"),
    ).test_client()


def test_internal_routes_require_token(tmp_path: Path) -> None:
    response = _app(tmp_path).get("/internal/market-intelligence/v1/market-cases")
    assert response.status_code == 401
    assert response.content_type == "application/problem+json"


def test_database_health_and_seed_report(tmp_path: Path) -> None:
    client = _app(tmp_path)
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200
    response = client.get(
        "/internal/market-intelligence/v1/seed-report",
        headers={"X-PropertyScope-Internal-Token": "test-token"},
    )
    assert response.get_json()["tables"] == {"market_case": 10, "sale_observation": 26}


def test_database_api_crud_validation(tmp_path: Path) -> None:
    client = _app(tmp_path)
    headers = {"X-PropertyScope-Internal-Token": "test-token"}
    collection = "/internal/market-intelligence/v1/market-cases"
    assert len(client.get(collection, headers=headers).get_json()["items"]) == 10
    invalid = client.post(collection, json={}, headers=headers)
    assert invalid.status_code == 422
    created = client.post(
        collection,
        json={
            "name": "HTTP case",
            "property_ref": "11111111-1111-4111-8111-111111111111",
            "address_display": "11 Example Street",
            "date_from": "2024-01-01",
            "date_to": "2025-12-31",
            "status": "draft",
            "notes": "",
            "filters": {},
            "property_validation_state": "verified",
        },
        headers=headers,
    )
    assert created.status_code == 201
    item = created.get_json()
    path = f"{collection}/{item['id']}"
    assert (
        client.put(path, json={"version": 1, "status": "active"}, headers=headers).get_json()[
            "version"
        ]
        == 2
    )
    assert (
        client.put(path, json={"version": 1, "status": "complete"}, headers=headers).status_code
        == 409
    )
    assert client.delete(path, headers=headers).status_code == 200
    assert client.get(path, headers=headers).status_code == 404


def test_database_sales_query_requires_uuid(tmp_path: Path) -> None:
    response = _app(tmp_path).get(
        "/internal/market-intelligence/v1/sales?property_ref=nope",
        headers={"X-PropertyScope-Internal-Token": "test-token"},
    )
    assert response.status_code == 422
