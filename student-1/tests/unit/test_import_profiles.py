from __future__ import annotations

import hashlib
import inspect
import io
import json
import time
import uuid
from pathlib import Path
from threading import Event
from typing import Any, cast

import pytest

from propertyscope_data_platform.runner import _fixture_records
from propertyscope_data_store.import_profiles import (
    _GNAF_STREAM_COLUMNS,
    _GNAF_STREAM_INSERT_SQL,
    _GNAF_STREAM_STAGE_SQL,
    CANONICAL_SCHEMA_VERSION,
    IMPORT_PHASE_LABELS,
    POSTGRES_BIGINT_MAX,
    POSTGRES_INTEGER_MAX,
    ImportProfileError,
    ImportResult,
    _insert_profile_rows,
    _record_quality,
    execute_stream_import,
    iter_ndjson_import,
    prepare_import,
)
from propertyscope_data_store.loader import (
    DatabaseLoader,
    ImportCancelledError,
    _safe_loader_error,
    _VerifiedLineStream,
)
from propertyscope_data_store.source_materialisation import (
    BOCSAR_COPY_SQL,
    BOCSAR_COVERAGE_INSERT_SQL,
    BOCSAR_OBSERVATION_INSERT_SQL,
    BOCSAR_STAGE_SQL,
    PSI_ADDRESS_RESOLUTION_SQL,
    PSI_COPY_SQL,
    PSI_IDENTITY_SQL,
    PSI_PHASE_SQL,
    PSI_STAGE_SQL,
    PSI_STREAM_COLUMNS,
    PSI_TARGET_INSERT_SQL,
)


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


class _PersistedCandidateCountCursor:
    rowcount = 0

    def __init__(self, counts_by_table: dict[str, int]) -> None:
        self._counts_by_table = counts_by_table
        self._current: dict[str, int] | None = None
        self.executions: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, statement: str, parameters: tuple[object, ...]) -> None:
        normalised = " ".join(statement.split())
        self.executions.append((normalised, parameters))
        self._current = None
        for table, count in self._counts_by_table.items():
            if f"FROM {table}" in normalised:
                self._current = {"count": count}
                break

    def fetchone(self) -> dict[str, int] | None:
        return self._current


def test_conflict_safe_import_replay_counts_persisted_candidate_generation() -> None:
    cursor = _PersistedCandidateCountCursor({"warehouse.school": 10})
    release_id, artifact_id, run_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    accepted = _insert_profile_rows(
        cursor,
        "schools-master",
        release_id=release_id,
        artifact_id=artifact_id,
        run_id=run_id,
    )

    assert accepted == 10
    count_statement, count_parameters = cursor.executions[-1]
    assert "dataset_release_id=%s AND artifact_record_id=%s AND ingestion_run_id=%s" in (
        count_statement
    )
    assert count_parameters == (release_id, artifact_id, run_id)


def test_bocsar_replay_counts_both_persisted_candidate_tables() -> None:
    cursor = _PersistedCandidateCountCursor(
        {"warehouse.bocsar_observation": 7, "warehouse.bocsar_coverage": 3}
    )
    release_id, artifact_id, run_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    accepted = _insert_profile_rows(
        cursor,
        "bocsar-sparse",
        release_id=release_id,
        artifact_id=artifact_id,
        run_id=run_id,
        typed_source_stage=True,
    )

    assert accepted == 10
    count_executions = [
        execution for execution in cursor.executions if execution[0].startswith("SELECT count(*)")
    ]
    assert len(count_executions) == 2
    assert all(
        parameters == (release_id, artifact_id, run_id) for _, parameters in count_executions
    )


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


@pytest.mark.parametrize("publisher_postcode", ["0", "09", "200"])
def test_psi_import_maps_historical_non_postcodes_to_unknown(
    publisher_postcode: str,
) -> None:
    record = {**_contract_records("psi-sales")[0], "postcode": publisher_postcode}

    prepared = prepare_import(_artifact("psi-sales", [record]), profile="psi-sales")

    assert prepared.rows[0]["postcode"] is None


