"""Shared isolated fixtures for the Student 5 database package."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from flask.testing import FlaskClient

from propertyscope_buyer_store.app import create_app
from propertyscope_buyer_store.configuration import StoreSettings
from propertyscope_buyer_store.repository import BuyerStore
from shared_testkit.endpoints import EndpointClient
from shared_testkit.pytest_endpoints import (
    endpoint_client,
    endpoint_ready_path,
    pytest_collection_modifyitems,
)

__all__ = ["endpoint_client", "endpoint_ready_path", "pytest_collection_modifyitems"]

OWNER = "release0-demo-owner"
TOKEN = "phase-one-test-token"
HEADERS = {"X-PropertyScope-Internal-Token": TOKEN}


@pytest.fixture
def created_buyer_cases(endpoint_client: EndpointClient) -> Iterator[list[str]]:
    """Clean up only the cases created by an opt-in live endpoint test."""
    created: list[str] = []
    yield created
    for case_id in created:
        response = endpoint_client.delete(f"/api/buyer-workspaces/v1/buyer-cases/{case_id}")
        assert response.status_code in {200, 204, 404}, (
            f"Could not clean up endpoint test case: HTTP {response.status_code}"
        )


@pytest.fixture
def store(tmp_path: Path) -> BuyerStore:
    identifiers: Iterator[str] = (
        f"f5000000-0000-4000-8000-{sequence:012d}" for sequence in range(1, 100)
    )
    value = BuyerStore(
        tmp_path / "buyer-workspaces.sqlite3",
        clock=lambda: "2026-09-03T10:00:00Z",
        id_factory=lambda: next(identifiers),
    )
    value.initialize()
    return value


@pytest.fixture
def client(store: BuyerStore) -> FlaskClient:
    settings = StoreSettings(
        database_path=Path("unused.sqlite3"),
        internal_token=TOKEN,
        demo_owner_ref=OWNER,
        auto_migrate=False,
    )
    app = create_app(settings, store=store)
    app.config.update(TESTING=True)
    return app.test_client()
