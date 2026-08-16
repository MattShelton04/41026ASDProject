from __future__ import annotations

import io
from datetime import date
from pathlib import Path
from typing import cast
from zipfile import ZipFile

import httpx
import pytest

from propertyscope_data_platform.adapters.bocsar import parse_bocsar_archive, parse_bocsar_csv
from propertyscope_data_platform.adapters.gnaf import (
    inspect_gnaf_archive,
    parse_gnaf_archive_path,
    select_geocode,
)
from propertyscope_data_platform.adapters.psi import (
    iter_psi_archive,
    parse_psi_archive,
    parse_psi_b_record,
)
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
        runner._live_document({}, stage="acquire", profile="spatial-features")


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


def test_bocsar_archive_filters_geography_and_months() -> None:
    stream = io.BytesIO()
    with ZipFile(stream, "w") as archive:
        archive.writestr(
            "PostcodeData26Q2.csv",
            "Postcode,Offence,Subcategory,Dec 2024,Jan 2025,Feb 2025\n"
            "2000,Theft,Other,7,2,0\n2007,Theft,Other,8,9,10\n",
        )
    observations, coverage = parse_bocsar_archive(
        stream.getvalue(),
        geography_kind="postcode",
        geography_values=frozenset({"2000"}),
        start_month=date(2025, 1, 1),
        end_month=date(2025, 2, 1),
        maximum_rows=10,
        maximum_records=10,
    )
    assert [(item.geography_value, item.count) for item in observations] == [("2000", 2)]
    assert coverage[0].observed_months == (date(2025, 1, 1), date(2025, 2, 1))


def test_psi_source_key_and_hectare_conversion() -> None:
    sale = parse_psi_b_record(
        ("001", "P1", "2", "20250101", "20250201", "900000", "1.5", "H", "1 ROAD", "D1"),
        source_year=2025,
    )
    assert sale.source_business_key == "001:P1:2"
    assert sale.area_square_metres == 15000


def test_psi_archive_parses_nested_current_format_and_caps_records() -> None:
    nested = io.BytesIO()
    with ZipFile(nested, "w") as archive:
        archive.writestr(
            "20250101.DAT",
            "B;001;P1;2;20250101;;1;10;ROAD;SYDNEY;2000;1.5;H;20250101;"
            "20250201;900000;R;R;;;X;;;D1\n"
            "B;001;P2;1;20250101;;2;10;ROAD;SYDNEY;2000;500;M;20250101;"
            "20250201;800000;R;R;;;X;;;D2\n",
        )
    outer = io.BytesIO()
    with ZipFile(outer, "w") as archive:
        archive.writestr("week.zip", nested.getvalue())
    sales = parse_psi_archive(outer.getvalue(), source_year=2025, maximum_records=1)
    assert len(sales) == 1
    assert sales[0].source_business_key == "001:P1:2"
    assert sales[0].area_square_metres == 15000


def test_psi_archive_full_parse_has_no_implicit_record_cap() -> None:
    stream = io.BytesIO()
    with ZipFile(stream, "w") as archive:
        archive.writestr(
            "20250106.DAT",
            "".join(
                f"B;001;P{index};1;20250101;;1;10;ROAD;SYDNEY;2000;500;M;"
                f"20250101;20250201;{800000 + index};R;R;;;X;;;D{index}\n"
                for index in range(50_001)
            ),
        )

    assert sum(1 for _ in iter_psi_archive(stream.getvalue(), source_year=2025)) == 50_001


def test_psi_archive_parses_pre_2001_root_dat_and_deduplicates_retransmission() -> None:
    row = "B;001;X;V1;P1;U1;10;GEORGE ST;SYDNEY;2000;31/12/1999;400000;X;1.5;H\n"
    stream = io.BytesIO()
    with ZipFile(stream, "w") as archive:
        archive.writestr("ARCHIVE_SALES_1999.DAT", row + row)

    sales = tuple(iter_psi_archive(stream.getvalue(), source_year=1999))

    assert len(sales) == 1
    assert sales[0].source_era == "pre-2001"
    assert sales[0].contract_date == date(1999, 12, 31)
    assert sales[0].area_square_metres == 15000


