from __future__ import annotations

import hashlib
import inspect
import json
import uuid
from pathlib import Path
from typing import Any, cast

import pytest

from propertyscope_data_platform.runner import _fixture_records
from propertyscope_data_store.import_profiles import (
    _PROFILE_INSERT_SQL,
    CANONICAL_SCHEMA_VERSION,
    ImportProfileError,
    ImportResult,
    execute_import,
    iter_ndjson_import,
    prepare_import,
)
from propertyscope_data_store.loader import DatabaseLoader, ImportCancelledError


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


def _contract_records(profile: str) -> list[dict[str, object]]:
    """Build finite test-only records for each database import contract."""
    if profile == "property-fixture":
        return _fixture_records()
    if profile == "schools-master":
        return [
            {
                "school_code": f"S{index:04d}",
                "school_name": f"Example Public School {index}",
                "school_type": "Primary",
                "status": "Open",
                "locality_original": "Sydney",
                "locality_normalised": "SYDNEY",
                "lga_name": "City of Sydney",
                "latitude": -33.9 + index * 0.001,
                "longitude": 151.1 + index * 0.001,
            }
            for index in range(1, 11)
        ]
    if profile == "gnaf-nsw":
        return [
            {
                "gnaf_pid": f"GANSWFIXTURE{index:04d}",
                "property_ref": None,
                "address_display": f"{index} Fixture Street, Sydney NSW 2000",
                "locality": "SYDNEY",
                "postcode": "2000",
                "source_status": "CURRENT",
                "geocode_type": "PC",
                "source_crs": 7844,
                "latitude": -33.9 + index * 0.001,
                "longitude": 151.1 + index * 0.001,
            }
            for index in range(1, 11)
        ]
    if profile == "psi-sales":
        return [
            {
                "source_business_key": f"001:P{index}:1",
                "source_revision": 1,
                "source_era": "post-2001",
                "source_partition_year": 2025,
                "district_code": "001",
                "property_id": f"P{index}",
                "dealing_id": f"D{index}",
                "contract_date": "2025-01-01",
                "settlement_date": "2025-02-01",
                "price_aud": 800_000 + index,
                "area_original": "500",
                "area_unit": "M",
                "area_square_metres": "500",
                "property_ref": None,
                "match_tier": "MISS",
                "match_confidence": "0",
                "geographic_precision": "unmatched",
            }
            for index in range(1, 11)
        ]
    if profile == "bocsar-sparse":
        return [
            record
            for index in range(1, 6)
            for record in (
                {
                    "record_kind": "observation",
                    "geography_kind": "postcode",
                    "geography_value": "2000",
                    "source_category_key": f"fixture-category-{index}",
                    "offence_label": "Synthetic offence",
                    "subcategory_label": f"Synthetic category {index}",
                    "month": "2025-02-01",
                    "count": index,
                },
                {
                    "record_kind": "coverage",
                    "geography_kind": "postcode",
                    "geography_value": "2000",
                    "source_category_key": f"fixture-category-{index}",
                    "observed_months": ["2025-01-01", "2025-02-01"],
                    "blank_means_observed_zero": True,
                },
            )
        ]
    raise AssertionError(f"missing test records for {profile}")


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
    record = _fixture_records()[0]
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


def test_psi_scope_partition_survives_nullable_business_dates() -> None:
    record: dict[str, object] = {
        "source_business_key": "001:P1:1",
        "source_revision": 1,
        "source_era": "post-2001",
        "district_code": "001",
        "property_id": "P1",
        "dealing_id": None,
        "contract_date": None,
        "settlement_date": None,
        "price_aud": None,
        "area_original": None,
        "area_unit": None,
        "area_square_metres": None,
        "property_ref": None,
        "match_tier": "MISS",
        "match_confidence": "0",
        "geographic_precision": "unmatched",
        "source_partition_year": 2025,
    }

    prepared = prepare_import(_artifact("psi-sales", [record]), profile="psi-sales")

    assert prepared.rows[0]["contract_date"] is None
    assert prepared.rows[0]["source_partition_year"] == 2025

    corrected = {**record, "price_aud": 910000}
    revisions = prepare_import(
        _artifact("psi-sales", [record, record, corrected]), profile="psi-sales"
    )
    assert [row["source_revision"] for row in revisions.rows] == [1, 2]
    assert [row["price_aud"] for row in revisions.rows] == [None, 910000]

    later_partition = {**record, "source_partition_year": 2026}
    retransmission = prepare_import(
        _artifact("psi-sales", [record, later_partition]), profile="psi-sales"
    )
    assert len(retransmission.rows) == 1


