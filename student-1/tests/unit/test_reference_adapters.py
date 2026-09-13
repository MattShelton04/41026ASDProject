from __future__ import annotations

import io
import json
from collections.abc import Iterator
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

import httpx
import pytest
import shapefile  # type: ignore[import-untyped]

from propertyscope_data_platform.adapters import reference
from propertyscope_data_platform.adapters.abs_cpi import (
    CPI_SERIES,
    discover_abs_cpi,
    iter_abs_cpi_records,
    parse_abs_cpi_csv,
)


def _cpi_csv(region: str, frequency: str) -> bytes:
    region_name = "Sydney" if region == "1" else "Australia"
    frequency_name = "Monthly" if frequency == "M" else "Quarterly"
    periods = ("2025-10", "2025-09") if frequency == "M" else ("2025-Q4", "2025-Q3")
    header = (
        "STRUCTURE,STRUCTURE_ID,MEASURE,Measure,INDEX,Index,TSEST,Adjustment Type,"
        "REGION,Region,FREQ,Frequency,TIME_PERIOD,OBS_VALUE,UNIT_MEASURE,"
        "Unit of Measure,OBS_STATUS,BASE_PERIOD,Reference Base Period\n"
    )
    rows = "".join(
        f"DATAFLOW,ABS:CPI(2.0.0),1,Index numbers,10001,All groups CPI,10,Original,"
        f"{region},{region_name},{frequency},{frequency_name},{period},{value},IN,"
        f"Index Numbers,,25,Sep 2025 = 100.0\n"
        for period, value in zip(periods, ("101.25", "100"), strict=True)
    )
    return (header + rows).encode()


def test_abs_cpi_parser_sorts_periods_and_preserves_new_reference_basis() -> None:
    records = parse_abs_cpi_csv(_cpi_csv("1", "M"), CPI_SERIES[0])

    assert [record["period"] for record in records] == ["2025-09", "2025-10"]
    assert records[0]["index_value"] == 100.0
    assert records[0]["reference_basis"] == "Sep 2025 = 100.0"


def test_abs_cpi_parser_rejects_reference_basis_drift() -> None:
    content = _cpi_csv("1", "M").replace(b"Sep 2025 = 100.0", b"2011-12 = 100.0")

    with pytest.raises(ValueError, match="outside the registered series"):
        parse_abs_cpi_csv(content, CPI_SERIES[0])


def test_abs_cpi_discovery_and_iteration_require_all_exact_series() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        key = request.url.path.rsplit("/", 1)[-1]
        parts = key.split(".")
        return httpx.Response(200, content=_cpi_csv(parts[3], parts[4]))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        objects = discover_abs_cpi(client)
        records = list(iter_abs_cpi_records(client, objects))

    assert len(objects) == 4
    assert len(records) == 8
    assert {record["geometry"] for record in records} == {None}
    assert records[0]["valid_from"] in {"2025-07-01", "2025-09-01"}


def test_arcgis_profile_uses_fixed_nsw_filters_and_stable_codes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def discover(
        _client: httpx.Client, url: str, logical_key: str, *, where: str
    ) -> dict[str, Any]:
        return {
            "logical_key": logical_key,
            "url": url,
            "where": where,
            "complete": True,
            "source_crs": "EPSG:3857",
        }

    def features(_client: httpx.Client, descriptor: dict[str, Any]) -> Iterator[dict[str, Any]]:
        if "SAL" in descriptor["url"]:
            properties = {
                "sal_code_2021": "10002",
                "sal_name_2021": "Abbotsbury",
                "state_code_2021": "1",
                "area_albers_sqkm": 4.9788,
            }
        else:
            properties = {
                "lga_code_2021": "10050",
                "lga_name_2021": "Albury",
                "state_code_2021": "1",
                "area_albers_sqkm": 305.6386,
            }
        yield {
            "type": "Feature",
            "properties": properties,
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[150.0, -34.0], [151.0, -34.0], [150.0, -34.0]]],
            },
        }

    monkeypatch.setattr(reference, "discover_arcgis_layer", discover)
    monkeypatch.setattr(reference, "iter_arcgis_features", features)

    with httpx.Client() as client:
        objects = reference.discover_reference_sources("abs-geography-2021", client)
        records = list(reference.iter_reference_records("abs-geography-2021", client, objects))

    assert {item["where"] for item in objects} == {"state_code_2021='1'"}
    assert {item["record_id"] for item in records} == {
        "abs-sal-2021:10002",
        "abs-lga-2021:10050",
    }


def test_amenity_scope_includes_libraries_and_bounded_protected_reserves() -> None:
    specs = reference._ARC_BY_PROFILE["nsw-amenities"]

    assert len(specs) == 17
    library = next(item for item in specs if item.logical_key == "amenity-library")
    reserve = next(item for item in specs if item.logical_key == "amenity-protected-reserve")
    assert library.where == "classsubtype=2 AND buildingcomplextype=11"
    assert reserve.coverage_note is not None
    assert "council-managed urban park" in reserve.coverage_note