def test_psi_import_rejects_unexpected_nonnumeric_postcode_corruption() -> None:
    record = {**_contract_records("psi-sales")[0], "postcode": "20O0"}

    with pytest.raises(ImportProfileError, match="postcode must contain four digits"):
        prepare_import(_artifact("psi-sales", [record]), profile="psi-sales")


@pytest.mark.parametrize("field", ["street_number_first", "street_number_last"])
def test_psi_retains_sale_with_unusable_derived_address_number(field: str) -> None:
    record = {
        **_contract_records("psi-sales")[0],
        "house_number": "6711011622" if field == "street_number_first" else "10-6711011622",
        field: 6_711_011_622,
    }

    prepared = prepare_import(_artifact("psi-sales", [record]), profile="psi-sales")

    assert prepared.rows[0][field] is None
    assert prepared.rows[0]["house_number"] == record["house_number"]

    boundary = {**record, field: POSTGRES_INTEGER_MAX}
    assert prepare_import(_artifact("psi-sales", [boundary]), profile="psi-sales").rows[0][
        field
    ] == (POSTGRES_INTEGER_MAX)


@pytest.mark.parametrize(
    ("field", "maximum"),
    [
        ("source_revision", POSTGRES_INTEGER_MAX),
        ("source_partition_year", POSTGRES_INTEGER_MAX),
        ("price_aud", POSTGRES_BIGINT_MAX),
    ],
)
def test_psi_rejects_every_typed_integer_above_postgresql_range(field: str, maximum: int) -> None:
    record = {**_contract_records("psi-sales")[0], field: maximum + 1}

    with pytest.raises(ImportProfileError, match=rf"record 1 {field} is above its maximum"):
        prepare_import(_artifact("psi-sales", [record]), profile="psi-sales")

    boundary = {**record, field: maximum}
    validated = next(iter(iter_ndjson_import([json.dumps(boundary).encode()], profile="psi-sales")))
    assert validated[field] == maximum


def test_bocsar_rejects_count_above_postgresql_integer_range() -> None:
    record = {**_contract_records("bocsar-sparse")[0], "count": POSTGRES_INTEGER_MAX + 1}

    with pytest.raises(ImportProfileError, match="record 1 count is above its maximum"):
        prepare_import(_artifact("bocsar-sparse", [record]), profile="bocsar-sparse")

    boundary = {**record, "count": POSTGRES_INTEGER_MAX}
    assert (
        prepare_import(_artifact("bocsar-sparse", [boundary]), profile="bocsar-sparse").rows[0][
            "count"
        ]
        == POSTGRES_INTEGER_MAX
    )


class _CopySink:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows

    def __enter__(self) -> _CopySink:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def write_row(self, row: tuple[object, ...]) -> None:
        self.rows.append(row)


class _StreamingCursor:
    rowcount = 1

    def __init__(self) -> None:
        self.copied: list[tuple[object, ...]] = []
        self.statements: list[str] = []
        self.current: dict[str, int] | None = None

    def __enter__(self) -> _StreamingCursor:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def copy(self, _statement: str) -> _CopySink:
        return _CopySink(self.copied)

    def execute(self, statement: str, _parameters: object = None) -> None:
        normalised = " ".join(statement.split())
        self.statements.append(normalised)
        self.current = (
            {"count": len(self.copied)} if normalised.startswith("SELECT count(*)") else None
        )

    def fetchone(self) -> dict[str, int] | None:
        return self.current


class _StreamingConnection:
    def __init__(self) -> None:
        self.stream_cursor = _StreamingCursor()

    def cursor(self) -> _StreamingCursor:
        return self.stream_cursor


