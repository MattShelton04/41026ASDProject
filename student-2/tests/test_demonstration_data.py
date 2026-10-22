"""The seeded showcase must not survive in a production database.

Feature 1 publishes only real reviewed releases to the Azure deployment. Importing one sets the
accepted generation pointer, after which ``list_sales`` reads that release alone: the seeded sale
rows remain in the table but stop being consulted, so every seeded case resolves to zero eligible
sales, no exclusions and no source releases. A case that looks broken is worse than no case, so a
production database starts empty instead.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from propertyscope_market_store.configuration import StoreSettings
from propertyscope_market_store.repository import MarketStore

FIXTURE_PROPERTY = "a0000000-0000-0000-0000-000000000001"
SEEDED_CASES = 10
SEEDED_SALES = 26


def _store(tmp_path: Path, *, demonstration_data: bool) -> MarketStore:
    store = MarketStore(tmp_path / "market.sqlite3")
    store.initialize(demonstration_data=demonstration_data)
    return store


def test_the_showcase_is_seeded_by_default(tmp_path: Path) -> None:
    """Local stacks, CI and the tests all rely on the seeded baseline."""
    store = _store(tmp_path, demonstration_data=True)
    counts = store.table_counts()
    assert counts["market_case"] == SEEDED_CASES
    assert counts["sale_observation"] == SEEDED_SALES
    assert len(store.list_sales(FIXTURE_PROPERTY)) == 12


def test_a_production_database_starts_empty(tmp_path: Path) -> None:
    store = _store(tmp_path, demonstration_data=False)
    counts = store.table_counts()
    assert counts["market_case"] == 0
    assert counts["sale_observation"] == 0
    assert store.list_sales(FIXTURE_PROPERTY) == []


def test_the_purge_is_idempotent_across_restarts(tmp_path: Path) -> None:
    """It runs after every migration pass, so a second start must not fail or differ."""
    store = _store(tmp_path, demonstration_data=False)
    store.initialize(demonstration_data=False)
    assert store.table_counts() == {"market_case": 0, "sale_observation": 0}


def test_a_database_seeded_before_the_setting_existed_is_cleaned(tmp_path: Path) -> None:
    """The Azure database already holds the seed; it is purged on the next start."""
    store = _store(tmp_path, demonstration_data=True)
    assert store.table_counts()["market_case"] == SEEDED_CASES
    store.initialize(demonstration_data=False)
    assert store.table_counts() == {"market_case": 0, "sale_observation": 0}


def test_real_rows_and_imported_generations_are_left_alone(tmp_path: Path) -> None:
    """Only the seed identifiers are removed, so the purge is safe beside real data."""
    store = _store(tmp_path, demonstration_data=True)
    case = store.create_case(
        {
            "name": "Real case",
            "property_ref": "99999999-9999-4999-8999-999999999999",
            "address_display": "1 Real Street, Sydney NSW 2000",
            "date_from": "2024-01-01",
            "date_to": "2025-12-31",
            "status": "draft",
            "notes": "Kept beside the purge.",
            "filters": {"minimum_match_tier": "B"},
            "property_validation_state": "verified",
        }
    )
    with sqlite3.connect(store._path) as connection:
        connection.execute("INSERT INTO sales_import_generation VALUES ('real-r1','deadbeef',1,1)")
        connection.execute(
            "INSERT INTO sale_generation_record (release_id,ordinal,source_business_key,"
            "source_revision,property_ref,contract_date,record_sha256,record_json) "
            "VALUES ('real-r1',1,'psi:1',1,'99999999-9999-4999-8999-999999999999',"
            "'2024-06-01','x','{}')"
        )
        connection.commit()

    store.initialize(demonstration_data=False)

    assert store.get_case(case["id"]) is not None
    assert store.table_counts()["market_case"] == 1
    with sqlite3.connect(store._path) as connection:
        generations = connection.execute("SELECT COUNT(*) FROM sales_import_generation").fetchone()
        records = connection.execute("SELECT COUNT(*) FROM sale_generation_record").fetchone()
    assert generations[0] == 1
    assert records[0] == 1


def test_the_setting_defaults_to_true_and_reads_the_environment(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("PROPERTYSCOPE_DEMONSTRATION_DATA", raising=False)
    assert StoreSettings.from_environment().demonstration_data is True
    for value, expected in (("false", False), ("FALSE", False), ("0", False), ("true", True)):
        monkeypatch.setenv("PROPERTYSCOPE_DEMONSTRATION_DATA", value)
        assert StoreSettings.from_environment().demonstration_data is expected
