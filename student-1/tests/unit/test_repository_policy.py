from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest

from propertyscope_data_store.errors import ConflictError
from propertyscope_data_store.orchestration_policy import (
    run_status_for_stage,
    task_plan,
    validate_retry_parent,
)
from propertyscope_data_store.persistence_support import (
    json_document,
    normalise_row,
    receipt_matches_values,
    require_source_snapshot,
)
from propertyscope_data_store.query_specs import (
    PREVIEW_SPECS,
    PROPERTY_RECORD_SPEC,
    encode_export_cursor,
    normalise_product_rows,
    release_export_query,
    release_product_query,
)


def test_run_task_plan_has_stable_order_and_cached_skip_policy() -> None:
    full_refresh = task_plan("full_refresh")
    cached = task_plan("reprocess_cached")

    assert tuple(task.logical_key for task in full_refresh) == (
        "00/discover",
        "01/acquire",
        "02/import",
        "03/build_release",
    )
    assert not any(task.skipped for task in full_refresh)
    assert tuple(task.stage for task in cached if task.skipped) == (
        "discover",
        "acquire",
    )


@pytest.mark.parametrize(
    ("stage", "status"),
    [
        ("discover", "discovering"),
        ("acquire", "acquiring"),
        ("import", "staging"),
        ("build_release", "building_release"),
    ],
)
def test_claimed_stage_projects_the_current_public_run_status(stage: str, status: str) -> None:
    assert run_status_for_stage(stage) == status


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_full_refresh_retry_accepts_only_recoverable_parent_states(status: str) -> None:
    job_id = uuid.uuid4()

    attempt = validate_retry_parent(
        job_id,
        "full_refresh",
        {"job_definition_id": str(job_id), "status": status, "attempt_number": 2},
    )

    assert attempt == 3


def test_retry_parent_rejects_wrong_job_and_non_terminal_cached_parent() -> None:
    job_id = uuid.uuid4()

    with pytest.raises(ConflictError, match="different job"):
        validate_retry_parent(
            job_id,
            "full_refresh",
            {"job_definition_id": str(uuid.uuid4()), "status": "failed", "attempt_number": 1},
        )
    with pytest.raises(ConflictError, match="terminal parent"):
        validate_retry_parent(
            job_id,
            "reprocess_cached",
            {"job_definition_id": str(job_id), "status": "running", "attempt_number": 1},
        )


def test_preview_registry_has_fixed_generation_scoped_queries() -> None:
    assert PREVIEW_SPECS["property-fixture"] is PROPERTY_RECORD_SPEC
    assert PREVIEW_SPECS["gnaf-nsw"] is PROPERTY_RECORD_SPEC
    assert set(PREVIEW_SPECS) == {
        "property-fixture",
        "gnaf-nsw",
        "psi-sales",
        "bocsar-sparse",
        "schools-master",
    }
    for spec in PREVIEW_SPECS.values():
        assert "dataset_release_id=%s" in spec.select_sql
        assert "LIMIT %s OFFSET %s" in spec.select_sql
        assert "dataset_release_id=%s" in spec.count_sql
        assert len(spec.columns) == len(set(spec.columns))


@pytest.mark.parametrize(
    ("profile", "table"),
    [
        ("property-fixture", "warehouse.gnaf_address"),
        ("gnaf-nsw", "warehouse.gnaf_address"),
        ("bocsar-sparse", "warehouse.bocsar_observation"),
        ("schools-master", "warehouse.school"),
    ],
)
def test_release_product_queries_are_fixed_and_generation_scoped(profile: str, table: str) -> None:
    release_id = uuid.uuid4()

    query = release_product_query(
        profile, release_id, {"maximum_records": 100}, limit=25, offset=50
    )

    assert table in query.select_sql
    assert "dataset_release_id=%s" in query.select_sql
    assert release_id in query.select_params
    assert query.select_params[-2:] == (25, 50)
    assert release_id in query.count_params


def test_psi_product_query_requires_and_applies_explicit_source_years() -> None:
    release_id = uuid.uuid4()

    with pytest.raises(ConflictError, match="bounded year scope"):
        release_product_query("psi-sales", release_id, {"maximum_records": 100}, limit=10, offset=0)

    query = release_product_query(
        "psi-sales",
        release_id,
        {"release_scope": {"years": [2024, 2025], "maximum_records": 100}},
        limit=10,
        offset=0,
    )

    assert "source_partition_year=ANY(%s)" in query.select_sql
    assert query.select_params == (release_id, [2024, 2025], 10, 0)
    assert query.count_params == (release_id, [2024, 2025])
    assert "least(" not in query.count_sql.lower()


