"""JUnit XML reports become deterministic Markdown step summaries."""

from __future__ import annotations

from pathlib import Path

import pytest

from shared_testkit.junit_summary import (
    JUnitCase,
    JUnitReport,
    load_junit,
    main,
    markdown_summary,
    markdown_table,
    parse_junit,
)

PYTEST_JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites name="pytest tests">
  <testsuite name="pytest" errors="1" failures="1" skipped="1" tests="4" time="1.5">
    <testcase classname="tests.endpoints.test_api" name="test_search[ok]" time="0.250" />
    <testcase classname="tests.endpoints.test_api" name="test_create" time="0.5">
      <failure message="AssertionError: expected HTTP 201, got 422 | detail">trace
line 2</failure>
    </testcase>
    <testcase classname="tests.endpoints.test_api" name="test_setup" time="bad">
      <error message="">
        fixture 'endpoint_client' failed
      </error>
    </testcase>
    <testcase classname="" name="test_skipped" time="0">
      <skipped type="pytest.skip" message="endpoint test: set the base URL" />
    </testcase>
  </testsuite>
</testsuites>
"""


def test_parse_pytest_junit_outcomes_messages_and_totals() -> None:
    report = parse_junit(PYTEST_JUNIT)
    assert [case.outcome for case in report.cases] == ["passed", "failed", "error", "skipped"]
    assert report.cases[1].message == "AssertionError: expected HTTP 201, got 422 | detail"
    assert report.cases[2].message == "fixture 'endpoint_client' failed"
    assert report.cases[2].time_seconds == 0.0
    assert report.cases[0].test_id == "tests.endpoints.test_api::test_search[ok]"
    assert report.cases[3].test_id == "test_skipped"
    assert (report.total, report.count("passed"), report.count("skipped")) == (4, 1, 1)
    assert report.time_seconds == pytest.approx(0.75)
    assert report.succeeded is False


def test_single_testsuite_root_and_success_rules() -> None:
    passing = parse_junit(b'<testsuite><testcase name="a" time="0.1"/></testsuite>')
    assert passing.succeeded is True
    assert JUnitReport(()).succeeded is False
    only_skipped = JUnitReport((JUnitCase("c", "s", 0.0, "skipped"),))
    assert only_skipped.succeeded is False


@pytest.mark.parametrize("source", ["<not-xml", "<html><testcase/></html>"])
def test_invalid_reports_are_rejected(source: str) -> None:
    with pytest.raises(ValueError, match="invalid JUnit XML"):
        parse_junit(source)


def test_markdown_escapes_table_cells_and_marks_failures() -> None:
    report = parse_junit(PYTEST_JUNIT)
    table = markdown_table(report)
    assert table.splitlines()[0] == "| Test | Outcome | Duration (s) | Message |"
    assert "| `tests.endpoints.test_api::test_search[ok]` | passed | 0.250 |  |" in table
    assert "got 422 \\| detail" in table
    assert "| **failed** |" in table and "| **error** |" in table
    summary = markdown_summary(report, title="Feature | endpoints")
    assert summary.startswith("### Feature \\| endpoints\n\n**FAILED**: 1 passed, 1 failed")
    assert summary.endswith("|\n")


def test_empty_report_summary_says_nothing_ran() -> None:
    summary = markdown_summary(JUnitReport(()), title="Endpoints")
    assert "**FAILED**" in summary
    assert "No test cases were recorded." in summary


def test_cli_prints_writes_and_optionally_enforces_success(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    junit = tmp_path / "junit.xml"
    junit.write_text(PYTEST_JUNIT, encoding="utf-8")
    output = tmp_path / "out" / "summary.md"
    assert main([str(junit), "--title", "Endpoints", "--output", str(output)]) == 0
    printed = capsys.readouterr().out
    assert printed.startswith("### Endpoints")
    assert output.read_text(encoding="utf-8") == printed
    assert load_junit(junit).total == 4
    assert main([str(junit), "--require-success"]) == 1
    capsys.readouterr()
    passing = tmp_path / "passing.xml"
    passing.write_text('<testsuite><testcase name="a"/></testsuite>', encoding="utf-8")
    assert main([str(passing), "--require-success"]) == 0
    capsys.readouterr()
    assert main([str(tmp_path / "missing.xml")]) == 2
    assert "error:" in capsys.readouterr().err