def test_unusable_final_psi_address_number_is_retained_with_quality_warning() -> None:
    valid = _contract_records("psi-sales")[0]
    invalid = {
        **valid,
        "source_business_key": "001:INVALID:1",
        "street_number_first": 6_711_011_622,
    }
    rows = iter_ndjson_import(
        (json.dumps(row).encode() + b"\n" for row in (valid, invalid)),
        profile="psi-sales",
    )
    connection = _StreamingConnection()

    result = execute_stream_import(
        cast(Any, connection),
        {
            "ingestion_run_id": uuid.uuid4(),
            "candidate_release_id": uuid.uuid4(),
            "artifact_record_id": uuid.uuid4(),
        },
        profile="psi-sales",
        rows=rows,
    )

    assert len(connection.stream_cursor.copied) == 2
    assert (
        connection.stream_cursor.copied[1][PSI_STREAM_COLUMNS.index("street_number_first")] is None
    )
    assert result.rows_accepted == 1
    assert result.rows_rejected == 0
    assert result.quality_checks == 4
    assert any("property_ref IS NOT NULL" in sql for sql in connection.stream_cursor.statements)
    assert any(
        "INSERT INTO warehouse.psi_sale" in sql for sql in connection.stream_cursor.statements
    )
    assert not any(
        "UPDATE serving.accepted_generation" in sql
        or "INSERT INTO serving.accepted_generation" in sql
        for sql in connection.stream_cursor.statements
    )


def test_zero_psi_property_linkage_is_a_blocking_quality_failure() -> None:
    class QualityCursor:
        def __init__(self) -> None:
            self.parameters: list[tuple[object, ...]] = []

        def execute(self, _statement: str, parameters: tuple[object, ...]) -> None:
            self.parameters.append(parameters)

    cursor = QualityCursor()

    checks = _record_quality(
        cursor,
        profile="psi-sales",
        run_id=uuid.uuid4(),
        release_id=uuid.uuid4(),
        expected=10,
        accepted=10,
        linked_property_rows=0,
    )

    linkage = next(
        parameters
        for parameters in cursor.parameters
        if parameters[3] == "import.psi-sales.property-linkage"
    )
    assert checks == 3
    assert linkage[5:7] == ("blocking", "fail")
    assert cast(Any, linkage[7]).obj == {"linked": 0, "unmatched": 10}


def test_import_phase_registry_has_stable_indeterminate_set_sql_boundaries() -> None:
    assert tuple(IMPORT_PHASE_LABELS) == (
        "artifact_verification",
        "typed_staging",
        "identity_revision_derivation",
        "address_resolution",
        "target_materialisation",
        "verification",
    )


def test_loader_exposes_bounded_canonical_validation_evidence() -> None:
    error = _safe_loader_error(ImportProfileError("record 1978 postcode must contain four digits"))

    assert error == {
        "code": "canonical_record_invalid",
        "category": "data_validation",
        "message": "Import stopped because record 1978 postcode must contain four digits.",
        "retryable": False,
    }


def test_psi_import_versions_changed_hashes_and_collapses_exact_retransmissions() -> None:
    source = "\n".join(statement for _phase, statement in PSI_PHASE_SQL)

    assert "first_transmissions" in source
    assert "min(ordinal) AS first_ordinal" in source
    assert "source_row_sha256" in source
    assert "derived_revision" in source
    assert "source_partition_year" in source
    assert "street_name_normalised" in source
    assert "warehouse.gnaf_address" in source
    assert "accepted.dataset_id='gnaf-nsw'" in source
    assert "registry.property" in source
    assert "count(DISTINCT property.property_ref)=1" in source
    assert "exact_address" in source
    assert "LEFT JOIN LATERAL" not in source
    assert "upper(" not in source
    assert "CASE WHEN count(DISTINCT property.property_ref)=1" in source
    assert "property.street_number_last" in source
    assert "property.street_number_suffix" in source
    assert "property.unit_number" in source
    assert "source.street_type IS NOT NULL" in source
    assert "source.house_number ~ '^[0-9]+[A-Z]?(-[0-9]+)?$'" in source


