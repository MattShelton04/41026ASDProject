"""Measure read-only Feature 1 HTTP flows against an explicitly running stack.

Run before and after a change with the same --property-ref and accepted data.
This does not acquire, publish, import, or alter any records. SQL plans and browser
render timings are separate evidence; HTTP measurements include both service hops.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_QUERIES = (
    "Parramatta",
    "Sutherland",
    "2000",
    "Glebe",
    "Sydney",
    "Sydney NSW 2000",
    "St Marys",
    "George",
    "North",
    "11 George",
    "zzzznonexistent",
)


@dataclass(frozen=True)
class Case:
    label: str
    path: str
    body: dict[str, Any] | None = None


def read_case(base_url: str, case: Case) -> tuple[dict[str, Any], dict[str, Any]]:
    start = time.perf_counter()
    payload = json.dumps(case.body).encode() if case.body is not None else None
    request = urllib.request.Request(
        base_url.rstrip("/") + "/" + case.path,
        data=payload,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    try:
        try:
            response = urllib.request.urlopen(request, timeout=15)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            raw = response.read(8 * 1024 * 1024 + 1)
            if len(raw) > 8 * 1024 * 1024:
                raise ValueError("response exceeds benchmark capture limit")
            body = json.loads(raw)
            result = {
                "status": response.status,
                "bytes": len(raw),
                "count": body.get("count"),
                "total": body.get("total"),
                "total_is_lower_bound": body.get("total_is_lower_bound"),
            }
    except (OSError, ValueError) as error:
        result = {"error": type(error).__name__}
        body = {}
    result["elapsed_ms"] = round((time.perf_counter() - start) * 1000, 3)
    return result, body


def cases_for_stack(base_url: str, property_ref: str | None) -> tuple[list[Case], str | None]:
    cases = [
        Case(
            f"search:{query}",
            "properties/search?" + urllib.parse.urlencode({"q": query, "limit": 25}),
        )
        for query in DEFAULT_QUERIES
    ]
    if property_ref is None:
        _, search = read_case(base_url, cases[0])
        property_ref = next((item["property_ref"] for item in search.get("items", [])), None)
    cases.extend(
        Case(path, path)
        for path in (
            "overview",
            "notifications",
            "sources?limit=25",
            "jobs?limit=25",
            "ingestion-runs?limit=25",
            "dataset-releases?limit=25",
            "dataset-releases?view=summary&limit=25",
            "data-products",
            "runtime-capabilities",
            "properties/locality-summary?locality=Parramatta&include_streets=true",
        )
    )
    if property_ref:
        cases.extend(
            Case(f"property:{suffix or 'identity'}", f"properties/{property_ref}{suffix}")
            for suffix in (
                "",
                "/map-context",
                "/coverage",
                "/sale-history?limit=50",
                "/seifa",
                "/report-section",
            )
        )
    cases.extend(
        (
            Case("tool:search", "tools/properties.search.v1", {"query": "Glebe", "limit": 10}),
            Case("tool:locality", "tools/properties.locality-summary.v1", {"locality": "Glebe"}),
        )
    )
    _, catalogue = read_case(base_url, Case("catalogue", "data-products"))
    for product in catalogue.get("items", []):
        accepted = product.get("latest_accepted_release")
        if not accepted:
            continue
        dataset = product["dataset_id"]
        cases.append(Case(f"accepted:{dataset}", f"data-products/{dataset}/accepted"))
        cases.extend(
            Case(
                f"preview:{dataset}:{offset}",
                f"dataset-releases/{accepted['id']}/records?limit=25&offset={offset}",
            )
            for offset in (0, 25)
        )
    cases.append(
        Case("psi-source-year", "data-products/nsw-psi-sales/source-records?year=2025&limit=25")
    )
    return cases, property_ref


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:5200/api/data-platform/v1")
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument(
        "--property-ref", help="Pin identical property evidence across measurements"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.samples <= 100:
        parser.error("--samples must be between 1 and 100")
    cases, property_ref = cases_for_stack(args.base_url, args.property_ref)
    report: dict[str, Any] = {
        "measured_at": datetime.now(UTC).isoformat(),
        "base_url": args.base_url,
        "samples_per_case": args.samples,
        "property_ref": property_ref,
        "method": "sequential requests; cache is not flushed; first sample retained",
        "cases": [],
    }
    for case in cases:
        samples = [read_case(args.base_url, case)[0] for _ in range(args.samples)]
        times = sorted(sample["elapsed_ms"] for sample in samples)
        summary = {
            "label": case.label,
            "path": case.path,
            "method": "POST" if case.body else "GET",
            "p50_ms": round(statistics.median(times), 3),
            "p95_ms": times[math.ceil(len(times) * 0.95) - 1],
            "max_ms": times[-1],
            "successes": sum(sample.get("status") == 200 for sample in samples),
            "within_500ms": sum(
                sample.get("status") == 200 and sample["elapsed_ms"] <= 500 for sample in samples
            ),
            "samples": samples,
        }
        report["cases"].append(summary)
        print(
            f"{case.label}: {summary['successes']}/{args.samples} OK, "
            f"p50={summary['p50_ms']} ms, p95={summary['p95_ms']} ms",
            flush=True,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if all(case["successes"] == args.samples for case in report["cases"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
