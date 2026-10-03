"""Protect the Release 1 report's generated evidence, draft handling and submission guard."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml
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


def test_empty_final_report_is_rejected_even_without_todos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "done.md"
    source.write_text("# Report\n\n## 1 Scope\n\nFinished.\n", encoding="utf-8")
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(report_pdf, "build", lambda *args: calls.append(args))

    assert report.main(["--source", str(source), "--final", "--baseline", "a" * 40]) == 1
    assert calls == []
    assert report.OUTPUT.name == "group-20.pdf"


def test_status_reports_the_word_limit_and_owners(capsys: pytest.CaptureFixture[str]) -> None:
    assert report.main(["--status"]) == 0
    output = capsys.readouterr().out
    assert f"of {report.WORD_LIMIT} total" in output
    assert "code and appendices included" in output


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
    assert any(line.startswith("request_id") for line in lines)
    assert any(line.startswith("feature") for line in lines)
    assert any(line.startswith("tool") for line in lines)
    assert any(line.startswith("  version") for line in lines)
    assert any(line.startswith("boundary") for line in lines)


def test_knowledge_sources_link_to_local_documents_with_provenance() -> None:
    rows = report.corpus_table("")
    assert any("project guidance" in row for row in rows)
    assert any("../../student-1/config/rag/documents/" in row for row in rows)
    assert any("CC0" in row for row in rows)


def test_committed_figures_match_their_mermaid_sources() -> None:
    report_pdf.validate_diagrams(report.SPEC)
    source = report.SOURCE.read_text(encoding="utf-8")
    for asset in report.SPEC.diagram_pairs.values():
        assert f"assets/release-1/{asset}" in source


@pytest.fixture
def complete_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    """A tiny real Git repository makes commit and evidence checks deterministic."""

    def git(*arguments: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(tmp_path), *arguments], capture_output=True, text=True, check=True
        )
        return completed.stdout.strip()

    git("init", "--quiet")
    git("config", "user.name", "Report test")
    git("config", "user.email", "report-test@example.invalid")
    evidence_file = tmp_path / "evidence.txt"
    evidence_file.write_text("Recorded local validation; fixture data.\n", encoding="utf-8")
    for mode in ("mcp", "rag"):
        capture = {
            "mode": mode,
            "passed": True,
            "status": "succeeded",
            "phases": ["plan", "act", "observe", "adapt"],
            "feature_key": "student-1-test",
            "tool_name": "context.retrieve.v1" if mode == "rag" else "test.capabilities.v1",
            "run_id": "test-run",
            "request_id": "test-request",
            "corpus_id": "test-corpus",
            "evidence_boundary": "Local transports; deterministic decisions.",
            "tool_results": [
                {
                    "call_id": "test-call",
                    "outcome": "succeeded",
                    "retrieval": {"corpus_version": "test-version", "status": "ready"},
                }
            ],
        }
        (tmp_path / f"loop-{mode}.json").write_text(json.dumps(capture), encoding="utf-8")
    git("add", "evidence.txt", "loop-mcp.json", "loop-rag.json")
    git("commit", "--quiet", "-m", "test: retain evidence")
    baseline = git("rev-parse", "HEAD")
    monkeypatch.setattr(report, "ROOT", tmp_path)
    monkeypatch.setattr(report, "_feature_manifests", lambda: [{"_student": "student-1"}])
    sections = {key: key.title() for key in report.REQUIRED_SECTIONS}
    statement = "Showcase attendance could not be independently confirmed."
    metadata = {
        "schema_version": 1,
        "baseline": "[[BASELINE]]",
        "repository_url": report_pdf.REPOSITORY_URL,
        "showcase_url": "https://youtu.be/0Z0Rt146lD0",
        "sections": sections,
        "evidence": [
            {
                "kind": kind,
                "section": "Validation",
                "path": f"{kind}.json" if kind.startswith("loop-") else "evidence.txt",
                "boundary": "Recorded local services; fixture data.",
                **student,
            }
            for kind, student in [
                *((kind, {}) for kind in report.SHARED_EVIDENCE),
                *((kind, {"student": 1}) for kind in report.STUDENT_EVIDENCE),
            ]
        ],
        "contributions": [{"student": 1, "section": "Student 1", "commits": [baseline[:7]]}],
        "attendance": {1: statement},
    }
    source = tmp_path / "report.md"
    content = (
        "# Report\n\n| Field | Value |\n|---|---|\n"
        f"| Repository | [Repository]({report_pdf.REPOSITORY_URL}) |\n"
        "| Showcase video | [Showcase](https://youtu.be/0Z0Rt146lD0) |\n"
        "| Commit reference | `[[BASELINE]]` |\n\n"
        "<!-- RELEASE1_METADATA\n" + yaml.safe_dump(metadata) + "-->\n\n"
    )
    for key, title in sections.items():
        content += f"## {title}\n\nDocumented {key} content.\n\n"
        if key == "validation":
            content += (
                "[Retained validation](evidence.txt)\n\n"
                "[MCP loop](loop-mcp.json) [RAG loop](loop-rag.json)\n\n"
            )
        if key == "contributions":
            content += (
                f"{statement}\n\n### Student 1\n\n{baseline[:7]} implemented the feature.\n\n"
            )
    source.write_text(content, encoding="utf-8")
    return source, baseline


def test_final_requires_real_commit_complete_sections_and_traceable_evidence(
    complete_report: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    source, baseline = complete_report
    assert report.final_content_blockers(source, baseline) == []
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(report_pdf, "build", lambda *args: calls.append(args))
    assert report.main(["--source", str(source), "--final", "--baseline", baseline]) == 0
    assert calls[0][1] == report.OUTPUT
    assert report.OUTPUT.name == "group-20.pdf"


def test_final_rejects_fake_baseline_and_cover_mismatch(complete_report: tuple[Path, str]) -> None:
    source, baseline = complete_report
    assert any(
        "does not resolve" in issue for issue in report.final_content_blockers(source, "0" * 40)
    )
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "| Commit reference | `[[BASELINE]]` |", "| Commit reference | Pending |"
        ),
        encoding="utf-8",
    )
    assert "cover Commit reference does not match --baseline" in report.final_content_blockers(
        source, baseline
    )


def test_final_rejects_empty_required_section(complete_report: tuple[Path, str]) -> None:
    source, baseline = complete_report
    source.write_text(
        source.read_text(encoding="utf-8").replace("Documented integration content.", ""),
        encoding="utf-8",
    )
    assert "missing or empty required section: integration" in report.final_content_blockers(
        source, baseline
    )


def test_final_rejects_untracked_evidence_and_unresolvable_contribution(
    complete_report: tuple[Path, str],
) -> None:
    source, baseline = complete_report
    (source.parent / "new.txt").write_text("Uncommitted validation", encoding="utf-8")
    source.write_text(
        source.read_text(encoding="utf-8")
        .replace("evidence.txt", "new.txt")
        .replace(baseline[:7], "0" * 40),
        encoding="utf-8",
    )
    blockers = report.final_content_blockers(source, baseline)
    assert any("not tracked at the baseline" in issue for issue in blockers)
    assert any("must resolve and appear in the log" in issue for issue in blockers)


def test_final_rejects_evidence_edited_since_baseline(complete_report: tuple[Path, str]) -> None:
    source, baseline = complete_report
    (source.parent / "evidence.txt").write_text("New evidence after baseline", encoding="utf-8")
    assert any(
        "differs from the baseline evidence" in issue
        for issue in report.final_content_blockers(source, baseline)
    )


def test_evidence_in_another_section_does_not_satisfy_declared_section(
    complete_report: tuple[Path, str],
) -> None:
    source, baseline = complete_report
    source.write_text(
        source.read_text(encoding="utf-8").replace("[Retained validation](evidence.txt)", "")
        + "\n## Unrelated\n\n[Retained validation](evidence.txt)\n",
        encoding="utf-8",
    )
    assert any(
        "not shown or linked in its section" in issue
        for issue in report.final_content_blockers(source, baseline)
    )


def test_loop_final_guard_rejects_failed_or_unidentified_capture(tmp_path: Path) -> None:
    path = tmp_path / "capture.json"
    path.write_text(json.dumps({"mode": "mcp", "passed": False}), encoding="utf-8")
    assert "successful four-phase mcp" in str(report._loop_capture_issue(path, "loop-mcp"))
    path.write_text(
        json.dumps(
            {
                "mode": "rag",
                "passed": True,
                "status": "succeeded",
                "phases": ["plan", "act", "observe", "adapt"],
            }
        ),
        encoding="utf-8",
    )
    assert "identities" in str(report._loop_capture_issue(path, "loop-rag"))