def test_psi_import_versions_changed_hashes_and_collapses_exact_retransmissions() -> None:
    source = _PROFILE_INSERT_SQL["psi-sales"]

    assert "distinct_source_rows" in source
    assert "source_row_sha256" in source
    assert "derived_revision" in source
    assert "source_partition_year" in source
    assert "street_name_normalised" in source
    assert "registry.property" in source
    assert "count(*)=1" in source
    assert "exact_address" in source


class _Store:
    def import_cancel_requested(self, _operation_id: uuid.UUID) -> bool:
        return False

    def execute_import_profile(self, work: dict[str, Any], prepared: Any) -> ImportResult:
        assert prepared.profile == "property-fixture"
        assert work["candidate_release_id"] == "60000000-0000-0000-0000-000000000001"
        return ImportResult(1, 1, 1, 0, 2)


class _CancelledStore(_Store):
    def import_cancel_requested(self, _operation_id: uuid.UUID) -> bool:
        return True


class _ActivationStore:
    def __init__(self) -> None:
        self.operation_id = uuid.uuid4()
        self.heartbeats = 0
        self.materialized = False
        self.finished_status = ""

    def claim_release_activation(self, **_: Any) -> dict[str, Any]:
        return {"id": self.operation_id, "lease_token": "activation-token"}

    def heartbeat_release_activation(self, *_: Any, **__: Any) -> None:
        self.heartbeats += 1

    def materialize_release_activation(self, *_: Any, **kwargs: Any) -> None:
        assert kwargs["stop_event"] is not None
        assert kwargs["lease_failed_event"] is not None
        self.materialized = True

    def finish_release_activation(self, *_: Any, **kwargs: Any) -> None:
        self.finished_status = str(kwargs["status"])

    def claim_import(self, **_: Any) -> None:
        raise AssertionError("publication activation must be serviced before another import")


def test_loader_prioritises_and_finishes_background_release_activation(tmp_path: Path) -> None:
    store = _ActivationStore()
    loader = DatabaseLoader(cast(Any, store), tmp_path, worker_id="loader-test")

    assert loader.run_once() is True
    assert store.heartbeats == 1
    assert store.materialized is True
    assert store.finished_status == "succeeded"


def test_loader_shutdown_leaves_activation_explicitly_recoverable(tmp_path: Path) -> None:
    store = _ActivationStore()
    loader = DatabaseLoader(cast(Any, store), tmp_path, worker_id="loader-test")
    loader.stop()

    loader._activate({"id": store.operation_id, "lease_token": "activation-token"})

    assert store.finished_status == "interrupted"


def test_loader_verifies_artifact_then_delegates_registered_copy_profile(tmp_path: Path) -> None:
    data = _artifact("property-fixture", [_fixture_records()[0]])
    digest = hashlib.sha256(data).hexdigest()
    relative = Path("sha256") / digest[:2] / digest
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(data)
    loader = DatabaseLoader(cast(Any, _Store()), tmp_path, worker_id="loader-test")
    work = {
        "id": "70000000-0000-0000-0000-000000000001",
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


def test_loader_stops_before_reading_a_cancelled_import(tmp_path: Path) -> None:
    data = _artifact("property-fixture", [_fixture_records()[0]])
    digest = hashlib.sha256(data).hexdigest()
    relative = Path("sha256") / digest[:2] / digest
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(data)
    loader = DatabaseLoader(cast(Any, _CancelledStore()), tmp_path, worker_id="loader-test")

    with pytest.raises(ImportCancelledError, match="cancelled by operator"):
        loader._execute(
            {
                "id": "70000000-0000-0000-0000-000000000002",
                "import_profile_key": "property-fixture",
                "storage_key": relative.as_posix(),
                "artifact_bytes": len(data),
                "content_sha256": digest,
                "media_type": "application/json",
                "candidate_release_id": "60000000-0000-0000-0000-000000000001",
            }
        )


@pytest.mark.parametrize(
    "profile",
    ["property-fixture", "gnaf-nsw", "psi-sales", "bocsar-sparse", "schools-master"],
)
def test_deterministic_canonical_samples_use_the_database_contract(profile: str) -> None:
    records = _contract_records(profile)

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
