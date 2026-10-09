"""Compare PSI parsing against a trusted Git revision using an explicit local archive.

No downloads or database writes. Ordered complete sale fingerprints are checked after timing.
Each parser starts with empty date caches; the bounded sample is retained for parity checking.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from propertyscope_data_platform.adapters import psi

SOURCE_PATH = "student-1/backend/src/propertyscope_data_platform/adapters/psi.py"


def benchmark(archive: Path, year: int, rows: int, baseline: str) -> dict[str, Any]:
    if not 1 <= rows <= 250_000:
        raise ValueError("rows must be 1..250000")
    source = subprocess.run(  # noqa: S603 - fixed git argv, no shell
        ["git", "show", f"{baseline}:{SOURCE_PATH}"],  # noqa: S607 - git is resolved from the developer PATH
        check=True,
        capture_output=True,
    ).stdout
    with TemporaryDirectory(prefix="psi-benchmark-") as directory:
        path = Path(directory) / "baseline_psi.py"
        path.write_bytes(source)
        spec = importlib.util.spec_from_file_location("baseline_psi", path)
        if spec is None or spec.loader is None:
            raise RuntimeError("cannot load the baseline PSI adapter")
        old = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = old
        spec.loader.exec_module(old)
        results = {}
        reference = None
        for name, module in ((baseline, old), ("working_tree", psi)):
            for parser in (module._date, module._source_datetime):
                if hasattr(parser, "cache_clear"):
                    parser.cache_clear()
            started = time.perf_counter()
            sales = list(
                module.iter_psi_archive_path(archive, source_year=year, maximum_records=rows)
            )
            seconds = time.perf_counter() - started
            digest = hashlib.sha256()
            for sale in sales:
                # Same historical encoder for both variants, outside the timed parser.
                digest.update(sale.source_business_key.encode())
                digest.update(bytes.fromhex(old._sale_fingerprint(sale)))
            identity = (len(sales), digest.hexdigest())
            if reference is not None and identity != reference:
                raise RuntimeError("PSI parser changed ordered sale identities or facts")
            reference = identity
            results[name] = {"seconds": seconds, "records": identity[0], "row_digest": identity[1]}
            del sales
    return {"scope": "local archive parsing only", "year": year, "variants": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--rows", type=int, default=100_000)
    parser.add_argument("--baseline", default="9459a11")
    args = parser.parse_args()
    print(json.dumps(benchmark(args.archive, args.year, args.rows, args.baseline), indent=2))
