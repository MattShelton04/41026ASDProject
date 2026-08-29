from __future__ import annotations

import gzip
import hashlib
import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from propertyscope_data_platform.artifacts import LocalArtifactStore
from propertyscope_data_platform.configuration import (
    ConfigurationError,
    load_job_profiles,
    load_source_register,
)
from propertyscope_data_platform.release_builders import (
    BuildContext,
    RegisteredReleaseBuilder,
    default_release_builders,
    resolve_release_builder,
    validate_release_job,
)
from propertyscope_data_platform.runner import (
    AcquisitionRunner,
    RunnerSettings,
    TaskCancelledError,
)

ROOT = Path(__file__).parents[2]
FIXED_TIME = datetime(2026, 8, 16, 1, 2, 3, tzinfo=UTC)


def _settings(tmp_path: Path) -> RunnerSettings:
    return RunnerSettings(
        backend_url="http://backend",
        token="runner-secret",
        artifact_root=tmp_path,
        worker_id="runner-1",
        poll_seconds=0.01,
        lease_seconds=30,
    )


def _context(**changes: Any) -> BuildContext:
    values: dict[str, Any] = {
        "release_id": "60000000-0000-0000-0000-000000000099",
        "release_version": "release-fixture-v1",
        "dataset_id": "fixture-property",
        "target_feature": "feature-1",
        "candidate_generation_id": "60000000-0000-0000-0000-000000000099",
        "import_profile": "property-fixture",
        "normalisation_version": "1.0.0",
        "publisher": "PropertyScope project",
        "source": "Deterministic synthetic property snapshot",
        "source_release": "showcase",
        "source_licence": "synthetic-test-data",
        "licence_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "redistribution_policy": "committed-synthetic-fixture",
        "scope": {"maximum_records": 20, "localities": ["PARRAMATTA"]},
    }
    values.update(changes)
    return BuildContext.model_validate(values)


def _property_row(index: int = 1) -> dict[str, Any]:
    return {
        "source_address_id": f"FIX-{index:03d}",
        "property_ref": None,
        "address_display": f"{index} TEST STREET PARRAMATTA NSW 2150",
        "flat_type": None,
        "unit_number": None,
        "street_number_first": index,
        "street_number_suffix": None,
        "street_number_last": None,
        "street_name": "TEST",
        "street_type": "STREET",
        "locality": "PARRAMATTA",
        "postcode": "2150",
        "source_status": "CURRENT",
        "geocode_type": "FIXTURE",
        "source_crs": 4326,
        "geometry": {"type": "Point", "coordinates": [151.0011, -33.8151]},
        "source_row_sha256": hashlib.sha256(f"fixture-{index}".encode()).hexdigest(),
        "normalisation_version": "1.0.0",
    }


def test_release_cancellation_removes_partial_stream_artifact(tmp_path: Path) -> None:
    def cancelled_rows() -> Any:
        yield _property_row()
        raise TaskCancelledError("Run task cancelled by operator")

    builder = default_release_builders()["property-snapshot"]
    product = builder.stream(_context(), cancelled_rows())

    with pytest.raises(TaskCancelledError, match="cancelled by operator"):
        LocalArtifactStore(tmp_path).put(product.chunks(), media_type=builder.spec.media_type)
    assert not any(path.is_file() for path in tmp_path.rglob("*"))


