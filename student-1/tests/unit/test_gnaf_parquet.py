from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

from propertyscope_data_platform.gnaf_parquet import gnaf_parquet_schema, write_gnaf_parquet
from propertyscope_data_store.import_profiles import (
    ImportProfileError,
    iter_ndjson_import,
    iter_parquet_import,
)


def _row() -> dict[str, Any]:
    return {
        "gnaf_pid": "GNAF-1",
        "property_ref": None,
        "address_display": "1 Example St",
        "flat_type": None,
        "unit_number": "a",
        "street_number_first": 1,
        "street_number_suffix": "b",
        "street_number_last": None,
        "street_name": "Example",
        "street_type": "ST",
        "locality": "Sydney",
        "postcode": "2000",
        "source_status": "CURRENT",
        "geocode_type": "PC",
        "source_crs": 7844,
        "latitude": -33.86,
        "longitude": 151.2,
    }


def test_parquet_preserves_values_order_normalisation_and_hashes(tmp_path: Path) -> None:
    rows = [_row(), {**_row(), "gnaf_pid": "GNAF-2", "unit_number": None}, _row()]
    path = tmp_path / "gnaf.parquet"
    assert write_gnaf_parquet(path, iter(rows), batch_rows=2) == 3
    assert pq.ParquetFile(path).metadata.num_row_groups == 2
    expected = list(iter_ndjson_import((json.dumps(r).encode() for r in rows), profile="gnaf-nsw"))
    assert list(iter_parquet_import(path, profile="gnaf-nsw")) == expected
    assert expected[0]["unit_number"] == "A"


@pytest.mark.parametrize("change", ["schema", "metadata", "postcode", "coordinates", "empty"])
def test_parquet_rejects_invalid_contract_or_records(tmp_path: Path, change: str) -> None:
    schema = gnaf_parquet_schema()
    row = _row()
    if change == "schema":
        schema = schema.append(pa.field("unexpected", pa.string()))
    if change == "metadata":
        schema = schema.with_metadata({b"propertyscope.schema_version": b"unknown"})
    if change == "postcode":
        row["postcode"] = "20"
    if change == "coordinates":
        row["latitude"] = float("nan")
    path = tmp_path / "bad.parquet"
    pq.write_table(pa.Table.from_pylist([] if change == "empty" else [row], schema=schema), path)
    with pytest.raises(ImportProfileError):
        list(iter_parquet_import(path, profile="gnaf-nsw"))


def test_parquet_rejects_unreadable_and_empty_input(tmp_path: Path) -> None:
    path = tmp_path / "bad.parquet"
    path.write_bytes(b"not parquet")
    with pytest.raises(ImportProfileError, match="unreadable"):
        list(iter_parquet_import(path, profile="gnaf-nsw"))
    with pytest.raises(ValueError, match="empty"):
        write_gnaf_parquet(path, [])
    assert not path.exists()
    with pytest.raises(ValueError, match="batch_rows"):
        write_gnaf_parquet(path, [_row()], batch_rows=0)
