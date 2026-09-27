"""Rebuild the Release 0 technical report PDF from its maintained Markdown source.

The PDF submitted on Canvas is frozen under ``docs/reports/submissions/release-0``. Rebuilds are
written to ``tmp/`` by default so they can never overwrite that historical artefact.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from pathlib import Path

from reportlab.lib.units import mm

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import report_pdf
from scripts.report_pdf import REPORT_DIR, ROOT, ReportSpec

BASELINE = "7d5350d19023fb1e978e85127a72e3500a1556f3"
SOURCE = REPORT_DIR / "release-0-technical-report.md"
DEFAULT_OUTPUT = ROOT / "tmp" / "reports" / "release-0" / "41026Group20Release0Report.pdf"
SUBMITTED_PDF = REPORT_DIR / "submissions" / "release-0" / "41026Group20Release0Report.pdf"


def _diagram_pairs() -> dict[str, str]:
    return {
        "feature-1-runtime.mmd": "individual-boundaries.png",
        "feature-1-publication.mmd": "feature-1-publication.png",
        **{f"feature-{i}-runtime.mmd": f"feature-{i}-runtime.png" for i in range(2, 6)},
        **{f"feature-{i}-erd.mmd": f"feature-{i}-erd.png" for i in range(1, 6)},
        **{
            f"{name}.mmd": f"{name}.png"
            for name in (
                "integrated-architecture",
                "compose-topology",
                "agent-loop",
                "devops-pipeline",
            )
        },
    }


def _image_max_height(path: Path) -> float:
    if path.stem == "compose-topology":
        return 115 * mm
    if path.stem == "agent-loop":
        return 135 * mm
    return report_pdf.default_image_max_height(path)


SPEC = ReportSpec(
    release_label="RELEASE 0",
    footer_title="PropertyScope NSW  |  Release 0 Technical Report",
    pdf_title="PropertyScope NSW Release 0 Technical Report",
    pdf_subject="41026 Advanced Software Development Assessment 1",
    asset_dir=REPORT_DIR / "assets" / "release-0",
    diagram_dir=REPORT_DIR / "diagrams" / "release-0",
    diagram_pairs=_diagram_pairs(),
    image_max_height=_image_max_height,
)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--baseline", default=BASELINE)
    parser.add_argument(
        "--render-diagrams",
        action="store_true",
        help="Refresh Mermaid PNGs and their drift manifest before building",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.output.resolve() == SUBMITTED_PDF.resolve():
        parser.error("the submitted Release 0 PDF is frozen; choose another --output")
    if args.render_diagrams:
        report_pdf.render_diagrams(SPEC)
    report_pdf.build(args.source.resolve(), args.output.resolve(), args.baseline, SPEC)
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
