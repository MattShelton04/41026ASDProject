"""Show which Feature 1 datasets are really loaded, and which releases wait for a human.

Usage: uv run python .github/skills/feature-1-data/data_status.py [--base-url URL] [--json]

Read-only: it only calls public GET endpoints. The default base URL follows PROPERTYSCOPE_PORT
(default 5200), the same setting `scripts/dev.py` and Compose use.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

import httpx

# The database migrations seed a tiny demonstration baseline with these fixed release IDs.
SEEDED_RELEASE_PREFIX = "60000000-0000-0000-0000-"
OPEN_STATES = ("candidate", "awaiting_review")


def _get(client: httpx.Client, path: str, **params: str | int) -> dict[str, Any]:
    response = client.get(path, params=params)
    response.raise_for_status()
    value = response.json()
    if not isinstance(value, dict):
        raise RuntimeError(f"{path} returned malformed JSON")
    return value


def _releases(client: httpx.Client, status: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    offset: int | None = 0
    while offset is not None and len(items) < 1000:
        page = _get(client, "dataset-releases", status=status, limit=100, offset=offset)
        items.extend(item for item in page.get("items", []) if isinstance(item, dict))
        next_offset = page.get("next_offset")
        offset = next_offset if isinstance(next_offset, int) and next_offset > offset else None
    return items


def collect(client: httpx.Client) -> list[dict[str, Any]]:
    """Return one row per registered dataset with its accepted and open releases."""
    products = _get(client, "data-products").get("items", [])
    accepted = {item["dataset_id"]: item for item in _releases(client, "accepted")}
    open_releases: dict[str, list[dict[str, Any]]] = {}
    for state in OPEN_STATES:
        for item in _releases(client, state):
            open_releases.setdefault(item["dataset_id"], []).append(item)
    rows = []
    for product in products:
        dataset_id = product["dataset_id"]
        current = accepted.get(dataset_id)
        seeded = bool(current and str(current["id"]).startswith(SEEDED_RELEASE_PREFIX))
        rows.append(
            {
                "dataset_id": dataset_id,
                "accepted_release_id": current["id"] if current else None,
                "accepted_records": current.get("record_count") if current else None,
                "accepted_is_seeded_demo": seeded,
                "open_releases": [
                    {
                        "id": item["id"],
                        "status": item["status"],
                        "version": item.get("version"),
                        "records": item.get("record_count"),
                    }
                    for item in open_releases.get(dataset_id, [])
                ],
            }
        )
    return rows


def render(rows: list[dict[str, Any]]) -> str:
    lines = [f"{'dataset':<26} {'accepted records':>16}  state"]
    for row in rows:
        if row["accepted_release_id"] is None:
            count, state = "-", "not loaded"
        else:
            count = f"{row['accepted_records']:,}"
            state = "SEEDED DEMO ONLY" if row["accepted_is_seeded_demo"] else "real accepted data"
        lines.append(f"{row['dataset_id']:<26} {count:>16}  {state}")
        for item in row["open_releases"]:
            lines.append(
                f"{'':<26} {'':>16}  -> {item['status']} {item['id']} "
                f"v{item['version']} ({item['records']:,} records): needs human review"
            )
    return "\n".join(lines)


def main() -> int:
    port = os.environ.get("PROPERTYSCOPE_PORT", "").strip() or "5200"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=f"http://127.0.0.1:{port}/api/data-platform/v1")
    parser.add_argument("--json", action="store_true", help="Print machine-readable rows")
    arguments = parser.parse_args()
    try:
        with httpx.Client(base_url=arguments.base_url.rstrip("/") + "/", timeout=30) as client:
            rows = collect(client)
    except httpx.HTTPError as exc:
        print(f"Feature 1 API unavailable at {arguments.base_url}: {exc}", file=sys.stderr)
        print("Start the stack with `uv run scripts/dev.py stack up --offline`.", file=sys.stderr)
        return 1
    print(json.dumps(rows, indent=2) if arguments.json else render(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