def test_psi_archive_preserves_a_corrected_retransmission_as_a_revision() -> None:
    first = (
        "B;001;P1;2;20250101;;1;10;ROAD;SYDNEY;2000;500;M;20250101;20250201;900000;R;R;;;X;;;D1\n"
    )
    corrected = first.replace("900000", "910000")
    stream = io.BytesIO()
    with ZipFile(stream, "w") as archive:
        archive.writestr("20250101.DAT", first + first + corrected)

    sales = tuple(iter_psi_archive(stream.getvalue(), source_year=2025))

    assert [sale.price_aud for sale in sales] == [900000, 910000]


def test_psi_archive_detects_legacy_rows_inside_official_2001_archive() -> None:
    row = (
        "B;014;ARCHIVE;2026840000000;361622;;8;LORRAINE AV;BERKELEY VALE;2261;"
        "06/02/2001;142000;LOT 52 DP 775484;4.433;H;;EX;A;;;;\n"
    )
    stream = io.BytesIO()
    with ZipFile(stream, "w") as archive:
        archive.writestr("Archive Sales 2001/ARCHIVE_SALES_2001.DAT", row)

    sale = next(iter_psi_archive(stream.getvalue(), source_year=2001))

    assert sale.source_era == "pre-2001"
    assert sale.property_id == "361622"
    assert sale.contract_date == date(2001, 2, 6)
    assert sale.price_aud == 142000
    assert sale.area_unit == "H"
    assert sale.area_square_metres == 44330


