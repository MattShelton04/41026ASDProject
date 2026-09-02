"""Feature 2 test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from propertyscope_market_store.repository import MarketStore


@pytest.fixture
def market_store(tmp_path: Path) -> MarketStore:
    store = MarketStore(tmp_path / "market.sqlite3")
    store.initialize()
    return store
