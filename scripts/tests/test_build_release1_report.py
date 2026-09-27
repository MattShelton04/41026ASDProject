"""Protect the Release 1 report's generated evidence, draft handling and submission guard."""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts import build_release1_report as report
from scripts import report_pdf


def test_drafts_write_the_tracked_submission_file_and_final_is_blocked_while_work_remains(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(report_pdf, "build", lambda *args: calls.append(args))

    assert report.main([]) == 0
    assert calls == [(report.SOURCE, report.OUTPUT, "main", report.SPEC)]
    assert report.OUTPUT.relative_to(report_pdf.REPORT_DIR).as_posix() == (
        "submissions/release-1/group-20.pdf"
    )

    assert report.main(["--final", "--baseline", "0" * 40]) == 1
    assert len(calls) == 1
    assert "Final build blocked" in capsys.readouterr().err


def test_final_output_uses_the_required_submission_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "done.md"
    source.write_text("# Report\n\n## 1 Scope\n\nFinished.\n", encoding="utf-8")
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(report_pdf, "build", lambda *args: calls.append(args))

    assert report.main(["--source", str(source), "--final", "--baseline", "a" * 40]) == 0
    assert calls[0][1] == report.OUTPUT
    assert report.OUTPUT.name == "group-20.pdf"


def test_status_reports_the_word_limit_and_owners(capsys: pytest.CaptureFixture[str]) -> None:
    assert report.main(["--status"]) == 0
    output = capsys.readouterr().out
    assert f"of {report.WORD_LIMIT} total" in output
    status = report_pdf.review(report.SOURCE, report.SPEC)
    assert status.words.total <= report.WORD_LIMIT


def test_tool_table_lists_every_enabled_feature_and_the_shared_tool() -> None:
    rows = report.tool_table("")
    manifests = report._feature_manifests()
    assert len(rows) == 2 + len(manifests) + 1
    for manifest in manifests:
        for tool in report._catalog_tools(manifest):
            assert any(f"`{tool['name']}`" in row for row in rows)
    assert "context.retrieve.v1" in rows[-1]


def test_every_registered_tool_has_an_appendix_row() -> None:
    names = [tool["name"] for m in report._feature_manifests() for tool in report._catalog_tools(m)]
    assert len(report.tool_detail("")) == 2 + len(names)


def test_missing_loop_capture_becomes_a_todo() -> None:
    lines = report.loop_output("docs/release-1/evidence/does-not-exist.json")
    assert report_pdf.TODO_PATTERN.fullmatch(lines[0])


def test_loop_capture_renders_as_terminal_output() -> None:
    lines = report.loop_output("docs/release-1/evidence/validation-rag.json")
    assert lines[0] == "```text" and lines[-1] == "```"
    assert any(line.startswith("run_id") for line in lines)


def test_committed_figures_match_their_mermaid_sources() -> None:
    report_pdf.validate_diagrams(report.SPEC)
    source = report.SOURCE.read_text(encoding="utf-8")
    for asset in report.SPEC.diagram_pairs.values():
        assert f"assets/release-1/{asset}" in source
