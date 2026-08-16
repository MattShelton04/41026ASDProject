from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from propertyscope_data_platform.configuration import (
    ConfigurationError,
    load_job_profiles,
    load_source_register,
)
from propertyscope_data_platform.release_builders import (
    BuildContext,
    default_release_builders,
    resolve_release_builder,
    validate_release_job,
)
from propertyscope_data_platform.runner import AcquisitionRunner, RunnerSettings

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
        "display_address": f"{index} TEST STREET PARRAMATTA NSW 2150",
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
                    "builder": {"key": "property-snapshot", "version": "1.0.0"},
                    "target_contract": "propertyscope.property-snapshot.v1",
                    "release_id": release_id,
                },
            )
        if request.method == "GET" and request.url.path.endswith("/product-records"):
            return httpx.Response(
                200,
                json={"items": [_property_row()], "count": 1, "total": 1, "next_offset": None},
            )
        if request.method == "POST" and request.url.path.endswith(f"/tasks/{task_id}/artifacts"):
            body = cast(dict[str, Any], json.loads(request.content))
            observed["artifact"] = body
            artifact_path = tmp_path / body["storage_key"]
            content = artifact_path.read_bytes()
            observed["content"] = json.loads(content)
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
    assert observed["content"]["schema_version"] == "propertyscope.property-snapshot.v1"
    assert observed["finalize"]["artifact_record_id"] == "70000000-0000-0000-0000-000000000099"
    assert (
        observed["finalize"]["manifest"]["content_sha256"] == observed["artifact"]["content_sha256"]
    )
    assert observed["finalize"]["manifest"]["record_count"] == 1
    assert observed["finalize"]["schema_version"] == "propertyscope.property-snapshot.v1"


def test_registered_property_builder_is_byte_deterministic() -> None:
    builder = resolve_release_builder("property-snapshot", "1.0.0")
    rows = [_property_row(2), _property_row(1)]

    first = builder.build(_context(), rows, created_at=FIXED_TIME)
    second = builder.build(_context(), reversed(rows), created_at=FIXED_TIME)

    assert first.content == second.content
    assert first.manifest.content_sha256 == hashlib.sha256(first.content).hexdigest()
    assert first.manifest.record_count == 2
    assert first.manifest.byte_count == len(first.content)


def test_release_builder_registry_fails_closed() -> None:
    with pytest.raises(ConfigurationError, match="unknown release builder"):
        resolve_release_builder("not-registered", "1.0.0")
    with pytest.raises(ConfigurationError, match="unsupported release builder version"):
        resolve_release_builder("property-snapshot", "2.0.0")


def test_sales_builder_preserves_revisions_nulls_and_source_aligned_fields() -> None:
    builder = resolve_release_builder("property-sales", "1.0.0")
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


def test_crime_builder_preserves_exact_coverage_and_coverage_only_series() -> None:
    builder = resolve_release_builder("crime-series", "1.0.0")
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


def test_school_builder_orders_codes_and_preserves_non_operational_status() -> None:
    builder = resolve_release_builder("school-points", "1.0.0")
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
