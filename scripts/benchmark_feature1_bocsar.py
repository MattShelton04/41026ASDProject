"""Compare BOCSAR ZIP parsing with a trusted local Git revision, using synthetic data.

The baseline is loaded from this repository's history, never downloaded. Timing and peak
Python allocation are measured in separate passes because tracemalloc slows parsing.
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import subprocess
import sys
import time
import tracemalloc
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from propertyscope_data_platform.adapters import bocsar

SOURCE_PATH = "student-1/backend/src/propertyscope_data_platform/adapters/bocsar.py"


def benchmark(rows: int, baseline: str) -> dict[str, Any]:
    if not 1 <= rows <= 100_000:
        raise ValueError("rows must be 1..100000")
    months = [f"{year}-{month:02}" for year in range(2000, 2026) for month in range(1, 13)]
    header = "Postcode,Offence,Subcategory," + ",".join(months) + "\n"
    # Mostly blank observations reflect the sparse source rather than dense toy data.
    line = (
        "2000,Assault,Total,"
        + ",".join("1" if i % 17 == 0 else "" for i in range(len(months)))
        + "\n"
    )
    archive = io.BytesIO()
    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as output:
        output.writestr("crime.csv", header + line * rows)
    content = archive.getvalue()
    source = subprocess.run(  # noqa: S603 - fixed git argv, no shell
        ["git", "show", f"{baseline}:{SOURCE_PATH}"],  # noqa: S607 - git is resolved from the developer PATH
        check=True,
        capture_output=True,
    ).stdout
    with TemporaryDirectory(prefix="bocsar-benchmark-") as directory:
        path = Path(directory) / "baseline_bocsar.py"
        path.write_bytes(source)
        spec = importlib.util.spec_from_file_location("baseline_bocsar", path)
        if spec is None or spec.loader is None:
            raise RuntimeError("cannot load the baseline BOCSAR adapter")
        old = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = old
        spec.loader.exec_module(old)
        results = {}
        reference = None
        for name, module in ((baseline, old), ("working_tree", bocsar)):
            started = time.perf_counter()
            identity = _consume(module, content)
            seconds = time.perf_counter() - started
            tracemalloc.start()
            _consume(module, content)
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            if reference is not None and reference != identity:
                raise RuntimeError("parser changed observation/coverage counts or totals")
            reference = identity
            results[name] = {"seconds": seconds, "peak_python_bytes": peak, "counts": identity}
    return {
        "scope": "synthetic ZIP parsing only; no publisher/database",
        "source_rows": rows,
        "months": len(months),
        "variants": results,
    }


def _consume(module: ModuleType, content: bytes) -> tuple[int, int, int]:
    observations = coverage = total = 0
    for record in module.iter_bocsar_archive(content, geography_kind="postcode", maximum_rows=None):
        if isinstance(record, module.CrimeObservation):
            observations += 1
            total += record.count
        else:
            coverage += 1
    return observations, coverage, total


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=10_000)
    parser.add_argument("--baseline", default="9459a11")
    args = parser.parse_args()
    print(json.dumps(benchmark(args.rows, args.baseline), indent=2))
