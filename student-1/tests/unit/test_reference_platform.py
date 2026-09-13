"""Producer reference facts preserve source meaning across validation and export."""

from __future__ import annotations

import gzip
import hashlib
import json
import uuid
from collections.abc import Iterator
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import pytest

from propertyscope_data_platform.reference_catalog import REFERENCE_PROFILES
from propertyscope_data_platform.release_builders import (
    BuildContext,
    ReferenceFeatureRecord,
    default_release_builders,
)
from propertyscope_data_platform.runner import RunnerSettings
from propertyscope_data_platform.scope_policy import validate_job_scope
from propertyscope_data_store.import_profiles import ImportProfileError, iter_ndjson_import
from propertyscope_data_store.query_specs import (
    decode_export_cursor,
    encode_export_cursor,
    release_export_query,
)
from propertyscope_data_store.reference_import import (
    REFERENCE_PROFILES as DATABASE_REFERENCE_PROFILES,
)


def _record() -> dict[str, Any]:
    return {
        "record_id": "heritage:18",
        "layer": "heritage",
        "name": "Recorded site",
        "geometry": {"type": "Point", "coordinates": [151.1, -33.8]},
        "attributes": {"OBJECTID": 18, "REFERENCE": "LEP-EXAMPLE", "AEP": None},
        "source_url": "https://example.gov.au/layers/18",
        "source_crs": "EPSG:7844",
        "source_updated_at": "2026-09-01T00:00:00Z",
        "valid_from": None,
        "valid_to": None,
    }


def _normalise(record: dict[str, Any], profile: str = "nsw-planning-controls") -> dict[str, Any]:
    return next(iter(iter_ndjson_import([json.dumps(record).encode()], profile=profile)))


def test_reference_profile_boundaries_are_consistent_and_do_not_allow_subsets() -> None:
    assert DATABASE_REFERENCE_PROFILES == REFERENCE_PROFILES
    for profile in REFERENCE_PROFILES:
        scope = {"profile": "full-data", "all_records": True}
        validated, error = validate_job_scope(
            {"import_profile_key": profile}, scope, run_mode="full_refresh"
        )
        assert error is None and validated == scope
        _, error = validate_job_scope(
            {"import_profile_key": profile},
            {**scope, "maximum_records": 1},
            run_mode="full_refresh",
        )
        assert error is not None and error.code == "invalid_scope"


@pytest.mark.parametrize("profile", sorted(REFERENCE_PROFILES))
def test_reference_import_preserves_nulls_source_attributes_and_hash(profile: str) -> None:
    original = _record()
    normalised = _normalise(original, profile)
    assert {key: normalised[key] for key in original} == original
    expected = hashlib.sha256(
        json.dumps(original, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    assert normalised["source_row_sha256"] == expected


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_url", "http://example.gov.au/source"),
        ("source_url", "https://user:password@example.gov.au/source"),
        ("source_updated_at", "unknown-date"),
        ("attributes", []),
        ("attributes", {"value": float("nan")}),
        ("geometry", {"type": "Point", "coordinates": [151, -33, 1]}),
        ("geometry", {"type": "Point", "coordinates": [300, -33]}),
        ("geometry", {"type": "Point", "coordinates": [True, -33]}),
        ("geometry", {"type": "Polygon", "coordinates": []}),
        ("geometry", {"type": "GeometryCollection", "geometries": []}),
    ],
)
def test_reference_import_rejects_malformed_facts(field: str, value: Any) -> None:
    record = _record()
    record[field] = value
    with pytest.raises(ImportProfileError):
        _normalise(record)


def test_large_official_bushfire_record_has_a_scoped_finite_byte_allowance() -> None:
    record = _record()
    record["attributes"]["publisher_payload"] = "x" * (16 * 1024 * 1024)
    assert _normalise(record, "nsw-bushfire-prone-land")["geometry"] == record["geometry"]
    with pytest.raises(ImportProfileError, match="per-feature byte bound"):
        _normalise(record, "nsw-planning-controls")
    record["attributes"]["publisher_payload"] = "x" * (64 * 1024 * 1024)
    with pytest.raises(ImportProfileError, match="per-feature byte bound"):
        _normalise(record, "nsw-bushfire-prone-land")


@pytest.mark.parametrize("field", ["enddate", "EndDate"])
def test_cached_publisher_open_end_sentinel_normalises_without_losing_source_fact(
    field: str,
) -> None:
    record = _record()
    record["valid_to"] = "3000-01-01T00:00:00+00:00"
    record["attributes"][field] = 32503680000000
    cached = _normalise(record)
    assert cached["valid_to"] is None
    assert cached["attributes"][field] == 32503680000000
    record["valid_to"] = None
    assert _normalise(record)["source_row_sha256"] == cached["source_row_sha256"]


