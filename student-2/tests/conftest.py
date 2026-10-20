"""Feature 2 test fixtures.

The endpoint fixtures are re-exported here rather than from ``tests/endpoints/conftest.py``:
``scripts/check.py`` type-checks every student's tests in one strict mypy run with no
namespace-package configuration, so a second ``conftest`` module under this slice collides with
this one, and an ``endpoints`` package collides with Feature 1's. Keeping them here means
``tests/endpoints/`` holds only test modules, whose names are already unique.

The shared plugin skips every ``endpoint`` test unless ``PROPERTYSCOPE_ENDPOINT_BASE_URL`` is
set, so the default quality gate never needs Docker.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from propertyscope_market_store.repository import MarketStore
from shared_testkit.endpoints import EndpointClient
from shared_testkit.pytest_endpoints import (
    endpoint_client,
    endpoint_ready_path,
    pytest_collection_modifyitems,
)

__all__ = [
    "endpoint_client",
    "endpoint_ready_path",
    "market_store",
    "pytest_collection_modifyitems",
]

API = "/api/market-intelligence/v1"


@pytest.fixture
def market_store(tmp_path: Path) -> MarketStore:
    store = MarketStore(tmp_path / "market.sqlite3")
    store.initialize()
    return store


@pytest.fixture
def created_cases(endpoint_client: EndpointClient) -> Iterator[list[str]]:
    """Track market cases a test creates and delete any it leaves behind.

    Endpoint tests run against a shared, long-lived Compose stack, so a test that leaves rows
    behind changes what the next run sees: ``student-2.yml`` asserts on the seeded case count.
    """
    created: list[str] = []
    yield created
    for case_id in created:
        response = endpoint_client.delete(f"{API}/market-cases/{case_id}")
        if response.status_code not in {200, 204, 404}:
            raise AssertionError(
                f"could not clean up market case {case_id}: "
                f"HTTP {response.status_code} {response.text[:300]}"
            )
