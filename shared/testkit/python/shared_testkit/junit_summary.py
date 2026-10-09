"""Turn a pytest JUnit XML report into a Markdown summary.

Used by the ``student-N.yml`` workflows to publish endpoint-test results to
``$GITHUB_STEP_SUMMARY`` and by ``scripts/collect_ci_evidence.py`` for the CI report::

    uv run --locked python -m shared_testkit.junit_summary endpoint-junit.xml \\
        --title "Feature 1 endpoint tests" >> "$GITHUB_STEP_SUMMARY"

The input is the report pytest itself wrote in the same job; it is parsed with the
standard library, whose bundled Expat rejects entity-expansion attacks.
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ElementTree
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Outcome = Literal["passed", "failed", "error", "skipped"]
_OUTCOME_LABELS: dict[Outcome, str] = {
    "passed": "passed",
    "failed": "**failed**",
    "error": "**error**",
    "skipped": "skipped",
}
_NON_PASSING_CHILDREN: tuple[tuple[str, Outcome], ...] = (
    ("failure", "failed"),
    ("error", "error"),
    ("skipped", "skipped"),
)
_MESSAGE_CHARS = 200


@dataclass(frozen=True, slots=True)
class JUnitCase:
    """One test case outcome from a JUnit report."""

    classname: str
    name: str
    time_seconds: float
    outcome: Outcome
    message: str = ""

    @property
    def test_id(self) -> str:
        return f"{self.classname}::{self.name}" if self.classname else self.name


@dataclass(frozen=True, slots=True)
class JUnitReport:
    """The aggregate of every test case in a JUnit report."""

    cases: tuple[JUnitCase, ...]

    def count(self, outcome: Outcome) -> int:
        return sum(1 for case in self.cases if case.outcome == outcome)

    @property
    def total(self) -> int:
        return len(self.cases)

    @property
    def time_seconds(self) -> float:
        return sum(case.time_seconds for case in self.cases)

    @property
    def succeeded(self) -> bool:
        """True when at least one test passed and none failed or errored."""
        return self.count("passed") > 0 and self.count("failed") == 0 and self.count("error") == 0


def _first_line(text: str | None) -> str:
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:_MESSAGE_CHARS]
    return ""


def _case(element: ElementTree.Element) -> JUnitCase:
    try:
        time_seconds = float(element.get("time", "0") or 0)
    except ValueError:
        time_seconds = 0.0
    outcome: Outcome = "passed"
    message = ""
    for child_tag, child_outcome in _NON_PASSING_CHILDREN:
        child = element.find(child_tag)
        if child is not None:
            outcome = child_outcome
            message = _first_line(child.get("message")) or _first_line(child.text)
            break
    return JUnitCase(
        classname=element.get("classname", ""),
        name=element.get("name", ""),
        time_seconds=time_seconds,
        outcome=outcome,
        message=message,
    )


def parse_junit(source: str | bytes) -> JUnitReport:
    """Parse JUnit XML text with a ``<testsuites>`` or ``<testsuite>`` root."""
    try:
        root = ElementTree.fromstring(source)
    except ElementTree.ParseError as exc:
        raise ValueError(f"invalid JUnit XML: {exc}") from exc
    if root.tag not in {"testsuites", "testsuite"}:
        raise ValueError(f"invalid JUnit XML: unexpected root element <{root.tag}>")
    return JUnitReport(tuple(_case(element) for element in root.iter("testcase")))


def load_junit(path: Path) -> JUnitReport:
    """Read and parse one JUnit XML file."""
    return parse_junit(path.read_bytes())


def _cell(text: str) -> str:
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ").strip()


def markdown_table(report: JUnitReport) -> str:
    """Return a Markdown table with one row per test case."""
    lines = [
        "| Test | Outcome | Duration (s) | Message |",
        "|---|---|---:|---|",
    ]
    for case in report.cases:
        lines.append(
            f"| `{_cell(case.test_id)}` | {_OUTCOME_LABELS[case.outcome]} "
            f"| {case.time_seconds:.3f} | {_cell(case.message)} |"
        )
    return "\n".join(lines)


def markdown_summary(report: JUnitReport, *, title: str) -> str:
    """Return a heading, totals line and per-test table suitable for a step summary."""
    verdict = "PASSED" if report.succeeded else "FAILED"
    totals = (
        f"**{verdict}**: {report.count('passed')} passed, {report.count('failed')} failed, "
        f"{report.count('error')} errors, {report.count('skipped')} skipped "
        f"of {report.total} tests in {report.time_seconds:.2f}s"
    )
    if not report.cases:
        return f"### {_cell(title)}\n\n{totals}\n\nNo test cases were recorded.\n"
    return f"### {_cell(title)}\n\n{totals}\n\n{markdown_table(report)}\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m shared_testkit.junit_summary",
        description="Render a JUnit XML report as a Markdown summary.",
    )
    parser.add_argument("junit", type=Path, help="JUnit XML file written by pytest --junitxml")
    parser.add_argument("--title", default="Endpoint tests", help="Markdown heading")
    parser.add_argument("--output", type=Path, help="Also write the Markdown to this file")
    parser.add_argument(
        "--require-success",
        action="store_true",
        help="Exit 1 unless at least one test passed and none failed or errored",
    )
    arguments = parser.parse_args(argv)
    try:
        report = load_junit(arguments.junit)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    summary = markdown_summary(report, title=arguments.title)
    if arguments.output is not None:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(summary, encoding="utf-8")
    sys.stdout.write(summary)
    if arguments.require_success and not report.succeeded:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