def test_psi_phase_callbacks_immediately_precede_their_real_sql_boundaries() -> None:
    events: list[str] = []

    class PhaseCursor(_PersistedCandidateCountCursor):
        def execute(self, statement: str, parameters: tuple[object, ...] = ()) -> None:
            phase_by_sql = {
                PSI_IDENTITY_SQL: "identity_revision_derivation",
                PSI_ADDRESS_RESOLUTION_SQL: "address_resolution",
                PSI_TARGET_INSERT_SQL: "target_materialisation",
            }
            if statement in phase_by_sql:
                events.append(f"sql:{phase_by_sql[statement]}")
            super().execute(statement, parameters)

    cursor = PhaseCursor({"warehouse.psi_sale": 7})
    release_id, artifact_id, run_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    accepted = _insert_profile_rows(
        cursor,
        "psi-sales",
        release_id=release_id,
        artifact_id=artifact_id,
        run_id=run_id,
        typed_source_stage=True,
        phase_rows=7,
        phase_callback=lambda phase, rows: events.append(f"callback:{phase}:{rows}"),
    )

    assert accepted == 7
    assert events == [
        "callback:identity_revision_derivation:7",
        "sql:identity_revision_derivation",
        "callback:address_resolution:7",
        "sql:address_resolution",
        "callback:target_materialisation:7",
        "sql:target_materialisation",
    ]


def test_psi_source_scale_path_casts_once_and_avoids_a_final_wide_sort() -> None:
    source = "\n".join(statement for _phase, statement in PSI_PHASE_SQL)

    assert "JSONB" not in PSI_STAGE_SQL
    assert "FREEZE TRUE" in PSI_COPY_SQL
    assert "GROUP BY source_business_key,source_row_sha256" in PSI_IDENTITY_SQL
    assert "min(ordinal) AS first_ordinal" in PSI_IDENTITY_SQL
    assert "ORDER BY first_ordinal" in PSI_IDENTITY_SQL
    assert "SELECT DISTINCT source.postcode" in PSI_ADDRESS_RESOLUTION_SQL
    assert "FROM propertyscope_psi_identity_stage identity" in PSI_ADDRESS_RESOLUTION_SQL
    assert "ON source.ordinal=identity.first_ordinal" in PSI_ADDRESS_RESOLUTION_SQL
    assert PSI_ADDRESS_RESOLUTION_SQL.count("CROSS JOIN LATERAL") == 2
    assert "accepted_gnaf_candidates AS MATERIALIZED" not in PSI_ADDRESS_RESOLUTION_SQL
    assert "registry_fallback_candidates" not in PSI_ADDRESS_RESOLUTION_SQL
    assert "property_candidates" not in PSI_ADDRESS_RESOLUTION_SQL
    assert "WHERE accepted.dataset_id='gnaf-nsw'" in PSI_ADDRESS_RESOLUTION_SQL
    assert "JOIN registry.property registered_property" in PSI_ADDRESS_RESOLUTION_SQL
    assert "registered_property.property_ref=COALESCE(" in PSI_ADDRESS_RESOLUTION_SQL
    assert (
        "address.property_ref,md5('propertyscope-gnaf:' || address.gnaf_pid)::uuid)"
        in PSI_ADDRESS_RESOLUTION_SQL
    )
    assert "WHERE gnaf_match.match_count=0" in PSI_ADDRESS_RESOLUTION_SQL
    assert "address.dataset_release_id=(" in PSI_ADDRESS_RESOLUTION_SQL
    assert "address.postcode=eligible.postcode" in PSI_ADDRESS_RESOLUTION_SQL
    assert "property.postcode=eligible.postcode" in PSI_ADDRESS_RESOLUTION_SQL
    assert "match_count" in PSI_ADDRESS_RESOLUTION_SQL
    assert "COALESCE(source.property_ref,resolution.exact_property_ref)" in source
    assert "JOIN propertyscope_psi_import_stage source" in PSI_TARGET_INSERT_SQL
    assert "ON source.ordinal=identity.first_ordinal" in PSI_TARGET_INSERT_SQL
    assert "source.source_business_key=identity.source_business_key" not in PSI_TARGET_INSERT_SQL
    assert "source.source_row_sha256=identity.source_row_sha256" not in PSI_TARGET_INSERT_SQL
    assert PSI_TARGET_INSERT_SQL.count("source.house_number ~ '^[0-9]+[A-Z]?(-[0-9]+)?$'") == 1
    assert "payload" not in source
    assert "ORDER BY identity.source_business_key" not in PSI_TARGET_INSERT_SQL


