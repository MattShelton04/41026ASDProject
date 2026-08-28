from __future__ import annotations

from pathlib import Path

import pytest

from propertyscope_data_platform.adapters import parse_property_fixture

ROOT = Path(__file__).resolve().parents[2]


def test_fixture_parser_is_strict_and_imports_every_fixture_row() -> None:
    content = (ROOT / "config" / "fixtures" / "property-snapshot.csv").read_bytes()
    records = parse_property_fixture(content)
    assert len(records) == 3
    assert records[2].display_address.startswith("UNIT 3")


def test_fixture_parser_rejects_header_drift() -> None:
    with pytest.raises(ValueError, match="headers"):
        parse_property_fixture(b"property_ref,address\n123,x\n")