def test_runner_retries_transient_control_plane_disconnect(tmp_path: Path) -> None:
    attempts = 0

    def control(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ReadError("connection reset")
        return httpx.Response(200, json={"ok": True})

    runner = AcquisitionRunner(
        RunnerSettings("http://backend", "token", tmp_path, "worker", 0.0, 30, True),
        client=httpx.Client(transport=httpx.MockTransport(control)),
    )

    response = runner._control_request("GET", "http://backend/health")

    assert response.status_code == 200
    assert attempts == 2


def test_psi_archive_accepts_historical_years_with_many_direct_dat_members() -> None:
    stream = io.BytesIO()
    with ZipFile(stream, "w") as archive:
        for index in range(5_001):
            archive.writestr(f"2008/week-{index}/empty-{index}.DAT", "")
        archive.writestr(
            "2008/week-final/001_SALES_DATA.DAT",
            "B;001;P1;1;20250101;;1;10;ROAD;SYDNEY;2000;500;M;20250101;"
            "20250201;800000;R;R;;;X;;;D1\n",
        )

    sales = tuple(iter_psi_archive(stream.getvalue(), source_year=2008))

    assert len(sales) == 1
    assert sales[0].source_business_key == "001:P1:1"


def test_psi_downloader_uses_verified_ranges_after_publisher_403(tmp_path: Path) -> None:
    archive = io.BytesIO()
    with ZipFile(archive, "w") as stream:
        stream.writestr("sale.DAT", "B;001;P1;1")
    payload = archive.getvalue()

    def source(request: httpx.Request) -> httpx.Response:
        if "Range" not in request.headers:
            return httpx.Response(403, content=b"publisher policy")
        assert request.headers["Range"].startswith("bytes=0-")
        return httpx.Response(
            206,
            content=payload,
            headers={"Content-Range": f"bytes 0-{len(payload) - 1}/{len(payload)}"},
        )

    runner = AcquisitionRunner(
        RunnerSettings("http://backend", "token", tmp_path, "worker", 0.1, 30, True),
        client=httpx.Client(transport=httpx.MockTransport(source)),
    )
    downloaded = runner._download_psi_archive(
        "https://www.valuergeneral.nsw.gov.au/x.zip", maximum_bytes=100_000
    )
    assert downloaded == payload


def test_live_psi_reuses_bounded_official_archive_cache(tmp_path: Path) -> None:
    cache = tmp_path / "psi"
    cache.mkdir()
    archive = io.BytesIO()
    with ZipFile(archive, "w") as stream:
        stream.writestr(
            "20250101.DAT",
            "B;001;P1;1;20250101;;1;10;ROAD;SYDNEY;2000;500;M;20250101;"
            "20250201;800000;R;R;;;X;;;D1\n",
        )
    (cache / "2025.zip").write_bytes(archive.getvalue())

    def no_network(_: httpx.Request) -> httpx.Response:
        raise AssertionError("a cached official PSI year must not contact the publisher")

    runner = AcquisitionRunner(
        RunnerSettings(
            "http://backend",
            "token",
            tmp_path / "artifacts",
            "worker",
            0.1,
            30,
            True,
            psi_archive_root=cache,
        ),
        client=httpx.Client(transport=httpx.MockTransport(no_network)),
    )
    document, records = runner._live_document(
        {
            "max_bytes": 1_000_000,
            "max_rows": 10,
            "partition_json": {"profile": "full-data", "years": [2025]},
        },
        stage="acquire",
        profile="psi-sales",
    )

    assert records[0]["source_business_key"] == "001:P1:1"
    assert cast(dict[str, object], document["source"])["cached_source_years"] == [2025]
    assert runner._live_objects("psi-sales", {"years": [2025]})[0]["cached"] is True


def test_live_bocsar_runner_emits_real_canonical_records(tmp_path: Path) -> None:
    stream = io.BytesIO()
    with ZipFile(stream, "w") as archive:
        archive.writestr(
            "PostcodeData26Q2.csv",
            "Postcode,Offence,Subcategory,Jan 2025\n2000,Theft,Other,3\n",
        )

    def source(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "bocsarblob.blob.core.windows.net"
        return httpx.Response(
            200, content=stream.getvalue(), headers={"Content-Type": "application/zip"}
        )

    runner = AcquisitionRunner(
        RunnerSettings("http://backend", "token", tmp_path, "worker", 0.1, 30, True),
        client=httpx.Client(transport=httpx.MockTransport(source)),
    )
    document, records = runner._live_document(
        {
            "max_bytes": 1_000_000,
            "max_rows": 10,
            "partition_json": {
                "geography_kind": "postcode",
                "geography_values": ["2000"],
                "start_month": "2025-01",
                "end_month": "2025-01",
            },
        },
        stage="acquire",
        profile="bocsar-sparse",
    )
    assert cast(dict[str, object], document["source"])["real_source"] is True
    assert {record["record_kind"] for record in records} == {"observation", "coverage"}


def test_gnaf_requires_members_and_selects_preferred_geocode() -> None:
    stream = io.BytesIO()
    with ZipFile(stream, "w") as archive:
        for suffix in (
            "NSW_ADDRESS_DETAIL_psv.psv",
            "NSW_ADDRESS_DEFAULT_GEOCODE_psv.psv",
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


def test_gnaf_streaming_join_preserves_units_and_declared_crs(tmp_path: Path) -> None:
    path = tmp_path / "gnaf.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr(
            "Standard/NSW_LOCALITY_psv.psv",
            "LOCALITY_PID|LOCALITY_NAME|PRIMARY_POSTCODE\nL1|Sydney|2000\n",
        )
        archive.writestr(
            "Standard/NSW_STREET_LOCALITY_psv.psv",
            "STREET_LOCALITY_PID|STREET_NAME|STREET_TYPE_CODE|LOCALITY_PID\nS1|GEORGE|ST|L1\n",
        )
        archive.writestr(
            "Standard/NSW_ADDRESS_DETAIL_psv.psv",
            "ADDRESS_DETAIL_PID|DATE_RETIRED|FLAT_TYPE_CODE|FLAT_NUMBER|NUMBER_FIRST|"
            "NUMBER_FIRST_SUFFIX|NUMBER_LAST|NUMBER_LAST_SUFFIX|STREET_LOCALITY_PID|"
            "LOCALITY_PID|POSTCODE\nA1||UNIT|12|100|A|||S1|L1|2000\n",
        )
        archive.writestr(
            "Standard/NSW_ADDRESS_DEFAULT_GEOCODE_psv.psv",
            "ADDRESS_DETAIL_PID|GEOCODE_TYPE_CODE|LONGITUDE|LATITUDE\nA1|PC|151.2|-33.86\n",
        )
    record = parse_gnaf_archive_path(path, declared_crs="GDA2020", maximum_records=10)[0]
    assert record.gnaf_pid == "A1"
    assert record.address_display == "UNIT 12/100A GEORGE ST, SYDNEY NSW 2000"
    assert record.source_crs == 7844


def test_source_parsers_enforce_bounds() -> None:
    with pytest.raises(ValueError, match="row limit"):
        parse_bocsar_csv(
            b"Postcode,Offence,Subcategory,Jan 2025\n2000,A,B,1\n",
            geography_kind="postcode",
            maximum_rows=0,
        )