def test_bocsar_typed_normal_path_uses_rowcount_without_destination_scans() -> None:
    class RowcountCursor:
        def __init__(self) -> None:
            self.rowcount = 0
            self.statements: list[str] = []

        def execute(self, statement: str, _parameters: object = None) -> None:
            self.statements.append(" ".join(statement.split()))
            if statement == BOCSAR_OBSERVATION_INSERT_SQL:
                self.rowcount = 7
            elif statement == BOCSAR_COVERAGE_INSERT_SQL:
                self.rowcount = 3
            elif statement.lstrip().startswith("SELECT count(*)"):
                raise AssertionError("normal path must not rescan destination tables")

    cursor = RowcountCursor()
    accepted = _insert_profile_rows(
        cursor,
        "bocsar-sparse",
        release_id=uuid.uuid4(),
        artifact_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        typed_source_stage=True,
        phase_rows=10,
    )

    assert accepted == 10
    assert "JSONB" not in BOCSAR_STAGE_SQL
    assert "FREEZE TRUE" in BOCSAR_COPY_SQL
    assert "ORDER BY ordinal" not in BOCSAR_OBSERVATION_INSERT_SQL
    assert "ORDER BY ordinal" not in BOCSAR_COVERAGE_INSERT_SQL
    assert "min(ordinal) AS ordinal" in BOCSAR_OBSERVATION_INSERT_SQL
    assert "min(ordinal) AS ordinal" in BOCSAR_COVERAGE_INSERT_SQL
    assert "JOIN propertyscope_bocsar_import_stage source" in BOCSAR_OBSERVATION_INSERT_SQL
    assert "JOIN propertyscope_bocsar_import_stage source" in BOCSAR_COVERAGE_INSERT_SQL
    assert "observed_months" in BOCSAR_COVERAGE_INSERT_SQL
    assert "blank_means_observed_zero" in BOCSAR_COVERAGE_INSERT_SQL


class _Store:
    def database_size_bytes(self) -> int:
        return 1024

    def database_filesystem_available_bytes(self) -> int:
        return 1024 * 1024 * 1024 * 1024

    def import_cancel_requested(self, _operation_id: uuid.UUID) -> bool:
        return False

    def execute_import_profile(
        self,
        work: dict[str, Any],
        prepared: Any,
        *,
        phase_callback: Any | None = None,
        lease_failed_event: Event | None = None,
        stop_event: Event | None = None,
    ) -> ImportResult:
        assert lease_failed_event is None or not lease_failed_event.is_set()
        assert stop_event is None or not stop_event.is_set()
        assert prepared.profile == "property-fixture"
        assert work["candidate_release_id"] == "60000000-0000-0000-0000-000000000001"
        if phase_callback is not None:
            phase_callback("target_materialisation", 1)
            phase_callback("verification", 1)
        return ImportResult(1, 1, 1, 0, 2)


class _CancelledStore(_Store):
    def import_cancel_requested(self, _operation_id: uuid.UUID) -> bool:
        return True


