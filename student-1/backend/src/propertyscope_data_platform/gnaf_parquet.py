"""Bounded typed handoff for G-NAF; normalization remains owned by the loader."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

GNAF_PARQUET_MEDIA_TYPE = "application/vnd.apache.parquet"
GNAF_PARQUET_SCHEMA_VERSION = "propertyscope.canonical-gnaf-parquet.v1"
GNAF_PARQUET_BATCH_ROWS = 65_536


def gnaf_parquet_schema() -> pa.Schema:
    """Source values before the existing loader normalization and row hash."""
    return pa.schema(
        [
            pa.field("gnaf_pid", pa.string(), nullable=False),
            pa.field("property_ref", pa.string()),
            pa.field("address_display", pa.string(), nullable=False),
            pa.field("flat_type", pa.string()),
            pa.field("unit_number", pa.string()),
            pa.field("street_number_first", pa.int32()),
            pa.field("street_number_suffix", pa.string()),
            pa.field("street_number_last", pa.int32()),
            pa.field("street_name", pa.string()),
            pa.field("street_type", pa.string()),
            pa.field("locality", pa.string(), nullable=False),
            pa.field("postcode", pa.string(), nullable=False),
            pa.field("source_status", pa.string(), nullable=False),
            pa.field("geocode_type", pa.string(), nullable=False),
            pa.field("source_crs", pa.int32(), nullable=False),
            pa.field("latitude", pa.float64(), nullable=False),
            pa.field("longitude", pa.float64(), nullable=False),
        ],
        metadata={
            b"propertyscope.schema_version": GNAF_PARQUET_SCHEMA_VERSION.encode(),
            b"propertyscope.import_profile": b"gnaf-nsw",
        },
    )


def write_gnaf_parquet(
    destination: Path,
    records: Iterable[Mapping[str, Any]],
    *,
    batch_rows: int = GNAF_PARQUET_BATCH_ROWS,
) -> int:
    """Retain source order with bounded Zstandard row groups and no JSON intermediate."""
    if not 1 <= batch_rows <= GNAF_PARQUET_BATCH_ROWS:
        raise ValueError("G-NAF Parquet batch_rows must be between 1 and 65536")
    schema = gnaf_parquet_schema()
    count = 0
    rows: list[Mapping[str, Any]] = []
    with pq.ParquetWriter(
        destination,
        schema,
        compression="zstd",
        compression_level=3,
        use_dictionary=[
            "flat_type",
            "street_type",
            "locality",
            "postcode",
            "source_status",
            "geocode_type",
            "source_crs",
        ],
    ) as writer:
        for record in records:
            rows.append(record)
            count += 1
            if len(rows) == batch_rows:
                writer.write_table(pa.Table.from_pylist(rows, schema=schema))
                rows.clear()
        if rows:
            writer.write_table(pa.Table.from_pylist(rows, schema=schema))
    if count == 0:
        destination.unlink(missing_ok=True)
        raise ValueError("canonical G-NAF artifact must not be empty")
    return count
