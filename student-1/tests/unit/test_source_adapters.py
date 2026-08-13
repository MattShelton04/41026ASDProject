from __future__ import annotations

import io
from pathlib import Path
from typing import cast
from zipfile import ZipFile

import httpx
import pytest

from propertyscope_data_platform.adapters.bocsar import parse_bocsar_csv
from propertyscope_data_platform.adapters.gnaf import inspect_gnaf_archive, select_geocode
from propertyscope_data_platform.adapters.psi import parse_psi_b_record
from propertyscope_data_platform.adapters.schools import parse_schools_csv
from propertyscope_data_platform.runner import AcquisitionRunner, RunnerSettings


def test_schools_preserves_and_normalises_locality() -> None:
    payload = (
        b"School_code,School_name,School_type,Operational_status,Town_suburb,LGA,"
        b"Latitude,Longitude\n1,Example,Primary,Open, North Sydney ,North Sydney,"
        b"-33.84,151.21\n"
    )
    record = parse_schools_csv(payload, maximum_rows=2)[0]
    assert record.locality_original == "North Sydney"
    assert record.locality_normalised == "NORTH SYDNEY"


def test_schools_accepts_current_real_master_headers() -> None:
    payload = (
        b"School_code,School_name,Level_of_schooling,Town_suburb,LGA,Latitude,Longitude\n"
        b"1001,Example Public School,Primary Schools,Sydney,City of Sydney,-33.86,151.20\n"
    )
    record = parse_schools_csv(payload, maximum_rows=2)[0]
    assert record.school_type == "Primary Schools"
    assert record.status == "Open"


def test_schools_accepts_nsw_lord_howe_island_coordinates() -> None:
    payload = (
        b"School_code,School_name,Level_of_schooling,Town_suburb,LGA,Latitude,Longitude\n"
        b"1921,Lord Howe Island Central School,Central Schools,Lord Howe Island,,"
        b"-31.530072,159.069032\n"
    )
    assert parse_schools_csv(payload, maximum_rows=2)[0].school_code == "1921"


def test_full_data_schools_download_invokes_real_parser_with_bounds(tmp_path: Path) -> None:
    payload = (
        b"School_code,School_name,Level_of_schooling,Town_suburb,LGA,Latitude,Longitude\n"
        b"1001,Example Public School,Primary Schools,Sydney,City of Sydney,-33.86,151.20\n"
    )

    def source(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "data.nsw.gov.au"
        return httpx.Response(200, content=payload, headers={"Content-Type": "text/csv"})

    runner = AcquisitionRunner(
        RunnerSettings("http://backend", "token", tmp_path, "worker", 0.1, 30, True),
        client=httpx.Client(transport=httpx.MockTransport(source)),
    )
    document, records = runner._live_document(
        {"max_bytes": 1_000_000, "max_rows": 10}, stage="acquire", profile="schools-master"
    )
    assert cast(dict[str, object], document["source"])["real_source"] is True
    assert records[0]["school_code"] == "1001"


def test_full_data_never_silently_substitutes_unconnected_sources(tmp_path: Path) -> None:
    runner = AcquisitionRunner(
        RunnerSettings("http://backend", "token", tmp_path, "worker", 0.1, 30, True)
    )
    with pytest.raises(RuntimeError, match="no connected live transport"):
        runner._live_document({}, stage="acquire", profile="gnaf-nsw")


def test_full_data_scope_never_falls_back_when_runtime_is_not_opted_in(tmp_path: Path) -> None:
    runner = AcquisitionRunner(
        RunnerSettings("http://backend", "token", tmp_path, "worker", 0.1, 30, False)
    )
    with pytest.raises(RuntimeError, match="explicit full-data runtime profile"):
        runner._execute(
            {
                "stage": "acquire",
                "import_profile_key": "schools-master",
                "partition_json": {"profile": "full-data"},
            }
        )


def test_bocsar_preserves_leading_zero_and_sparse_zero() -> None:
    payload = b"Postcode,Offence,Subcategory,Jan 2025,Feb 2025\n0077,Theft,Other,,3\n"
    observations, coverage = parse_bocsar_csv(payload, geography_kind="postcode", maximum_rows=2)
    assert coverage[0].geography_value == "0077"
    assert len(coverage[0].observed_months) == 2
    assert [item.count for item in observations] == [3]


def test_psi_source_key_and_hectare_conversion() -> None:
    sale = parse_psi_b_record(
        ("001", "P1", "2", "20250101", "20250201", "900000", "1.5", "H", "1 ROAD", "D1"),
        source_year=2025,
    )
    assert sale.source_business_key == "001:P1:2"
    assert sale.area_square_metres == 15000


def test_gnaf_requires_members_and_selects_preferred_geocode() -> None:
    stream = io.BytesIO()
    with ZipFile(stream, "w") as archive:
        for suffix in (
            "NSW_ADDRESS_DETAIL_psv.psv",
            "NSW_DEFAULT_GEOCODE_psv.psv",
            "NSW_LOCALITY_psv.psv",
            "NSW_STREET_LOCALITY_psv.psv",
        ):
            archive.writestr(f"G-NAF/GDA2020/Standard/{suffix}", "x")
    with ZipFile(io.BytesIO(stream.getvalue())) as archive:
        assert inspect_gnaf_archive(archive).coordinate_reference_system == "GDA2020"
    selected = select_geocode(
        (
            {
                "GEOCODE_PID": "2",
                "GEOCODE_TYPE_CODE": "LOCALITY",
                "LATITUDE": "-33",
                "LONGITUDE": "151",
            },
            {
                "GEOCODE_PID": "1",
                "GEOCODE_TYPE_CODE": "PC",
                "LATITUDE": "-33.1",
                "LONGITUDE": "151.1",
            },
        )
    )
    assert selected is not None and selected["GEOCODE_PID"] == "1"


def test_source_parsers_enforce_bounds() -> None:
    with pytest.raises(ValueError, match="row limit"):
        parse_bocsar_csv(
            b"Postcode,Offence,Subcategory,Jan 2025\n2000,A,B,1\n",
            geography_kind="postcode",
            maximum_rows=0,
        )