class _ActivationStore:
    def __init__(self, artifact: dict[str, Any]) -> None:
        self.operation_id = uuid.uuid4()
        self.release_id = uuid.uuid4()
        self.artifact = artifact
        self.heartbeats = 0
        self.materialized = False
        self.finished_status = ""
        self.finished_error: dict[str, Any] | None = None
        self.progress_phases: list[tuple[str, str]] = []

    def claim_release_activation(self, **_: Any) -> dict[str, Any]:
        return {
            "id": self.operation_id,
            "dataset_release_id": self.release_id,
            "lease_token": "activation-token",
        }

    def release_artifact(self, release_id: uuid.UUID) -> dict[str, Any]:
        assert release_id == self.release_id
        return self.artifact

    def heartbeat_release_activation(self, *_: Any, **__: Any) -> None:
        self.heartbeats += 1

    def update_release_activation_progress(self, *_: Any, **kwargs: Any) -> None:
        assert kwargs["worker_id"] == "loader-test"
        assert kwargs["lease_token"] == "activation-token"
        self.progress_phases.append((str(kwargs["phase_key"]), str(kwargs["phase"])))

    def materialize_release_activation(self, *_: Any, **kwargs: Any) -> None:
        assert kwargs["stop_event"] is not None
        assert kwargs["lease_failed_event"] is not None
        self.materialized = True

    def finish_release_activation(self, *_: Any, **kwargs: Any) -> None:
        self.finished_status = str(kwargs["status"])
        self.finished_error = kwargs["error"]

    def claim_import(self, **_: Any) -> None:
        raise AssertionError("publication activation must be serviced before another import")


class _ImportLeaseStore:
    def __init__(self, *, fail_renewal: bool = False) -> None:
        self.operation_id = uuid.uuid4()
        self.heartbeats = 0
        self.heartbeat_seen = Event()
        self.heartbeat_attempted = Event()
        self.lease_seconds: list[int] = []
        self.finished_status = ""
        self.fail_renewal = fail_renewal

    def claim_release_activation(self, **_: Any) -> None:
        return None

    def claim_import(self, **kwargs: Any) -> dict[str, Any]:
        self.lease_seconds.append(int(kwargs["lease_seconds"]))
        return {"id": self.operation_id, "lease_token": "import-token"}

    def heartbeat_import(self, *_: Any, **kwargs: Any) -> None:
        self.heartbeats += 1
        self.lease_seconds.append(int(kwargs["lease_seconds"]))
        if self.heartbeats >= 2:
            self.heartbeat_attempted.set()
            if self.fail_renewal:
                raise RuntimeError("database unavailable")
            self.heartbeat_seen.set()

    def import_work(self, operation_id: uuid.UUID) -> dict[str, Any]:
        assert operation_id == self.operation_id
        return {"id": operation_id}

    def finish_import(self, *_: Any, **kwargs: Any) -> None:
        self.finished_status = str(kwargs["status"])

    def import_cancel_requested(self, _operation_id: uuid.UUID) -> bool:
        return False


def _release_export_artifact(
    root: Path,
    expected: bytes,
    *,
    stored: bytes | None,
) -> dict[str, Any]:
    digest = hashlib.sha256(expected).hexdigest()
    relative = Path("sha256") / digest[:2] / digest
    if stored is not None:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(stored)
    return {
        "artifact_kind": "release_export",
        "storage_key": relative.as_posix(),
        "bytes": len(expected),
        "content_sha256": digest,
    }


def test_loader_prioritises_and_finishes_background_release_activation(tmp_path: Path) -> None:
    payload = b"verified release export"
    store = _ActivationStore(_release_export_artifact(tmp_path, payload, stored=payload))
    loader = DatabaseLoader(cast(Any, store), tmp_path, worker_id="loader-test")

    assert loader.run_once() is True
    assert store.heartbeats == 1
    assert store.materialized is True
    assert store.finished_status == "succeeded"
    assert [key for key, _label in store.progress_phases] == [
        "artifact_verification",
        "materialisation",
        "commit_pointer",
    ]