def test_school_catchment_archive_preserves_future_grade_years() -> None:
    content = _catchment_archive()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=content,
            headers={
                "content-type": "application/zip",
                "last-modified": "Sun, 06 Sep 2026 23:38:50 GMT",
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        objects = reference.discover_reference_sources("nsw-school-catchments", client)
        records = list(reference.iter_reference_records("nsw-school-catchments", client, objects))

    assert objects[0]["count"] == 3
    assert {record["layer"] for record in records} == {
        "school-primary-catchment",
        "school-secondary-catchment",
        "school-future-catchment",
    }
    future = next(record for record in records if record["layer"] == "school-future-catchment")
    assert future["attributes"]["grades"]["KINDERGART"] == 2027
    assert future["attributes"]["publisher_add_date"] == "2026-05-07"
    assert future["valid_from"] is None
    assert future["source_crs"] == "EPSG:4283"
    assert future["geometry"]["type"] == "Polygon"


def test_school_catchment_archive_rejects_missing_layer() -> None:
    content = _catchment_archive(skip="catchments_future.prj")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content, headers={"content-type": "application/zip"})

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(ValueError, match="members"),
    ):
        reference.discover_reference_sources("nsw-school-catchments", client)


def test_arcgis_open_end_sentinel_is_not_exposed_as_a_real_validity_date() -> None:
    assert (
        reference._first_esri_date(
            {"enddate": 32_503_680_000_000}, "enddate", date_only=True, open_ended=True
        )
        is None
    )


def test_strata_rows_use_publisher_row_id_when_a_scheme_spans_localities() -> None:
    spec = reference._STRATA[0]
    descriptor = {"source_crs": "EPSG:7844"}
    geometry = {
        "type": "Polygon",
        "coordinates": [[[151.6, -32.9], [151.7, -32.9], [151.6, -32.8], [151.6, -32.9]]],
    }
    first = reference._project_arcgis_feature(
        spec,
        descriptor,
        {
            "geometry": geometry,
            "properties": {
                "rid": 55738,
                "plannumber": 69436,
                "planlabel": "SP69436",
                "registrationdate": 1_054_512_000_000,
                "address": "182 LAKE ROAD ELERMORE VALE",
            },
        },
    )
    second = reference._project_arcgis_feature(
        spec,
        descriptor,
        {
            "geometry": geometry,
            "properties": {
                "rid": 55739,
                "plannumber": 69436,
                "planlabel": "SP69436",
                "registrationdate": 1_054_512_000_000,
                "address": "182-222 LAKE ROAD GLENDALE",
            },
        },
    )

    assert first["record_id"] == "nsw-strata-scheme:55738"
    assert second["record_id"] == "nsw-strata-scheme:55739"
    assert first["attributes"]["plannumber"] == second["attributes"]["plannumber"] == 69436


def _catchment_archive(*, skip: str | None = None) -> bytes:
    output = io.BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("catchment_sf_info.json", json.dumps({"current_enrolment_year": 2026}))
        for stem in reference._CATCHMENT_STEMS:
            components = _shapefile_components(future=stem.endswith("future"))
            for suffix, content in components.items():
                member = f"{stem}.{suffix}"
                if member != skip:
                    archive.writestr(member, content)
    return output.getvalue()


def _shapefile_components(*, future: bool) -> dict[str, bytes]:
    shp = io.BytesIO()
    shx = io.BytesIO()
    dbf = io.BytesIO()
    writer = shapefile.Writer(shp=shp, shx=shx, dbf=dbf, shapeType=shapefile.POLYGON)
    for field in reference._CATCHMENT_FIELDS:
        if future and field in reference._GRADE_FIELDS:
            writer.field(field, "N", size=6, decimal=0)
        else:
            size = 50 if field == "USE_DESC" else 20
            writer.field(field, "C", size=size)
    writer.poly([[[150.0, -34.0], [151.0, -34.0], [151.0, -35.0], [150.0, -34.0]]])
    values: list[Any] = [
        "3970" if future else "2060",
        "PRIMARY",
        "Example School",
        "20260507",
    ]
    values.extend([2027] * 7 + [0] * 6 if future else ["Y"] * 7 + ["N"] * 6)
    values.append("")
    writer.record(*values)
    writer.close()
    projection = (
        'GEOGCS["GCS_GDA_1994",DATUM["D_GDA_1994",SPHEROID["GRS_1980",'
        '6378137.0,298.257222101]],AUTHORITY["EPSG",4283]]'
    )
    return {
        "shp": shp.getvalue(),
        "shx": shx.getvalue(),
        "dbf": dbf.getvalue(),
        "prj": projection.encode(),
    }