def test_existing_build_release_defect_is_closed_by_constructing_the_configured_export(
    tmp_path: Path,
) -> None:
    """A live build stage must not merely finalise its canonical-import draft."""
    run_id = "50000000-0000-0000-0000-000000000099"
    release_id = "60000000-0000-0000-0000-000000000099"
    task_id = "40000000-0000-0000-0000-000000000099"
    observed: dict[str, Any] = {}

    def backend(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/release-build-context"):
            return httpx.Response(
                200,
                json={
                    "context": _context().model_dump(mode="json"),
                    "builder": {"key": "property-snapshot", "version": "2.0.0"},
                    "target_contract": "propertyscope.property-snapshot.v1",
                    "release_id": release_id,
                },
            )
        if request.method == "GET" and request.url.path.endswith("/product-records"):
            assert request.url.params["limit"] == "5000"
            return httpx.Response(
                200,
                json={
                    "release_id": release_id,
                    "candidate_generation_id": release_id,
                    "items": [_property_row()],
                    "count": 1,
                    "total": 1,
                    "next_cursor": None,
                },
            )
        if request.method == "POST" and request.url.path.endswith(f"/tasks/{task_id}/artifacts"):
            body = cast(dict[str, Any], json.loads(request.content))
            observed["artifact"] = body
            artifact_path = tmp_path / body["storage_key"]
            content = artifact_path.read_bytes()
            observed["content"] = json.loads(gzip.decompress(content))
            assert hashlib.sha256(content).hexdigest() == body["content_sha256"]
            return httpx.Response(
                201,
                json={
                    "artifact": {"id": "70000000-0000-0000-0000-000000000099", **body},
                    "created": True,
                },
            )
        if request.method == "POST" and request.url.path.endswith("/finalize-release"):
            body = cast(dict[str, Any], json.loads(request.content))
            observed["finalize"] = body
            return httpx.Response(200, json={"release": {"id": release_id, "status": "candidate"}})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    runner = AcquisitionRunner(
        _settings(tmp_path),
        client=httpx.Client(transport=httpx.MockTransport(backend)),
        clock=lambda: FIXED_TIME,
    )
    rows_in, rows_out = runner._execute(
        {
            "id": task_id,
            "ingestion_run_id": run_id,
            "stage": "build_release",
            "logical_key": "06/build_release",
        }
    )

    assert (rows_in, rows_out) == (1, 1)
    assert observed["artifact"]["artifact_kind"] == "release_export"
    assert observed["artifact"]["schema_version"] == "propertyscope.property-snapshot.v1"
    assert observed["content"]["source_address_id"] == "FIX-001"
    assert observed["finalize"]["manifest"]["content_encoding"] == "gzip"
    assert observed["finalize"]["manifest"]["media_type"] == "application/x-ndjson"
    assert observed["finalize"]["artifact_record_id"] == "70000000-0000-0000-0000-000000000099"
    assert (
        observed["finalize"]["manifest"]["content_sha256"] == observed["artifact"]["content_sha256"]
    )
    assert observed["finalize"]["manifest"]["record_count"] == 1
    assert observed["finalize"]["schema_version"] == "propertyscope.property-snapshot.v1"


def test_runner_rejects_an_inconsistent_complete_page_count(tmp_path: Path) -> None:
    def backend(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/release-build-context"):
            return httpx.Response(
                200,
                json={
                    "context": _context(scope={"maximum_records": 1}).model_dump(mode="json"),
                    "builder": {"key": "property-snapshot", "version": "2.0.0"},
                    "target_contract": "propertyscope.property-snapshot.v1",
                    "release_id": "60000000-0000-0000-0000-000000000099",
                },
            )
        if request.url.path.endswith("/product-records"):
            return httpx.Response(
                200,
                json={
                    "release_id": "60000000-0000-0000-0000-000000000099",
                    "candidate_generation_id": "60000000-0000-0000-0000-000000000099",
                    "items": [_property_row()],
                    "total": 2,
                    "next_cursor": None,
                },
            )
        raise AssertionError("runner must fail before registering an over-bound export")

    runner = AcquisitionRunner(
        _settings(tmp_path),
        client=httpx.Client(transport=httpx.MockTransport(backend)),
        clock=lambda: FIXED_TIME,
    )

    with pytest.raises(RuntimeError, match="page count is inconsistent"):
        runner._execute(
            {
                "id": "40000000-0000-0000-0000-000000000099",
                "ingestion_run_id": "50000000-0000-0000-0000-000000000099",
                "stage": "build_release",
                "logical_key": "06/build_release",
            }
        )


def test_discovery_persists_manifest_source_release_evidence(tmp_path: Path) -> None:
    observed: dict[str, Any] = {}

    def backend(request: httpx.Request) -> httpx.Response:
        observed.update(cast(dict[str, Any], json.loads(request.content)))
        return httpx.Response(201, json={"artifact": {"id": str(uuid.uuid4())}, "created": True})

    runner = AcquisitionRunner(
        _settings(tmp_path), client=httpx.Client(transport=httpx.MockTransport(backend))
    )
    runner._execute(
        {
            "id": "40000000-0000-0000-0000-000000000099",
            "ingestion_run_id": "50000000-0000-0000-0000-000000000099",
            "stage": "discover",
            "logical_key": "00/discover",
            "import_profile_key": "property-fixture",
            "partition_json": {"profile": "full-data", "all_records": True},
        }
    )

    assert observed["artifact_kind"] == "source_snapshot"
    assert observed["source_snapshot"]["source_release"] == "fixture-v1"


def test_registered_property_builder_is_byte_deterministic() -> None:
    builder = resolve_release_builder("property-snapshot", "2.0.0")
    rows = [_property_row(2), _property_row(1)]

    first = builder.build(_context(), rows, created_at=FIXED_TIME)
    second = builder.build(_context(), reversed(rows), created_at=FIXED_TIME)

    assert first.content == second.content
    assert first.manifest.content_sha256 == hashlib.sha256(first.content).hexdigest()
    assert first.manifest.record_count == 2
    assert first.manifest.byte_count == len(first.content)


def test_release_byte_bounds_cover_registered_scope_without_widening_other_products() -> None:
    builders = default_release_builders()

    assert all(builder.spec.max_rows is None for builder in builders.values())
    assert all(builder.spec.max_bytes is None for builder in builders.values())
    assert all(builder.spec.content_encoding == "gzip" for builder in builders.values())


def test_property_builder_preserves_published_identity_without_inventing_precision() -> None:
    property_ref = "a0000000-0000-0000-0000-000000000001"
    product = resolve_release_builder("property-snapshot", "2.0.0").build(
        _context(),
        [{**_property_row(), "property_ref": property_ref, "geocode_precision": None}],
        created_at=FIXED_TIME,
    )

    record = json.loads(product.content)["records"][0]
    assert record["property_ref"] == property_ref
    assert record["geocode_precision"] is None


def test_release_builder_registry_fails_closed() -> None:
    with pytest.raises(ConfigurationError, match="unknown release builder"):
        resolve_release_builder("not-registered", "1.0.0")
    with pytest.raises(ConfigurationError, match="unsupported release builder version"):
        resolve_release_builder("property-snapshot", "1.0.0")


def test_sales_builder_preserves_revisions_nulls_and_source_aligned_fields() -> None:
    builder = resolve_release_builder("property-sales", "3.0.0")
    context = _context(
        dataset_id="nsw-psi-sales",
        target_feature="feature-2",
        import_profile="psi-sales",
        redistribution_policy="bounded-derived-release",
    )
    base = {
        "source_era": "post-2001",
        "district_code": "001",
        "property_id": "P1",
        "dealing_id": None,
        "contract_date": None,
        "settlement_date": "2025-02-01",
        "price_aud": None,
        "area_original": "1.5",
        "area_unit": "H",
        "area_square_metres": "15000",
        "property_ref": None,
        "match_tier": "MISS",
        "match_confidence": "0.0000",
        "geographic_precision": "unmatched",
        "source_row_sha256": "b" * 64,
        "normalisation_version": "1.0.0",
        "source_downloaded_at": "2025-01-06 01:05:00",
        "house_number": "178",
        "street_number_first": 178,
        "street_name": "HOPETOUN ST",
        "street_name_normalised": "HOPETOUN",
        "street_type": "STREET",
        "locality": "KURRI KURRI",
        "postcode": "2327",
        "zoning_code": "R3",
        "nature_code": "R",
        "primary_purpose": "RESIDENCE",
    }
    product = builder.build(
        context,
        [
            {**base, "source_business_key": "001:P1:1", "source_revision": 2},
            {**base, "source_business_key": "001:P1:1", "source_revision": 1},
        ],
        created_at=FIXED_TIME,
    )

    payload = json.loads(product.content)
    assert [item["source_revision"] for item in payload["records"]] == [1, 2]
    assert payload["records"][0]["price_aud"] is None
    assert payload["records"][0]["property_ref"] is None
    assert payload["records"][0]["area_original"] == "1.5"
    assert payload["schema_version"] == "propertyscope.property-sales.v2"
    assert payload["records"][0]["street_name"] == "HOPETOUN ST"
    assert payload["records"][0]["zoning_code"] == "R3"


def test_crime_builder_preserves_exact_coverage_and_coverage_only_series() -> None:
    builder = resolve_release_builder("crime-series", "2.0.0")
    context = _context(
        dataset_id="bocsar-crime",
        target_feature="feature-3",
        import_profile="bocsar-sparse",
        redistribution_policy="approved-bounded-extract",
    )
    months = ("2025-01-01", "2025-02-01")
    completeness = hashlib.sha256(json.dumps(months, separators=(",", ":")).encode()).hexdigest()
    common = {
        "geography_kind": "postcode",
        "geography_value": "2000",
        "source_category_key": "fixture-category",
        "normalisation_version": "1.0.0",
    }
    coverage = {
        **common,
        "record_kind": "coverage",
        "observed_months": list(months),
        "first_month": months[0],
        "last_month": months[-1],
        "month_count": 2,
        "blank_means_observed_zero": True,
        "completeness_sha256": completeness,
        "source_row_sha256": "c" * 64,
    }

    product = builder.build(context, [coverage], created_at=FIXED_TIME)

    series = json.loads(product.content)["records"][0]
    assert series["observed_months"] == list(months)
    assert series["observations"] == []
    assert series["blank_means_observed_zero"] is True


def test_crime_builder_accepts_current_official_coverage_history() -> None:
    builder = resolve_release_builder("crime-series", "2.0.0")
    context = _context(
        dataset_id="bocsar-crime",
        target_feature="feature-3",
        import_profile="bocsar-sparse",
        redistribution_policy="approved-bounded-extract",
    )
    months = tuple(
        f"{year}-{month:02d}-01" for year in range(1995, 2027) for month in range(1, 13)
    )[:375]
    completeness = hashlib.sha256(json.dumps(months, separators=(",", ":")).encode()).hexdigest()
    coverage = {
        "record_kind": "coverage",
        "geography_kind": "suburb",
        "geography_value": "Sydney",
        "source_category_key": "fixture-category",
        "observed_months": list(months),
        "first_month": months[0],
        "last_month": months[-1],
        "month_count": len(months),
        "blank_means_observed_zero": True,
        "completeness_sha256": completeness,
        "source_row_sha256": "c" * 64,
        "normalisation_version": "1.0.0",
    }

    product = builder.build(context, [coverage], created_at=FIXED_TIME)

    assert len(json.loads(product.content)["records"][0]["observed_months"]) == 375


def test_school_builder_orders_codes_and_preserves_non_operational_status() -> None:
    builder = resolve_release_builder("school-points", "2.0.0")
    context = _context(
        dataset_id="nsw-government-schools",
        target_feature="feature-3",
        import_profile="schools-master",
        redistribution_policy="approved-bounded-extract",
    )
    base = {
        "school_name": "Example School",
        "school_type": "Primary",
        "locality_original": "Sydney",
        "locality_normalised": "SYDNEY",
        "lga_name": "City of Sydney",
        "geometry": {"type": "Point", "coordinates": [151.2, -33.86]},
        "source_row_sha256": "d" * 64,
        "normalisation_version": "1.0.0",
    }
    product = builder.build(
        context,
        [
            {**base, "school_code": "S0002", "status": "Closed"},
            {**base, "school_code": "S0001", "status": "Open"},
        ],
        created_at=FIXED_TIME,
    )

    records = json.loads(product.content)["records"]
    assert [item["school_code"] for item in records] == ["S0001", "S0002"]
    assert records[1]["operational_status"] == "Closed"


def test_school_builder_accepts_registered_lord_howe_footprint() -> None:
    context = _context(
        dataset_id="nsw-government-schools",
        target_feature="feature-3",
        import_profile="schools-master",
        redistribution_policy="approved-bounded-extract",
    )
    product = resolve_release_builder("school-points", "2.0.0").build(
        context,
        [
            {
                "school_code": "1921",
                "school_name": "Lord Howe Island Central School",
                "school_type": "Central Schools",
                "status": "Open",
                "locality_original": "Lord Howe Island",
                "locality_normalised": "LORD HOWE ISLAND",
                "lga_name": None,
                "geometry": {"type": "Point", "coordinates": [159.069032, -31.530072]},
                "source_row_sha256": "d" * 64,
                "normalisation_version": "1.0.0",
            }
        ],
        created_at=FIXED_TIME,
    )

    assert json.loads(product.content)["records"][0]["longitude"] == 159.069032


def test_every_job_profile_matches_a_complete_release_builder_registration() -> None:
    profiles = load_job_profiles(ROOT / "config" / "job-profiles")
    sources = load_source_register(ROOT / "config" / "source-register.yaml")
    schema_names = {builder.spec.contract for builder in default_release_builders().values()}

    for key in profiles:
        profile = profiles.get_profile(key)
        validate_release_job(
            profile,
            source=sources.get_profile(profile.source_key),
            schema_names=schema_names,
        )


def test_builder_bounds_fail_without_silent_truncation() -> None:
    registered = resolve_release_builder("property-snapshot", "2.0.0")
    row_bounded = RegisteredReleaseBuilder(replace(registered.spec, max_rows=1))
    byte_bounded = RegisteredReleaseBuilder(replace(registered.spec, max_bytes=10))

    with pytest.raises(ValueError, match="row bound"):
        row_bounded.build(_context(), [_property_row(1), _property_row(2)], created_at=FIXED_TIME)
    with pytest.raises(ValueError, match="byte bound"):
        byte_bounded.build(_context(), [_property_row(1)], created_at=FIXED_TIME)


@pytest.mark.parametrize(
    ("change", "schemas", "message"),
    [
        ({"release_builder": {"key": "missing", "version": "1.0.0"}}, None, "unknown"),
        (
            {"release_builder": {"key": "property-snapshot", "version": "1.0.0"}},
            None,
            "unsupported",
        ),
        (
            {"target": {"feature": "feature-1", "contract": "propertyscope.wrong.v1"}},
            None,
            "target contract",
        ),
        (
            {"target": {"feature": "feature-2", "contract": "propertyscope.property-snapshot.v1"}},
            None,
            "target feature",
        ),
        ({}, set(), "schema is absent"),
    ],
)
def test_incomplete_release_registrations_fail_closed(
    change: dict[str, Any], schemas: set[str] | None, message: str
) -> None:
    profiles = load_job_profiles(ROOT / "config" / "job-profiles")
    sources = load_source_register(ROOT / "config" / "source-register.yaml")
    original = profiles.get_profile("fixture-property-full")
    profile = type(original).model_validate({**original.model_dump(mode="python"), **change})
    available = schemas if schemas is not None else {"propertyscope.property-snapshot.v1"}

    with pytest.raises(ConfigurationError, match=message):
        validate_release_job(
            profile,
            source=sources.get_profile(profile.source_key),
            schema_names=available,
        )


def test_runner_rejects_generation_change_during_pagination(tmp_path: Path) -> None:
    run_id = "50000000-0000-0000-0000-000000000098"
    release_id = "60000000-0000-0000-0000-000000000098"
    page = 0
    heartbeat = False

    def backend(request: httpx.Request) -> httpx.Response:
        nonlocal heartbeat, page
        if request.url.path.endswith("/release-build-context"):
            context = _context(
                release_id=release_id,
                candidate_generation_id=release_id,
            )
            return httpx.Response(
                200,
                json={
                    "context": context.model_dump(mode="json"),
                    "builder": {"key": "property-snapshot", "version": "2.0.0"},
                    "target_contract": "propertyscope.property-snapshot.v1",
                    "release_id": release_id,
                },
            )
        if request.url.path.endswith("/heartbeat"):
            heartbeat = True
            return httpx.Response(200, json={"task": {"status": "running"}})
        page += 1
        return httpx.Response(
            200,
            json={
                "release_id": release_id,
                "candidate_generation_id": release_id if page == 1 else str(uuid.uuid4()),
                "items": [_property_row(page)],
                "count": 1,
                "total": 2,
                "next_cursor": "next-page" if page == 1 else None,
            },
        )

    runner = AcquisitionRunner(
        _settings(tmp_path),
        client=httpx.Client(transport=httpx.MockTransport(backend)),
        clock=lambda: FIXED_TIME,
    )

    with pytest.raises(RuntimeError, match="generation changed"):
        runner._execute(
            {
                "id": "40000000-0000-0000-0000-000000000098",
                "ingestion_run_id": run_id,
                "stage": "build_release",
                "logical_key": "06/build_release",
                "lease_token": "lease-1",
            }
        )
    assert heartbeat is True
