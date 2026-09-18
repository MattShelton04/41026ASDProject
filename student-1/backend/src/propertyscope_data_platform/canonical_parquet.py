"""Writer settings and helpers shared by Feature 1's canonical Parquet artifacts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

CANONICAL_PARQUET_MEDIA_TYPE = "application/vnd.apache.parquet"
CANONICAL_PARQUET_BATCH_ROWS = 65_536
POSTGRES_INTEGER_MAX = 2_147_483_647


def canonical_parquet_writer(
    destination: Path, schema: pa.Schema, *, dictionary_columns: Iterable[str]
) -> pq.ParquetWriter:
    """Open a deterministic Zstandard writer with the project's canonical format options."""
    return pq.ParquetWriter(
        destination,
        schema,
        version="2.6",
        compression="zstd",
        compression_level=3,
        use_dictionary=list(dictionary_columns),
        write_statistics=True,
    )


def write_row_group(
    writer: pq.ParquetWriter, rows: Sequence[Mapping[str, Any]], schema: pa.Schema
) -> None:
    """Write one batch as exactly one row group so batch boundaries remain observable."""
    writer.write_table(pa.Table.from_pylist(rows, schema=schema), row_group_size=len(rows))


def canonical_row_sha256(row: Mapping[str, Any]) -> bytes:
    """Digest a canonical JSON projection of one row for retransmission comparison."""
    canonical = json.dumps(row, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).digest()
