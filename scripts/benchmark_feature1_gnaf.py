"""Measure canonical G-NAF write/read costs; require identical normalized row hashes.

Use --source with a registered legacy canonical NDJSON artifact to measure real rows.
Without it, generate deterministic synthetic addresses. No publisher requests or DB writes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from itertools import islice
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from propertyscope_data_platform.gnaf_parquet import write_gnaf_parquet
from propertyscope_data_store.import_profiles import iter_ndjson_import, iter_parquet_import


def benchmark(rows: int, source: Path | None = None) -> dict[str, Any]:
    if not 1 <= rows <= 250_000:
        raise ValueError("rows must be between 1 and 250000")
    if source:
        with source.open("rb") as stream:
            records = [json.loads(line) for line in islice(stream, rows)]
    else:
        records = [
            {
                "gnaf_pid": f"SYNTHETIC-{i:09}",
                "property_ref": None,
                "address_display": f"{i} EXAMPLE STREET SYDNEY NSW 2000",
                "flat_type": None,
                "unit_number": None,
                "street_number_first": i,
                "street_number_suffix": None,
                "street_number_last": None,
                "street_name": "EXAMPLE",
                "street_type": "STREET",
                "locality": "SYDNEY",
                "postcode": "2000",
                "source_status": "CURRENT",
                "geocode_type": "PC",
                "source_crs": 7844,
                "latitude": -33.8 + i / 1e7,
                "longitude": 151.1 + i / 1e7,
            }
            for i in range(rows)
        ]
    results: dict[str, Any] = {
        "rows": len(records),
        "source": "registered artifact" if source else "synthetic",
        "variants": {},
    }
    reference = None
    with TemporaryDirectory(prefix="gnaf-benchmark-") as directory:
        for variant in ("ndjson", "parquet"):
            path = Path(directory) / variant
            start = time.perf_counter()
            if variant == "ndjson":
                with path.open("wb") as stream:
                    for record in records:
                        stream.write(
                            json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
                            + b"\n"
                        )
            else:
                write_gnaf_parquet(path, records)
            write_seconds = time.perf_counter() - start
            start = time.perf_counter()
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                imported = (
                    iter_ndjson_import(stream, profile="gnaf-nsw")
                    if variant == "ndjson"
                    else iter_parquet_import(path, profile="gnaf-nsw")
                )
                count = 0
                for row in imported:
                    count += 1
                    digest.update(bytes.fromhex(row["source_row_sha256"]))
            read_seconds = time.perf_counter() - start
            identity = (count, digest.hexdigest())
            if reference is not None and identity != reference:
                raise RuntimeError("canonical handoff changed normalized rows or order")
            reference = identity
            results["variants"][variant] = {
                "write_seconds": write_seconds,
                "read_validate_seconds": read_seconds,
                "bytes": path.stat().st_size,
            }
    results["row_hash_digest"] = reference[1] if reference else None
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=100_000)
    parser.add_argument("--source", type=Path)
    args = parser.parse_args()
    print(json.dumps(benchmark(args.rows, args.source), indent=2))
