from __future__ import annotations

from pathlib import Path

from propertyscope_data_platform.configuration import load_job_profiles, load_source_register
from propertyscope_data_platform.source_catalog import (
    CATALOGUE_GROUPS,
    DATASET_PRESENTATIONS,
    catalogue_presentation_payload,
    group_sources,
)

ROOT = Path(__file__).resolve().parents[2]


def test_presentation_catalogue_covers_every_registered_source_and_job() -> None:
    sources = load_source_register(ROOT / "config" / "source-register.yaml")
    jobs = load_job_profiles(ROOT / "config" / "job-profiles")

    assert {item.source_key for item in DATASET_PRESENTATIONS} == set(sources.keys())
    assert {item.job_profile for item in DATASET_PRESENTATIONS} == set(jobs.keys())
    assert {item.adapter_key for item in DATASET_PRESENTATIONS} == {
        sources.get_profile(key).adapter_key for key in sources
    }


def test_presentation_catalogue_has_six_plain_groups_and_keeps_readiness_separate() -> None:
    payload = catalogue_presentation_payload()

    assert [group.label for group in CATALOGUE_GROUPS] == [
        "Foundational property data",
        "Geography and boundaries",
        "Planning and hazards",
        "Community and amenities",
        "Economic context",
        "Development fixtures",
    ]
    assert len(payload["datasets"]) == 16
    assert all(item["purpose"] for item in payload["datasets"])
    assert all("capability" not in item and "ready" not in item for item in payload["datasets"])


def test_source_grouping_improves_defaults_and_preserves_custom_names() -> None:
    groups = group_sources(
        [
            {"adapter_key": "gnaf-bulk", "name": "G-NAF Open NSW"},
            {"adapter_key": "psi-bulk", "name": "Sales feed selected by the team"},
        ]
    )

    assert [group["label"] for group in groups] == ["Foundational property data"]
    assert [item["presentation_name"] for item in groups[0]["items"]] == [
        "G-NAF addresses",
        "Sales feed selected by the team",
    ]
