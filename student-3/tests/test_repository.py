from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from propertyscope_suburb_store.repository import DEMO_AMENITIES, SUBURBS, Repository


@pytest.fixture
def repository(tmp_path: Path) -> Repository:
    store = Repository(tmp_path / "suburbs.sqlite3")
    store.initialise()
    return store


def test_seeded_tables_meet_assessed_minimum(repository: Repository) -> None:
    assert all(count >= 10 for count in repository.table_counts().values())
    assert repository.table_counts()["suburb_indicators"] == 400


def test_seeded_comparisons_are_loadable(repository: Repository) -> None:
    supported = {locality for _key, locality, *_rest in SUBURBS}
    comparisons = repository.comparisons()
    assert len(comparisons) == len(SUBURBS)
    assert all(len(item["localities"]) == 2 for item in comparisons)
    assert all(set(item["localities"]) <= supported for item in comparisons)
    assert {item["measure"] for item in comparisons} == {"count", "rate"}


def test_demo_amenity_filters_and_counts_are_distinct(repository: Repository) -> None:
    assert len(set(DEMO_AMENITIES.values())) == len(SUBURBS)
    for index, kind in enumerate(("school", "transport", "park")):
        expected = {key for key, counts in DEMO_AMENITIES.items() if counts[index]}
        items, total = repository.list_suburbs(amenity=kind)
        assert {item["id"] for item in items} == expected
        assert total == len(expected) < len(SUBURBS)
    for key, locality, *_rest in SUBURBS:
        school, transport, park = DEMO_AMENITIES[key]
        assert len(repository.places("NSW", locality)) == school + transport + park
        for metric, value in (
            ("amenity_observations", school + transport + park),
            ("school_observations", school),
            ("transport_observations", transport),
        ):
            record = repository.area_series("NSW", locality, metric)[0]
            assert record["value"] == value
            assert record["zero_missing_state"] == ("recorded_zero" if value == 0 else "observed")


def test_existing_demo_upgrade_preserves_other_records_and_is_repeatable(tmp_path: Path) -> None:
    from propertyscope_suburb_store.repository import SCHEMA

    store = Repository(tmp_path / "legacy.sqlite3")
    with store.connect() as connection:
        connection.executescript(SCHEMA)
        store._seed(connection)
        store._ensure_fixture_revision(connection)
        connection.execute(
            "INSERT INTO suburb_amenity VALUES "
            "('custom', 'burwood', 'park', 'Keep me', -33.8, 151.1, 'observed', 'custom')"
        )
        connection.execute(
            "UPDATE user_suburbs SET name='Surry Hills research', "
            "localities_json='[\"Surry Hills\"]', measure='rate', "
            "selected_indicators_json='[\"offence_rate\"]' WHERE id='comparison-1'"
        )
    custom = store.create_comparison(
        {
            "name": "Keep my comparison",
            "localities": ["Burwood", "Newtown"],
            "from_month": "2026-02",
            "to_month": "2026-05",
            "measure": "count",
            "notes": "User-created record",
        }
    )
    store.initialise()
    counts = store.table_counts()
    store.initialise()
    assert store.table_counts() == counts
    with store.connect() as connection:
        assert (
            connection.execute("SELECT name FROM suburb_amenity WHERE id='custom'").fetchone()[0]
            == "Keep me"
        )
    assert store.comparison(custom["id"]) == custom
    seeded = [item for item in store.comparisons() if item["id"].startswith("comparison-")]
    assert all(len(item["localities"]) == 2 for item in seeded)
    assert store.area_series("NSW", "Burwood", "amenity_observations")[0]["value"] == 2


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


def test_concurrent_update_reports_conflict_instead_of_success(
    repository: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = repository.comparison
    stale = original("comparison-1")
    assert stale is not None
    reads = 0

    def read_then_compete(comparison_id: str) -> dict[str, Any] | None:
        nonlocal reads
        reads += 1
        row = original(comparison_id)
        if reads == 1:
            with repository.connect() as connection:
                connection.execute(
                    "UPDATE user_suburbs SET notes='Concurrent writer', "
                    "version=version+1 WHERE id=?",
                    (comparison_id,),
                )
        return row

    monkeypatch.setattr(repository, "comparison", read_then_compete)
    with pytest.raises(ValueError, match="version_conflict"):
        repository.update_comparison(
            "comparison-1", {"version": stale["version"], "notes": "Lost writer"}
        )
    latest = original("comparison-1")
    assert latest is not None and latest["notes"] == "Concurrent writer"


@pytest.mark.parametrize("version", [True, False, "1", 1.0, 0, -1])
def test_update_requires_a_strict_positive_integer(repository: Repository, version: object) -> None:
    with pytest.raises(ValueError, match="version is required"):
        repository.update_comparison("comparison-1", {"version": version})
