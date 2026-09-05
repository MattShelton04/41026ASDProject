"""Compare private export layouts with synthetic rows, without network or database writes.

The timings cover page encoding/decoding, validation, projection and gzip construction.
They do not estimate full source acquisition, PostgreSQL import or production network latency.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections.abc import Iterator
from contextlib import closing
from statistics import median
from typing import Any

from propertyscope_data_platform.release_builders import BuildContext, default_release_builders
from propertyscope_data_platform.release_stream import ReleaseRowStream
from propertyscope_data_store.export_pages import columnar_export_page

RELEASE_ID = "60000000-0000-0000-0000-000000000099"
PAGE_SIZE = 20_000


def benchmark(
    rows: int, repetitions: int, product_key: str = "property-snapshot"
) -> dict[str, Any]:
    """Report comparable bounded runs, requiring byte-identical portable products."""
    if not 1 <= rows <= 1_000_000 or not 1 <= repetitions <= 10:
        raise ValueError("rows must be 1..1000000 and repetitions 1..10")
    profile, target = {
        "property-snapshot": ("property-fixture", "feature-1"),
        "property-sales": ("psi-sales", "feature-2"),
        "crime-series": ("bocsar-sparse", "feature-3"),
    }[product_key]
    context = BuildContext(
        release_id=RELEASE_ID,
        candidate_generation_id=RELEASE_ID,
        release_version="synthetic-benchmark",
        dataset_id="fixture-property",
        import_profile=profile,
        normalisation_version="1.0.0",
        target_feature=target,
        publisher="Synthetic benchmark",
        source="Generated addresses",
        source_release="synthetic",
        source_licence="synthetic-test-data",
        licence_url="https://creativecommons.org/publicdomain/zero/1.0/",
        redistribution_policy={
            "property-snapshot": "committed-synthetic-fixture",
            "property-sales": "bounded-derived-release",
            "crime-series": "approved-bounded-extract",
        }[product_key],
    )
    builder = default_release_builders()[product_key]
    page_size = 500 if product_key == "crime-series" else PAGE_SIZE
    make_row = {"property-snapshot": _row, "property-sales": _sale_row, "crime-series": _crime_row}[
        product_key
    ]
    results: dict[str, list[dict[str, Any]]] = {
        "record_pages": [],
        "column_pages_prefetched": [],
        "column_pages_parallel": [],
    }
    reference: tuple[str, int] | None = None
    for _repetition in range(repetitions):
        for variant, measurements in results.items():
            transport_bytes = 0

            def fetch(cursor: str | None, *, layout: str = variant) -> dict[str, Any]:
                nonlocal transport_bytes
                offset = int(cursor or 0)
                items = [make_row(index) for index in range(offset, min(rows, offset + page_size))]
                page = {
                    "release_id": RELEASE_ID,
                    "candidate_generation_id": RELEASE_ID,
                    "total": rows if offset == 0 else None,
                    "items": items,
                    "next_cursor": str(offset + len(items)) if offset + len(items) < rows else None,
                }
                if layout != "record_pages":
                    page = columnar_export_page(page)
                encoded = json.dumps(page, sort_keys=True, separators=(",", ":")).encode()
                transport_bytes += len(encoded)
                return json.loads(encoded)

            def sequential() -> Iterator[dict[str, Any]]:
                cursor = None
                while True:
                    page = fetch(cursor)
                    yield from page["items"]
                    cursor = page["next_cursor"]
                    if cursor is None:
                        return

            start = time.perf_counter()
            source = (
                iter(
                    ReleaseRowStream(
                        fetch,
                        lambda *_: None,
                        release_id=RELEASE_ID,
                        generation_id=RELEASE_ID,
                        page_size=page_size,
                    )
                )
                if variant != "record_pages"
                else sequential()
            )
            digest = hashlib.sha256()
            size = 0
            with closing(source):
                product = builder.stream(
                    context,
                    source,
                    projection_workers=2 if variant == "column_pages_parallel" else 0,
                )
                for chunk in product.chunks():
                    digest.update(chunk)
                    size += len(chunk)
            seconds = time.perf_counter() - start
            identity = (digest.hexdigest(), size)
            if reference is not None and reference != identity:
                raise RuntimeError("export optimization changed portable product bytes")
            reference = identity
            measurements.append({"seconds": seconds, "transport_bytes": transport_bytes})
    return {
        "scope": "synthetic private page transport and portable product build; no database/network",
        "rows": rows,
        "product": product_key,
        "repetitions": repetitions,
        "gzip_sha256": reference[0] if reference else None,
        "gzip_bytes": reference[1] if reference else None,
        "variants": {
            variant: {"runs": runs, "median_seconds": median(run["seconds"] for run in runs)}
            for variant, runs in results.items()
        },
    }


def _row(index: int) -> dict[str, Any]:
    return {
        "source_address_id": f"SYNTHETIC-{index:09}",
        "property_ref": None,
        "address_display": f"{index} EXAMPLE STREET SYDNEY NSW 2000",
        "flat_type": None,
        "unit_number": None,
        "street_number_first": index,
        "street_number_suffix": None,
        "street_number_last": None,
        "street_name": "EXAMPLE",
        "street_type": "STREET",
        "locality": "SYDNEY",
        "postcode": "2000",
        "source_status": "CURRENT",
        "geocode_type": "PC",
        "source_crs": 7844,
        "latitude": -33.8 + index / 1e7,
        "longitude": 151.1 + index / 1e7,
        "source_row_sha256": hashlib.sha256(str(index).encode()).hexdigest(),
        "normalisation_version": "1.0.0",
    }


def _sale_row(index: int) -> dict[str, Any]:
    return {
        "source_business_key": f"sale-{index:09}",
        "source_revision": 1,
        "source_era": "post-2001",
        "contract_date": "2025-01-01",
        "price_aud": 500_000 + index,
        "property_ref": None,
        "match_tier": "MISS",
        "match_confidence": "0",
        "geographic_precision": "unknown",
        "source_row_sha256": hashlib.sha256(str(index).encode()).hexdigest(),
        "normalisation_version": "1.0.0",
    }


def _crime_row(index: int) -> dict[str, Any]:
    months = [f"{year}-{month:02}-01" for year in range(2000, 2026) for month in range(1, 13)]
    digest = hashlib.sha256(str(index).encode()).hexdigest()
    return {
        "geography_kind": "postcode",
        "geography_value": str(2000 + index % 6000),
        "source_category_key": f"category-{index // 6000}",
        "offence_label": "Synthetic offence",
        "subcategory_label": "Total",
        "observed_months": months,
        "first_month": months[0],
        "last_month": months[-1],
        "month_count": len(months),
        "blank_means_observed_zero": True,
        "completeness_sha256": hashlib.sha256(
            json.dumps(months, separators=(",", ":")).encode()
        ).hexdigest(),
        "observations": [
            {"month": month, "count": 1 + index % 20, "source_row_sha256": digest}
            for month in months
        ],
        "source_row_sha256": digest,
        "normalisation_version": "1.0.0",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=100_000)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument(
        "--product",
        choices=["property-snapshot", "property-sales", "crime-series"],
        default="property-snapshot",
    )
    arguments = parser.parse_args()
    print(json.dumps(benchmark(arguments.rows, arguments.repetitions, arguments.product), indent=2))