def test_loader_renews_import_lease_until_work_finishes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _ImportLeaseStore()
    loader = DatabaseLoader(cast(Any, store), tmp_path, worker_id="loader-test")
    monkeypatch.setattr("propertyscope_data_store.loader.IMPORT_HEARTBEAT_SECONDS", 0.01)

    def execute(
        _work: dict[str, Any],
        *,
        lease_failed_event: Event,
    ) -> tuple[dict[str, int], dict[str, Any]]:
        assert store.heartbeat_seen.wait(1)
        assert not lease_failed_event.is_set()
        return {
            "rows_in": 1,
            "rows_staged": 1,
            "rows_accepted": 1,
            "rows_rejected": 0,
        }, {"verified": True}

    monkeypatch.setattr(loader, "_execute", execute)

    assert loader.run_once() is True
    assert store.heartbeats >= 2
    assert set(store.lease_seconds) == {120}
    assert store.finished_status == "succeeded"


def test_loader_leaves_import_recoverable_when_heartbeat_renewal_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _ImportLeaseStore(fail_renewal=True)
    loader = DatabaseLoader(cast(Any, store), tmp_path, worker_id="loader-test")
    monkeypatch.setattr("propertyscope_data_store.loader.IMPORT_HEARTBEAT_SECONDS", 0.01)

    def execute(
        _work: dict[str, Any],
        *,
        lease_failed_event: Event,
    ) -> tuple[dict[str, int], dict[str, Any]]:
        assert store.heartbeat_attempted.wait(1)
        assert lease_failed_event.wait(1)
        raise RuntimeError("import lease could not be renewed")

    monkeypatch.setattr(loader, "_execute", execute)

    assert loader.run_once() is True
    assert store.heartbeats == 2
    assert store.finished_status == ""
    time.sleep(0.03)
    assert store.heartbeats == 2


def test_loader_shutdown_leaves_active_import_recoverable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _ImportLeaseStore()
    loader = DatabaseLoader(cast(Any, store), tmp_path, worker_id="loader-test")

    def execute(
        _work: dict[str, Any],
        *,
        lease_failed_event: Event,
    ) -> tuple[dict[str, int], dict[str, Any]]:
        assert not lease_failed_event.is_set()
        loader.stop()
        raise InterruptedError("database loader stopped during import")

    monkeypatch.setattr(loader, "_execute", execute)

    assert loader.run_once() is True
    assert store.finished_status == ""


def test_loader_shutdown_leaves_activation_explicitly_recoverable(tmp_path: Path) -> None:
    payload = b"verified release export"
    store = _ActivationStore(_release_export_artifact(tmp_path, payload, stored=payload))
    loader = DatabaseLoader(cast(Any, store), tmp_path, worker_id="loader-test")
    loader.stop()

    loader._activate({"id": store.operation_id, "lease_token": "activation-token"})

    assert store.finished_status == "interrupted"


@pytest.mark.parametrize("stored", [None, b"corrupt!"], ids=["missing", "corrupt"])
def test_loader_fails_activation_when_release_export_is_unavailable_or_corrupt(
    tmp_path: Path,
    stored: bytes | None,
) -> None:
    expected = b"original"
    store = _ActivationStore(_release_export_artifact(tmp_path, expected, stored=stored))
    loader = DatabaseLoader(cast(Any, store), tmp_path, worker_id="loader-test")

    assert loader.run_once() is True

    assert store.materialized is False
    assert store.finished_status == "failed"
    assert store.finished_error is not None
    assert store.finished_error["code"] == "release_artifact_verification_failed"
    assert "live pointer was not changed" in store.finished_error["message"]


