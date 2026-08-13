from __future__ import annotations

import io
from zipfile import ZipFile

import pytest

from propertyscope_data_platform.adapters.bocsar import parse_bocsar_csv
from propertyscope_data_platform.adapters.gnaf import inspect_gnaf_archive, select_geocode
from propertyscope_data_platform.adapters.psi import parse_psi_b_record
from propertyscope_data_platform.adapters.schools import parse_schools_csv


def test_schools_preserves_and_normalises_locality() -> None:
    payload = (
        b"School_code,School_name,School_type,Operational_status,Town_suburb,LGA,"
        b"Latitude,Longitude\n1,Example,Primary,Open, North Sydney ,North Sydney,"
        b"-33.84,151.21\n"
    )
    record = parse_schools_csv(payload, maximum_rows=2)[0]
    assert record.locality_original == "North Sydney"
    assert record.locality_normalised == "NORTH SYDNEY"


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
