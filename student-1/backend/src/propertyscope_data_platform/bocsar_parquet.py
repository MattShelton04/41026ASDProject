"""Typed canonical Parquet writer for sparse BOCSAR imports."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from propertyscope_data_platform.adapters.bocsar import CrimeCoverage, CrimeObservation

BOCSAR_PARQUET_MEDIA_TYPE = "application/vnd.apache.parquet"
BOCSAR_PARQUET_SCHEMA_VERSION = "propertyscope.canonical-bocsar-parquet.v1"
BOCSAR_PARQUET_BATCH_ROWS = 65_536

_SCHEMA_METADATA = {
    b"propertyscope.schema_version": BOCSAR_PARQUET_SCHEMA_VERSION.encode(),
    b"propertyscope.import_profile": b"bocsar-sparse",
    b"propertyscope.zero_semantics": b"coverage-evidence-required",
    b"propertyscope.sha256_encoding": b"fixed-size-binary-32",
}


def bocsar_parquet_schema() -> pa.Schema:
    """Return the exact v1 Arrow schema written into canonical BOCSAR artifacts."""
    return pa.schema(
        [
            pa.field("record_kind", pa.string(), nullable=False),
            pa.field("geography_kind", pa.string(), nullable=False),
            pa.field("geography_value", pa.string(), nullable=False),
            pa.field("source_category_key", pa.string(), nullable=False),
            pa.field("offence_label", pa.string()),
            pa.field("subcategory_label", pa.string()),
            pa.field("month", pa.date32()),
            pa.field("count", pa.int32()),
            pa.field("observed_months", pa.list_(pa.date32())),
            pa.field("first_month", pa.date32()),
            pa.field("last_month", pa.date32()),
            pa.field("month_count", pa.int32()),
            pa.field("blank_means_observed_zero", pa.bool_()),
            pa.field("completeness_sha256", pa.binary(32)),
            pa.field("source_row_sha256", pa.binary(32), nullable=False),
        ],
        metadata=_SCHEMA_METADATA,
    )


def write_bocsar_parquet(
    destination: Path,
    records: Iterable[CrimeObservation | CrimeCoverage],
    *,
    batch_rows: int = BOCSAR_PARQUET_BATCH_ROWS,
) -> int:
    """Write a bounded-memory, deterministic sparse artifact and return its row count."""
    if batch_rows < 1:
        raise ValueError("BOCSAR Parquet batch_rows must be positive")
    schema = bocsar_parquet_schema()
    rows: list[dict[str, Any]] = []
    row_count = 0
    writer = pq.ParquetWriter(
        destination,
        schema,
        version="2.6",
        compression="zstd",
        compression_level=3,
        use_dictionary=(
            "record_kind",
            "geography_kind",
            "geography_value",
            "source_category_key",
            "offence_label",
            "subcategory_label",
        ),
        write_statistics=True,
    )
    try:
        for record in records:
            rows.append(_parquet_row(record))
            row_count += 1
            if len(rows) >= batch_rows:
                _write_rows(writer, rows, schema)
                rows.clear()
        if rows:
            _write_rows(writer, rows, schema)
    finally:
        writer.close()
    if row_count == 0:
        destination.unlink(missing_ok=True)
        raise ValueError("canonical BOCSAR artifact must not be empty")
    return row_count


def _write_rows(writer: pq.ParquetWriter, rows: list[dict[str, Any]], schema: pa.Schema) -> None:
    writer.write_table(pa.Table.from_pylist(rows, schema=schema), row_group_size=len(rows))


def _parquet_row(record: CrimeObservation | CrimeCoverage) -> dict[str, Any]:
    common: dict[str, Any] = {
        "record_kind": "observation" if isinstance(record, CrimeObservation) else "coverage",
        "geography_kind": record.geography_kind,
        "geography_value": record.geography_value,
        "source_category_key": record.category_key,
    }
    _validate_common(common)
    if isinstance(record, CrimeObservation):
        if not record.offence_label.strip() or not record.subcategory_label.strip():
            raise ValueError("BOCSAR observation labels must not be blank")
        if record.count < 1 or record.count > 2_147_483_647:
            raise ValueError("BOCSAR observation count exceeds PostgreSQL INTEGER range")
        canonical = {
            **common,
            "offence_label": record.offence_label.strip(),
            "subcategory_label": record.subcategory_label.strip(),
            "month": record.month.isoformat(),
            "count": record.count,
            "month_or_coverage": record.month.isoformat(),
        }
        return {
            **common,
            "offence_label": canonical["offence_label"],
            "subcategory_label": canonical["subcategory_label"],
            "month": record.month,
            "count": record.count,
            "source_row_sha256": _canonical_sha256(canonical),
        }

    month_values = tuple(month.isoformat() for month in record.observed_months)
    if not month_values or month_values != tuple(sorted(set(month_values))):
        raise ValueError("BOCSAR coverage months must be non-empty, sorted and unique")
    completeness = hashlib.sha256(json.dumps(month_values, separators=(",", ":")).encode()).digest()
    canonical = {
        **common,
        "observed_months": month_values,
        "first_month": month_values[0],
        "last_month": month_values[-1],
        "month_count": len(month_values),
        "blank_means_observed_zero": record.blank_means_observed_zero,
        "completeness_sha256": completeness.hex(),
        "month_or_coverage": "coverage",
    }
    return {
        **common,
        "observed_months": list(record.observed_months),
        "first_month": record.observed_months[0],
        "last_month": record.observed_months[-1],
        "month_count": len(record.observed_months),
        "blank_means_observed_zero": record.blank_means_observed_zero,
        "completeness_sha256": completeness,
        "source_row_sha256": _canonical_sha256(canonical),
    }


def _validate_common(row: dict[str, Any]) -> None:
    for field in ("geography_value", "source_category_key"):
        value = str(row[field])
        if not value.strip() or len(value.strip()) > 500:
            raise ValueError(f"BOCSAR {field} must be non-empty text")
        row[field] = value.strip()
    kind = str(row["geography_kind"])
    if kind not in {"postcode", "suburb"}:
        raise ValueError("BOCSAR geography_kind must be postcode or suburb")
    if kind == "postcode" and (
        len(str(row["geography_value"])) != 4 or not str(row["geography_value"]).isdigit()
    ):
        raise ValueError("BOCSAR postcodes must preserve four digits")


def _canonical_sha256(row: dict[str, Any]) -> bytes:
    canonical = json.dumps(row, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).digest()
