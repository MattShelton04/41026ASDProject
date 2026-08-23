"""Command-line entry point for quick and full PropertyScope UI audits."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from scripts.ui_audit.config import AuditConfigError, AuditSelection, load_config
from scripts.ui_audit.runner import run_audit
from scripts.ui_fixture_server import DEFAULT_PORT


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", choices=("quick", "full"))
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--resume", type=Path, default=None)
    parser.add_argument("--workspace", action="append", default=[])
    parser.add_argument("--route-group", action="append", default=[])
    parser.add_argument("--route", action="append", default=[])
    parser.add_argument("--scenario", action="append", default=[])
    parser.add_argument("--viewport", action="append", default=[])
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-total", type=int, default=1)
    parser.add_argument(
        "--allow-destructive",
        action="store_true",
        help="Allow final destructive actions only against the stateless loopback fixture",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        config = load_config(arguments.config) if arguments.config else load_config()
        selection = AuditSelection(
            workspaces=tuple(arguments.workspace),
            route_groups=tuple(arguments.route_group),
            routes=tuple(arguments.route),
            scenarios=tuple(arguments.scenario),
            viewports=tuple(arguments.viewport),
            shard_index=arguments.shard_index,
            shard_total=arguments.shard_total,
        )
        result = run_audit(
            config,
            profile=arguments.profile,
            port=arguments.port,
            output=arguments.output,
            resume=arguments.resume,
            selection=selection,
            allow_destructive=arguments.allow_destructive,
        )
    except (AuditConfigError, OSError, PlaywrightError, RuntimeError) as exc:
        if "Executable doesn't exist" in str(exc):
            print(
                "error: Playwright Chromium is missing. Run "
                "`uv run playwright install chromium` once.",
                file=sys.stderr,
            )
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 2
    summary = result.report["summary"]
    print(f"UI audit artifacts: {result.output.resolve()}")
    print(
        "Batches: "
        f"{summary['batches']['completed']}/{summary['batches']['planned']} completed; "
        f"{summary['batches']['failed']} failed; {summary['batches']['resumed']} resumed"
    )
    print(
        "Controls: "
        f"{summary['controls']['inventoried']} inventoried; "
        f"{summary['controls']['exercised']} exercised; "
        f"{summary['controls']['skippedDestructive']} destructive skipped; "
        f"{summary['controls']['unreachable']} unreachable"
    )
    print(f"Findings: {summary['findings']['bySeverity']}")
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
