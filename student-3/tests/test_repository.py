from __future__ import annotations

from pathlib import Path

import pytest
from propertyscope_suburb_store.repository import Repository


@pytest.fixture
def repository(tmp_path: Path) -> Repository:
    store = Repository(tmp_path / "suburbs.sqlite3")
    store.initialise()
    return store


def test_seeded_tables_meet_assessed_minimum(repository: Repository) -> None:
    assert all(count >= 10 for count in repository.table_counts().values())
    assert repository.table_counts()["suburb_indicators"] == 400


def test_zero_and_missing_semantics_are_explicit(repository: Repository) -> None:
    items = repository.series("NSW", "Parramatta", "rate", "2026-01", "2026-06")
    assert len(items) == 6
    assert all(item["zero_missing_state"] in {"observed", "recorded_zero"} for item in items)
    assert all(item["measure_source"] == "calculated_fixture_rate" for item in items)
    missing_items = repository.series("NSW", "Manly", "count", "2026-01", "2026-06")
    assert any(
        item["value"] is None and item["zero_missing_state"] == "missing" for item in missing_items
    )


def test_area_metrics_and_nearby_places_are_queryable(repository: Repository) -> None:
    metrics = repository.area_series("NSW", "Parramatta", "population_density")
    assert metrics and metrics[0]["unit"] == "people per km²"
    suburb = repository.suburb("NSW", "Parramatta")
    assert suburb is not None
    places = repository.nearby_places(suburb["latitude"], suburb["longitude"], 2_000)
    assert places
    assert all(place["distance_m"] <= 2_000 for place in places)


def test_comparison_crud_uses_optimistic_versions(repository: Repository) -> None:
    payload = {
        "name": "Inner west comparison",
        "localities": ["Newtown", "Surry Hills"],
        "from_month": "2026-01",
        "to_month": "2026-06",
        "measure": "count",
        "selected_indicators": ["recorded_offences"],
        "priorities": ["transport"],
        "notes": "Fixture research scope",
        "status": "saved",
    }
    created = repository.create_comparison(payload)
    assert created["version"] == 1
    updated = repository.update_comparison(
        created["id"], payload | {"version": 1, "notes": "Reviewed"}
    )
    assert updated and updated["version"] == 2 and updated["notes"] == "Reviewed"
    with pytest.raises(ValueError, match="version_conflict"):
        repository.update_comparison(created["id"], payload | {"version": 1})
    assert repository.delete_comparison(created["id"])
    assert repository.comparison(created["id"]) is None