def test_loader_verifies_artifact_then_delegates_registered_copy_profile(tmp_path: Path) -> None:
    data = _artifact("property-fixture", [_fixture_records()[0]])
    digest = hashlib.sha256(data).hexdigest()
    relative = Path("sha256") / digest[:2] / digest
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(data)
    loader = DatabaseLoader(
        cast(Any, _Store()),
        tmp_path,
        worker_id="loader-test",
        database_capacity_bytes=128 * 1024 * 1024 * 1024,
    )
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
    loader = DatabaseLoader(
        cast(Any, _CancelledStore()),
        tmp_path,
        worker_id="loader-test",
        database_capacity_bytes=128 * 1024 * 1024 * 1024,
    )

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


def test_loader_stops_before_reading_an_import_during_shutdown(tmp_path: Path) -> None:
    data = _artifact("property-fixture", [_fixture_records()[0]])
    digest = hashlib.sha256(data).hexdigest()
    relative = Path("sha256") / digest[:2] / digest
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(data)
    loader = DatabaseLoader(
        cast(Any, _Store()),
        tmp_path,
        worker_id="loader-test",
        database_capacity_bytes=128 * 1024 * 1024 * 1024,
    )
    loader.stop()

    with pytest.raises(InterruptedError, match="loader stopped"):
        loader._execute(
            {
                "id": "70000000-0000-0000-0000-000000000003",
                "import_profile_key": "property-fixture",
                "storage_key": relative.as_posix(),
                "artifact_bytes": len(data),
                "content_sha256": digest,
                "media_type": "application/json",
                "candidate_release_id": "60000000-0000-0000-0000-000000000001",
            }
        )


def test_source_scale_stream_hashes_the_same_bytes_and_reports_final_progress() -> None:
    payload = b'{"row":1}\n{"row":2}\n'
    progress: list[tuple[int, int]] = []
    stream = _VerifiedLineStream(
        io.BytesIO(payload),
        expected_sha256=hashlib.sha256(payload).hexdigest(),
        expected_bytes=len(payload),
        progress=lambda rows, byte_count: progress.append((rows, byte_count)),
        raise_if_cancelled=lambda: None,
    )

    assert b"".join(stream) == payload
    stream.verify_complete()
    assert progress[-1] == (2, len(payload))


def test_source_scale_stream_observes_cancellation_during_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b'{"row":1}\n{"row":2}\n'
    moments = iter((0.0, 2.0))
    monkeypatch.setattr(time, "monotonic", lambda: next(moments))
    stream = _VerifiedLineStream(
        io.BytesIO(payload),
        expected_sha256=hashlib.sha256(payload).hexdigest(),
        expected_bytes=len(payload),
        progress=lambda _rows, _bytes: None,
        raise_if_cancelled=lambda: (_ for _ in ()).throw(
            ImportCancelledError("cancelled by operator")
        ),
    )

    with pytest.raises(ImportCancelledError, match="cancelled by operator"):
        list(stream)


@pytest.mark.parametrize(
    "profile",
    ["property-fixture", "gnaf-nsw", "psi-sales", "bocsar-sparse", "schools-master"],
)
def test_deterministic_canonical_samples_use_the_database_contract(profile: str) -> None:
    records = _contract_records(profile)

    prepared = prepare_import(_artifact(profile, records), profile=profile)

    assert len(prepared.rows) == 10


def test_import_updates_manifest_and_release_row_counts_together() -> None:
    source = inspect.getsource(execute_stream_import)
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


def test_source_scale_gnaf_uses_native_typed_staging_instead_of_jsonb() -> None:
    prepared = prepare_import(
        _artifact("gnaf-nsw", _contract_records("gnaf-nsw")[:1]), profile="gnaf-nsw"
    )

    assert set(_GNAF_STREAM_COLUMNS).issubset(prepared.rows[0])
    assert "JSONB" not in _GNAF_STREAM_STAGE_SQL
    assert "payload" not in _GNAF_STREAM_INSERT_SQL
    assert "ST_Transform" in _GNAF_STREAM_INSERT_SQL


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
