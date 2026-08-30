"""Validate every checked-in feature tool catalogue without contacting services."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ai_mode.tool_catalog import build_tool_runtime, load_tool_catalog

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.onboarding import OnboardingConfigurationError, discover_tool_catalogs

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def discover_catalogs(root: Path = REPOSITORY_ROOT) -> tuple[Path, ...]:
    """Find only catalogues declared by explicitly enabled features."""
    return discover_tool_catalogs(root)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate tool catalogues declared by enabled feature onboarding metadata."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=REPOSITORY_ROOT,
        help="Repository root to inspect (defaults to the current project).",
    )
    return parser


def main() -> int:
    """Load and compose each catalogue so unsafe transport metadata fails CI."""
    arguments = _parser().parse_args()
    try:
        catalogs = discover_catalogs(arguments.root.resolve())
    except OnboardingConfigurationError as exc:
        print(f"Tool catalogue discovery failed: {exc}")
        return 1
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
