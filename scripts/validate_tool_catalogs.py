"""Validate every checked-in feature tool catalogue without contacting services."""

from __future__ import annotations

from pathlib import Path

from ai_mode.tool_catalog import build_tool_runtime, load_tool_catalog

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CATALOG_NAME = "tool-catalog.yaml"


def discover_catalogs(root: Path = REPOSITORY_ROOT) -> tuple[Path, ...]:
    """Find canonical catalogues only in feature-owned and example slices."""
    candidate_roots = (
        root / "examples",
        *(root / f"student-{number}" for number in range(1, 6)),
    )
    return tuple(
        sorted(
            path
            for candidate_root in candidate_roots
            if candidate_root.exists()
            for path in candidate_root.rglob(CATALOG_NAME)
        )
    )


def main() -> int:
    """Load and compose each catalogue so unsafe transport metadata fails CI."""
    catalogs = discover_catalogs()
    for path in catalogs:
        catalog = load_tool_catalog(path)
        _, executor = build_tool_runtime(
            catalog,
            max_request_bytes=1,
            max_response_bytes=1,
        )
        executor.close()
    print(f"Validated {len(catalogs)} feature tool catalogue(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
