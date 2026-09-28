"""Command line for visual captures and local comparison galleries.

uv run python -m scripts.visual capture --provider fixture --out DIR [--case ID]
uv run python -m scripts.visual compare --base DIR --head DIR --out DIR
uv run python -m scripts.visual cases
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.visual", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    from scripts.visual import capture

    capture.add_arguments(commands.add_parser("capture", help="capture one provider's cases"))
    compare = commands.add_parser("compare", help="build a gallery from two capture directories")
    compare.add_argument(
        "--base", type=Path, required=True, help="baseline captures (may be empty)"
    )
    compare.add_argument("--head", type=Path, required=True, help="changed captures")
    compare.add_argument("--out", type=Path, required=True, help="gallery output directory")
    compare.add_argument("--title", default="Local visual comparison")
    commands.add_parser("cases", help="list the visual case inventory")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch a visual regression command."""
    arguments = _parser().parse_args(argv)
    if arguments.command == "capture":
        from scripts.visual import capture

        return capture.run(arguments)
    if arguments.command == "compare":
        from scripts.visual.report import build_report

        result = build_report(
            base_dir=arguments.base,
            head_dir=arguments.head,
            output=arguments.out,
            title=arguments.title,
            strict=False,
        )
        summary = result.summary
        print(
            f"{summary['changed']} changed, {summary['subtle']} subtle, "
            f"{summary['unchanged']} identical, {summary['baseUnavailable']} without baseline, "
            f"{summary['incomplete']} incomplete"
        )
        print(f"Open {arguments.out.resolve() / 'index.html'}")
        return 0
    from scripts.visual.cases import CASES

    for case in CASES:
        print(f"{case.id:<28} {case.provider:<8} {case.section:<10} {case.state}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