def test_reference_export_preserves_invalid_geometry_and_does_not_invent_aep() -> None:
    row = _normalise(_record())
    row.update(geometry_status="invalid", normalisation_version="1.0.0")
    release_id = uuid.uuid4()
    context = BuildContext(
        release_id=release_id,
        release_version="test-reference-v1",
        dataset_id="nsw-planning-controls",
        target_feature="feature-1",
        candidate_generation_id=release_id,
        import_profile="nsw-planning-controls",
        normalisation_version="1.0.0",
        publisher="Test publisher",
        source="Test source",
        source_release="test-edition",
        source_licence="cc-by",
        licence_url="https://creativecommons.org/licenses/by/4.0/",
        redistribution_policy="attributed-derived-release",
        scope={"profile": "full-data", "all_records": True},
    )
    product = default_release_builders()["reference-feature"].build(
        context, [row], created_at=datetime(2026, 9, 13, tzinfo=UTC)
    )
    exported = json.loads(gzip.decompress(product.content))
    ReferenceFeatureRecord.model_validate(exported)
    assert exported["geometry_status"] == "invalid"
    assert exported["attributes"]["AEP"] is None
    assert exported["source_crs"] == "EPSG:7844"
    assert exported["provenance"]["source_record_sha256"] == row["source_row_sha256"]
    assert product.manifest.download_permitted is True
    assert product.manifest.temporal_coverage is None

    missing = deepcopy(exported)
    missing["geometry"] = None
    with pytest.raises(ValueError, match="geometry and its status disagree"):
        ReferenceFeatureRecord.model_validate(missing)
    missing["geometry_status"] = "not_provided"
    assert ReferenceFeatureRecord.model_validate(missing).geometry is None


def test_reference_export_cursor_is_generation_scoped_and_parameterised() -> None:
    release_id = uuid.uuid4()
    row = {"layer": "literal' layer", "record_id": "identifier"}
    cursor = encode_export_cursor(row, ("layer", "record_id"))
    query = release_export_query("nsw-cadastre", release_id, limit=25, cursor=cursor)
    assert query.select_params == (release_id, row["layer"], row["record_id"], 25)
    assert row["layer"] not in query.select_sql
    assert "dataset_release_id=%s" in query.select_sql
    assert "OFFSET" not in query.select_sql
    assert decode_export_cursor(cursor, query.cursor_columns) == (row["layer"], row["record_id"])


@pytest.mark.parametrize("workers", [0, 5, True])
def test_acquisition_concurrency_has_a_small_explicit_bound(tmp_path: Any, workers: Any) -> None:
    with pytest.raises(ValueError, match="acquisition workers"):
        RunnerSettings(
            "http://backend", "token", tmp_path, "worker", 0.01, 30, acquisition_workers=workers
        )


def test_acquisition_concurrency_is_opt_in_and_environment_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PROPERTYSCOPE_ACQUISITION_WORKERS", raising=False)
    assert RunnerSettings.from_environment().acquisition_workers == 1
    monkeypatch.setenv("PROPERTYSCOPE_ACQUISITION_WORKERS", "2")
    assert RunnerSettings.from_environment().acquisition_workers == 2


@pytest.mark.parametrize("workers", [0, 1])
def test_bfpl_serial_export_projects_each_row_before_consuming_the_next(workers: int) -> None:
    projected: set[str] = set()

    class ObservedRow(dict[str, Any]):
        def get(self, key: str, default: Any = None) -> Any:
            if key == "record_id":
                projected.add(str(self[key]))
            return super().get(key, default)

    def source_rows() -> Iterator[dict[str, Any]]:
        for index in range(3):
            if index:
                assert f"bfpl:{index - 1}" in projected, "Export buffered another large polygon"
            source = _record()
            source["record_id"] = f"bfpl:{index}"
            row = _normalise(source, "nsw-bushfire-prone-land")
            row.update(geometry_status="valid", normalisation_version="1.0.0")
            yield ObservedRow(row)

    release_id = uuid.uuid4()
    context = BuildContext(
        release_id=release_id,
        release_version="test-bfpl-v1",
        dataset_id="nsw-bushfire-prone-land",
        target_feature="feature-1",
        candidate_generation_id=release_id,
        import_profile="nsw-bushfire-prone-land",
        normalisation_version="1.0.0",
        publisher="Test publisher",
        source="Test source",
        source_release="test-edition",
        source_licence="cc-by-4-0",
        licence_url="https://creativecommons.org/licenses/by/4.0/",
        redistribution_policy="attributed-derived-release",
        scope={"profile": "full-data", "all_records": True},
    )
    product = default_release_builders()["reference-feature"].stream(
        context, source_rows(), projection_workers=workers
    )
    content = b"".join(product.chunks())
    records = [json.loads(line) for line in gzip.decompress(content).splitlines()]
    assert [row["record_id"] for row in records] == ["bfpl:0", "bfpl:1", "bfpl:2"]
    assert product.record_count == 3
