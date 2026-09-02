"""Feature-owned SQLite repository tests."""

from __future__ import annotations

from typing import Any

import pytest

from propertyscope_market_store.repository import MarketStore, VersionConflictError


def test_seed_has_required_domain_rows(market_store: MarketStore) -> None:
    assert market_store.table_counts() == {"market_case": 10, "sale_observation": 26}
    assert market_store.ready() is True


def test_market_case_crud_and_version_conflict(market_store: MarketStore) -> None:
    created = market_store.create_case(
        {
            "name": "Test case",
            "property_ref": "11111111-1111-4111-8111-111111111111",
            "address_display": "11 Example Street",
            "date_from": "2024-01-01",
            "date_to": "2025-12-31",
            "status": "draft",
            "notes": "Created in a deterministic test",
            "filters": {"minimum_match_tier": "B"},
            "property_validation_state": "verified",
        }
    )
    fetched = market_store.get_case(created["id"])
    assert fetched is not None
    assert fetched["filters"]["minimum_match_tier"] == "B"
    updated = market_store.update_case(created["id"], {"status": "active"}, expected_version=1)
    assert updated is not None and updated["status"] == "active" and updated["version"] == 2
    with pytest.raises(VersionConflictError):
        market_store.update_case(created["id"], {"status": "complete"}, expected_version=1)
    assert market_store.delete_case(created["id"]) is True
    assert market_store.get_case(created["id"]) is None


def test_import_is_idempotent(market_store: MarketStore) -> None:
    record: dict[str, Any] = {
        "source_business_key": "test:import:1",
        "source_revision": 1,
        "source_era": "post-2001",
        "property_ref": "a0000000-0000-0000-0000-000000000001",
        "address_display": "11 Example Street, Sydney NSW 2000",
        "contract_date": "2026-03-01",
        "settlement_date": None,
        "price_aud": 1_200_000,
        "area_square_metres": 500.0,
        "locality": "SYDNEY",
        "postcode": "2000",
        "sale_code": None,
        "interest_of_sale": None,
        "match_tier": "A",
        "match_confidence": 1.0,
        "geographic_precision": "exact_address",
        "release_id": "70000000-0000-4000-8000-000000000001",
        "release_version": "test-r1",
        "source_record_sha256": "a" * 64,
        "normalisation_version": "1.0.0",
        "synthetic": True,
    }
    assert market_store.import_sales([record]) == {"received": 1, "inserted": 1, "replayed": 0}
    assert market_store.import_sales([record]) == {"received": 1, "inserted": 0, "replayed": 1}
    assert len(market_store.list_sales(record["property_ref"])) == 13