def test_bocsar_product_query_merges_only_the_bounded_page_window() -> None:
    release_id = uuid.uuid4()

    query = release_product_query(
        "bocsar-sparse", release_id, {"maximum_records": 100}, limit=25, offset=50
    )

    assert query.select_params == (release_id, 75, release_id, 75, 25, 50)
    assert query.select_sql.count("LIMIT %s") == 3


def test_property_product_query_uses_the_generation_primary_key_order() -> None:
    query = release_product_query(
        "gnaf-nsw", uuid.uuid4(), {"maximum_records": 50_000}, limit=5_000, offset=0
    )

    assert "ORDER BY gnaf_pid" in query.select_sql


@pytest.mark.parametrize(
    ("profile", "row", "keyset_predicate"),
    [
        ("gnaf-nsw", {"source_address_id": "G-2"}, "gnaf_pid>%s"),
        (
            "psi-sales",
            {"source_business_key": "sale-2", "source_revision": 3},
            "(source_business_key,source_revision)>(%s,%s)",
        ),
        ("schools-master", {"school_code": "S-2"}, "school_code>%s"),
        (
            "bocsar-sparse",
            {
                "geography_kind": "postcode",
                "geography_value": "2000",
                "source_category_key": "theft",
            },
            ">( %s,%s,%s)".replace(" ", ""),
        ),
    ],
)
def test_complete_export_uses_stable_keyset_cursors_without_offset(
    profile: str, row: dict[str, object], keyset_predicate: str
) -> None:
    first = release_export_query(profile, uuid.uuid4(), limit=5000, cursor=None)
    cursor = encode_export_cursor(row, first.cursor_columns)
    following = release_export_query(profile, uuid.uuid4(), limit=5000, cursor=cursor)

    compact_sql = following.select_sql.replace(" ", "").replace("\n", "")
    assert "OFFSET" not in following.select_sql
    assert keyset_predicate.replace(" ", "") in compact_sql
    assert following.select_params[-1] == 5000


def test_product_query_rejects_unregistered_profile_and_normalises_bocsar_dates() -> None:
    with pytest.raises(ConflictError, match="no registered product projection"):
        release_product_query("unknown", uuid.uuid4(), {}, limit=10, offset=0)

    rows = [{"record_kind": "coverage", "observed_months": [date(2025, 1, 1)]}]
    assert normalise_product_rows("bocsar-sparse", rows) == [
        {"record_kind": "coverage", "observed_months": ["2025-01-01"]}
    ]


def test_persistence_serialization_and_row_projection_are_deterministic() -> None:
    identifier = uuid.uuid4()
    timestamp = datetime(2026, 8, 22, 12, 30, tzinfo=UTC)

    assert json_document({"z": identifier, "a": 1}) == f'{{"a":1,"z":"{identifier}"}}'
    assert normalise_row({"id": identifier, "created_at": timestamp, "count": 2}) == {
        "id": str(identifier),
        "created_at": timestamp.isoformat(),
        "count": 2,
    }


@pytest.mark.parametrize(
    "values",
    [
        {},
        {"source_snapshot": {"source_release": "", "objects": [{}]}},
        {"source_snapshot": {"source_release": "2025", "objects": []}},
    ],
)
def test_source_snapshot_evidence_fails_closed(values: dict[str, object]) -> None:
    with pytest.raises(ConflictError, match="source snapshot"):
        require_source_snapshot(values)


def test_publication_receipt_replay_requires_exact_release_and_counts() -> None:
    release_id = uuid.uuid4()
    values = {
        "status": "accepted",
        "schema_version": "propertyscope.school-points.v1",
        "content_sha256": "a" * 64,
        "rows_received": 10,
        "rows_accepted": 10,
        "rows_rejected": 0,
    }
    receipt = {"dataset_release_id": release_id, **values}

    assert receipt_matches_values(receipt, release_id, values)
    assert not receipt_matches_values(receipt, uuid.uuid4(), values)
    assert not receipt_matches_values(receipt, release_id, {**values, "rows_accepted": 9})
