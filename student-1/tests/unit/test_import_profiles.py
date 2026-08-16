from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
from typing import Any, cast

import pytest

from propertyscope_data_platform.runner import _canonical_records
from propertyscope_data_store.import_profiles import (
    CANONICAL_SCHEMA_VERSION,
    ImportProfileError,
    ImportResult,
    execute_import,
    iter_ndjson_import,
    prepare_import,
)
from propertyscope_data_store.loader import DatabaseLoader


def _artifact(profile: str, records: list[dict[str, object]]) -> bytes:
    return json.dumps(
        {
            "schema_version": CANONICAL_SCHEMA_VERSION,
            "profile": profile,
            "records": records,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


@pytest.mark.parametrize(
    ("profile", "record", "natural_key"),
    [
        (
            "schools-master",
            {
                "school_code": "1001",
                "school_name": "Example Public School",
                "school_type": "Primary",
                "status": "Open",
                "locality_original": "North Sydney",
                "locality_normalised": "NORTH SYDNEY",
                "lga_name": "North Sydney",
                "latitude": -33.84,
                "longitude": 151.21,
            },
            "school_code",
        ),
        (
            "gnaf-nsw",
            {
                "gnaf_pid": "GANSW0001",
                "property_ref": None,
                "address_display": "1 Example Street, Sydney NSW 2000",
                "locality": "Sydney",
                "postcode": "2000",
                "source_status": "CURRENT",
                "geocode_type": "PC",
                "source_crs": 7844,
                "latitude": -33.86,
                "longitude": 151.2,
            },
            "gnaf_pid",
        ),
        (
            "psi-sales",
            {
                "source_business_key": "001:P1:1",
                "source_revision": 1,
                "source_era": "post-2001",
                "district_code": "001",
                "property_id": "P1",
                "dealing_id": "D1",
                "contract_date": "2025-01-01",
                "settlement_date": "2025-02-01",
                "price_aud": 900000,
                "area_original": "1.5",
                "area_unit": "H",
                "area_square_metres": "15000",
                "property_ref": None,
                "match_tier": "MISS",
                "match_confidence": "0",
                "geographic_precision": "unmatched",
            },
            "source_business_key",
        ),
    ],
)
def test_registered_profile_prepares_hashed_canonical_rows(
    profile: str, record: dict[str, object], natural_key: str
) -> None:
    prepared = prepare_import(_artifact(profile, [record]), profile=profile)

    assert prepared.profile == profile
    assert prepared.rows[0][natural_key] == record[natural_key]
    assert len(prepared.rows[0]["source_row_sha256"]) == 64


def test_bocsar_requires_sparse_observation_and_explicit_coverage_contracts() -> None:
    records: list[dict[str, object]] = [
        {
            "record_kind": "observation",
            "geography_kind": "postcode",
            "geography_value": "0077",
            "source_category_key": "theft-other",
            "offence_label": "Theft",
            "subcategory_label": "Other",
            "month": "2025-02-01",
            "count": 3,
        },
        {
            "record_kind": "coverage",
            "geography_kind": "postcode",
            "geography_value": "0077",
            "source_category_key": "theft-other",
            "observed_months": ["2025-01-01", "2025-02-01"],
            "blank_means_observed_zero": True,
        },
    ]

    prepared = prepare_import(_artifact("bocsar-sparse", records), profile="bocsar-sparse")

    assert len(prepared.rows) == 2
    assert prepared.rows[1]["month_count"] == 2
    assert prepared.rows[1]["blank_means_observed_zero"] is True


def test_profile_mismatch_and_duplicate_natural_keys_fail_before_copy() -> None:
    record = _canonical_records("property-fixture")[0]
    with pytest.raises(ImportProfileError, match="does not match"):
        prepare_import(_artifact("property-fixture", [record]), profile="schools-master")
    with pytest.raises(ImportProfileError, match="natural keys"):
        prepare_import(_artifact("property-fixture", [record, record]), profile="property-fixture")


def test_schools_import_accepts_nsw_lord_howe_island() -> None:
    record: dict[str, object] = {
        "school_code": "1921",
        "school_name": "Lord Howe Island Central School",
        "school_type": "Central Schools",
        "status": "Open",
        "locality_original": "Lord Howe Island",
        "locality_normalised": "LORD HOWE ISLAND",
        "lga_name": None,
        "latitude": -31.530072,
        "longitude": 159.069032,
    }
    prepared = prepare_import(_artifact("schools-master", [record]), profile="schools-master")
    assert prepared.rows[0]["school_code"] == "1921"


class _Store:
    def execute_import_profile(self, work: dict[str, Any], prepared: Any) -> ImportResult:
        assert prepared.profile == "property-fixture"
        assert work["candidate_release_id"] == "60000000-0000-0000-0000-000000000001"
        return ImportResult(1, 1, 1, 0, 2)


def test_loader_verifies_artifact_then_delegates_registered_copy_profile(tmp_path: Path) -> None:
    data = _artifact("property-fixture", [_canonical_records("property-fixture")[0]])
    digest = hashlib.sha256(data).hexdigest()
    relative = Path("sha256") / digest[:2] / digest
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(data)
    loader = DatabaseLoader(cast(Any, _Store()), tmp_path, worker_id="loader-test")
    work = {
        "import_profile_key": "property-fixture",
        "storage_key": relative.as_posix(),
        "artifact_bytes": len(data),
        "content_sha256": digest,
        "media_type": "application/json",
        "candidate_release_id": "60000000-0000-0000-0000-000000000001",
    }

    counts, result = loader._execute(work)

    assert counts == {"rows_in": 1, "rows_staged": 1, "rows_accepted": 1, "rows_rejected": 0}
    assert result["staging_method"] == "postgresql-copy"
    assert result["accepted_generation_unchanged"] is True


@pytest.mark.parametrize(
    "profile",
    ["property-fixture", "gnaf-nsw", "psi-sales", "bocsar-sparse", "schools-master"],
)
def test_runner_showcase_records_use_the_database_canonical_contract(profile: str) -> None:
    records = _canonical_records(profile)

    prepared = prepare_import(_artifact(profile, records), profile=profile)

    assert len(prepared.rows) == 10


def test_import_updates_manifest_and_release_row_counts_together() -> None:
    source = inspect.getsource(execute_import)
    assert "manifest_json=jsonb_set" in source
    assert "'{record_count}'" in source


def test_source_scale_ndjson_validation_streams_without_a_row_limit() -> None:
    row = {
        "source_business_key": "001:P1:1",
        "source_revision": 1,
        "source_era": "post-2001",
        "district_code": "001",
        "property_id": "P1",
        "dealing_id": "D1",
        "contract_date": "2025-01-01",
        "settlement_date": "2025-02-01",
        "price_aud": 900000,
        "area_original": "500",
        "area_unit": "M",
        "area_square_metres": "500",
        "property_ref": None,
        "match_tier": "MISS",
        "match_confidence": "0",
        "geographic_precision": "unmatched",
    }
    lines = (
        json.dumps({**row, "source_business_key": f"001:P{index}:1"}).encode() + b"\n"
        for index in range(100_001)
    )

    assert sum(1 for _ in iter_ndjson_import(lines, profile="psi-sales")) == 100_001


@pytest.mark.parametrize("area_unit", ["", "   ", None])
def test_psi_optional_text_normalises_official_blank_values(area_unit: object) -> None:
    record: dict[str, object] = {
        "source_business_key": "001:P1:1",
        "source_revision": 1,
        "source_era": "post-2001",
        "district_code": "001",
        "property_id": "P1",
        "dealing_id": "D1",
        "contract_date": "2025-01-01",
        "settlement_date": "2025-02-01",
        "price_aud": 900000,
        "area_original": "500",
        "area_unit": area_unit,
        "area_square_metres": "500",
        "property_ref": None,
        "match_tier": "MISS",
        "match_confidence": "0",
        "geographic_precision": "unmatched",
    }

    prepared = prepare_import(_artifact("psi-sales", [record]), profile="psi-sales")

    assert prepared.rows[0]["area_unit"] is None
