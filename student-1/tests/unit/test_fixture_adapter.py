from __future__ import annotations

from pathlib import Path

import pytest

from propertyscope_data_platform.adapters import parse_property_fixture

ROOT = Path(__file__).resolve().parents[2]


def test_fixture_parser_is_strict_bounded_and_unit_aware() -> None:
    content = (ROOT / "config" / "fixtures" / "property-snapshot.csv").read_bytes()
    records = parse_property_fixture(content, maximum_rows=3)
    assert len(records) == 3
    assert records[2].display_address.startswith("UNIT 3")
    with pytest.raises(ValueError, match="row limit"):
        parse_property_fixture(content, maximum_rows=2)


def test_fixture_parser_rejects_header_drift() -> None:
    with pytest.raises(ValueError, match="headers"):
        parse_property_fixture(b"property_ref,address\n123,x\n", maximum_rows=10)
