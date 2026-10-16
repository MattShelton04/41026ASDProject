"""Protect the Release 2 report's generated evidence tables, budget, drafts and final guard."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest
import yaml
from scripts import build_release2_report as report
from scripts import report_pdf

DIRECTIVE_CALLS = (
    (report.security_summary, ""),
    (report.ci_evidence, ""),
    (report.review_summary, "testing"),
    (report.review_summary, "multi-agent"),
    (report.review_summary, "cloud"),
    (report.multi_agent_runs, ""),
    (report.workflow_history, "multi-agent/student-1/missing-run"),
    (report.local_evidence, ""),
    (report.cloud_summary, ""),
)


def _todos(lines: list[str]) -> list[re.Match[str]]:
    return [match for line in lines if (match := report_pdf.TODO_PATTERN.fullmatch(line))]


@pytest.fixture
def evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "evidence"
    root.mkdir()
    monkeypatch.setattr(report, "EVIDENCE_DIR", root)
    return root


def test_drafts_write_the_tracked_submission_file_and_final_is_blocked_while_work_remains(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(report_pdf, "build", lambda *args: calls.append(args))

    assert report.main([]) == 0
    assert calls == [(report.SOURCE, report.OUTPUT, "main", report.SPEC)]
    assert report.OUTPUT.relative_to(report_pdf.REPORT_DIR).as_posix() == (
        "submissions/release-2/group-20.pdf"
    )

    assert report.main(["--final", "--baseline", "0" * 40]) == 1
    assert len(calls) == 1
    assert "Final build blocked" in capsys.readouterr().err


def test_status_prints_the_word_limit_budgets_and_todos_by_owner(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert report.main(["--status"]) == 0
    output = capsys.readouterr().out
    assert f"of {report.WORD_LIMIT} total" in output
    assert "cover and captions included" in output
    assert "TODOs by owner:" in output or "No TODOs remain." in output


def test_budgets_fit_the_limit_and_cover_every_chapter_of_the_brief() -> None:
    assert sum(report.SECTION_WORD_BUDGETS.values()) <= report.WORD_LIMIT - 40  # cover text
    words = report_pdf.count_words(report.SOURCE, report.SPEC)
    chapters = [title for title, _ in words.sections if title != "Cover"]
    assert len(chapters) == len(report.REQUIRED_SECTIONS) == len(report.SECTION_WORD_BUDGETS)
    for title in chapters:
        assert any(title.startswith(prefix) for prefix in report.SECTION_WORD_BUDGETS), title


def test_source_metadata_maps_every_required_section_to_a_rendered_heading() -> None:
    metadata = report._metadata(report.SOURCE)
    assert set(metadata["sections"]) == set(report.REQUIRED_SECTIONS)
    sections = report._section_bodies(report.SOURCE)
    for title in metadata["sections"].values():
        assert title in sections


def test_word_count_excludes_todos_and_counts_generated_tables(tmp_path: Path) -> None:
    def write(body: str) -> Path:
        source = tmp_path / "report.md"
        source.write_text(f"# Report\n\n## 1 Project overview\n\n{body}\n", encoding="utf-8")
        return source

    def overview(body: str) -> int:
        words = report_pdf.count_words(write(body), report.SPEC)
        return dict(words.sections)["1 Project overview"]

    todo = "[[TODO: Burhan Naeem | many words that must not be counted at all]]"
    assert (
        overview(f"One two three.\n\n{todo}") == overview("One two three.") == 6
    )  # heading counts
    assert overview("One two three.\n\n[[FEATURE_FLOWS]]") > 6 + 5 * len(report.TEAM)
    source = write(todo)
    status = report_pdf.review(source, report.SPEC)
    assert report.owner_summary(status) == "TODOs by owner: Burhan Naeem 1"


def test_every_generated_table_tolerates_missing_evidence(evidence: Path) -> None:
    for directive, argument in DIRECTIVE_CALLS:
        lines = directive(argument)
        assert _todos(lines), directive.__name__
    owners = {match["owner"] for match in _todos(report.ci_evidence(""))}
    assert owners == set(report.TEAM.values())
    assert len(_todos(report.multi_agent_runs(""))) == len(report.TEAM)
    assert any("Pending" in line for line in report.cloud_summary(""))


def test_unknown_review_mode_is_a_programming_error() -> None:
    with pytest.raises(ValueError, match="unknown review mode"):
        report.review_summary("deployment")


def test_ci_rows_come_from_the_collected_record_and_flag_failed_runs(evidence: Path) -> None:
    (evidence / "ci").mkdir()
    record = (
        "# Student 1 CI evidence\n\n| Field | Value |\n|---|---|\n"
        "| Run | [#353 (ID 38719115720, attempt 1)]"
        "(https://github.com/MattShelton04/41026ASDProject/actions/runs/38719115720) |\n"
        "| Conclusion | **success** |\n"
        "| Head SHA | `d449a43455ca6b20365ed95d1560aa3546b504ab` |\n\n## Jobs\n\n"
        "| Job | Conclusion | Started | Completed |\n|---|---|---|---|\n"
        "| [x](https://example.invalid) | failure | - | - |\n\n"
        "**PASSED**: 17 passed, 0 failed, 0 errors, 0 skipped of 17 tests in 0.26s\n"
        "**PASSED**: 17 passed, 0 failed, 0 errors, 0 skipped of 17 tests in 0.25s\n"
    )
    (evidence / "ci" / "student-1.md").write_text(record, encoding="utf-8")
    (evidence / "ci" / "student-2.md").write_text(
        record.replace("**success**", "**failure**").replace("0 failed,", "1 failed,", 1),
        encoding="utf-8",
    )

    lines = report.ci_evidence("")

    row = next(line for line in lines if line.startswith("| 1 |"))
    assert (
        "[#353](https://github.com/MattShelton04/41026ASDProject/actions/runs/38719115720)" in row
    )
    assert "| success |" in row and "`d449a43`" in row
    assert "34 passed, 0 failed (2 reports)" in row
    assert "[record](" in row
    owners = [match["owner"] for match in _todos(lines)]
    assert report.TEAM["1"] not in owners
    assert owners.count(report.TEAM["2"]) == 1
    assert "1 failed (2 reports)" in next(line for line in lines if line.startswith("| 2 |"))


def test_review_summary_shows_verdict_checklist_run_log_and_summary(evidence: Path) -> None:
    reviews = evidence / "reviews"
    reviews.mkdir()
    (reviews / "testing-review.md").write_text(
        "# Testing Report Review\n\n| Field | Value |\n|---|---|\n"
        "| Verdict | **pass_with_risks** |\n"
        "| Engine | AI-mode run through the shared agent loop |\n"
        "| Loop run ID | `7d700a5f-6334-49ff-8532-1ca0a96ab79d` (AI-mode Activity history) |\n"
        "| Provider / model | openai / gpt-5.6-terra |\n"
        "| Started / finished | 2026-10-09T09:54:53Z / 2026-10-09T09:55:06Z |\n\n"
        "## Summary\n\nEvery student's endpoints\npassed.\n\n## Checklist (24/26 passed)\n",
        encoding="utf-8",
    )
    (reviews / "testing-validation-log.jsonl").write_text('{"a": 1}\n{"b": 2}\n', encoding="utf-8")

    lines = report.review_summary("testing")

    assert "| **pass_with_risks** | 24/26 passed | AI-mode, openai / gpt-5.6-terra" in lines[2]
    assert "`7d700a5f`" in lines[2] and "2026-10-09" in lines[2] and "2 entries" in lines[2]
    assert lines[-1].startswith("> Every student's endpoints passed. ([full review](")
    assert not _todos(lines)


def test_multi_agent_runs_and_history_come_from_the_export(evidence: Path) -> None:
    export = evidence / "multi-agent" / "student-1" / "run-a"
    export.mkdir(parents=True)
    run = {
        "id": "18740ca5-5fec-482a-a279-fe179a6d25a6",
        "state": "partially_accepted",
        "decisions": [{"decision": "correct"}, {"decision": "partial"}],
    }
    (export / "run.json").write_text(json.dumps(run), encoding="utf-8")
    history = [
        {"run_id": run["id"], "at": "2026-10-10T01:18:30Z", "round": 1, "to_state": "planning",
         "actor": "multi-agent-server"},
        {"run_id": run["id"], "at": "2026-10-10T01:21:32Z", "round": 2,
         "from_state": "awaiting_human", "to_state": "partially_accepted", "actor": "matthew"},
    ]  # fmt: skip
    (export / "workflow_history.jsonl").write_text(
        "".join(json.dumps(item) + "\n" for item in history), encoding="utf-8"
    )
    audit = [{"event": "agent.handoff"}] * 3 + [{"event": "tool.call"}] * 2
    (export / "coordination_audit.jsonl").write_text(
        "".join(json.dumps(item) + "\n" for item in audit), encoding="utf-8"
    )
    broken = evidence / "multi-agent" / "student-2" / "broken"
    broken.mkdir(parents=True)
    (broken / "run.json").write_text("{not json", encoding="utf-8")

    rows = report.multi_agent_runs("")

    row = next(line for line in rows if line.startswith("| 1 |"))
    assert "[`18740ca5`](" in row and "| 2 | 5 | 3 | 2 | correct → partial |" in row
    assert row.endswith("| `partially_accepted` |")
    assert {match["owner"] for match in _todos(rows)} == {
        report.TEAM[number] for number in ("2", "3", "4", "5")
    }
    block = report.workflow_history("multi-agent/student-1/run-a")
    assert block[0] == "```text" and block[-1] == "```"
    assert "01:21:32 r2 awaiting_human -> partially_accepted" in block[3]


def test_local_and_cloud_evidence_summarise_their_reports(evidence: Path) -> None:
    (evidence / "local").mkdir()
    (evidence / "local" / "local-deployment-report.md").write_text(
        "# Local deployment report\n\n**Verdict: PASSED**, 3 of 3 checks passed.\n\n"
        "| Field | Value |\n|---|---|\n| Captured | 2026-10-16T08:38:05+00:00 |\n"
        "| Commit | `d449a43455ca6b20365ed95d1560aa3546b504ab` on `main` |\n\n"
        "## Terminals\n\n| # | Terminal | Ran as | Foreground command | Log | Bytes |\n"
        "|---|---|---|---|---|---|\n"
        "| 3 | MCP | managed | `dev.py ai serve mcp` "
        "| [terminal-3-mcp.log](terminal-3-mcp.log) | 9 |\n\n"
        "## All checks\n\n### Host AI services\n\n| Result | Check |\n|---|---|\n"
        "| PASS | mcp is a host process |\n| PASS | mcp is ready |\n\n### Data\n\n"
        "| Result | Check |\n|---|---|\n| PASS | seeded |\n",
        encoding="utf-8",
    )
    cloud = evidence / "cloud"
    cloud.mkdir()
    (cloud / "cloud-deployment-report.md").write_text(
        "| Item | Value |\n|---|---|\n| Result | **succeeded** |\n"
        "| Public URL | https://example.invalid |\n| AI tier | disabled |\n",
        encoding="utf-8",
    )
    (cloud / "release-decision.md").write_text(
        "| Field | Value |\n|---|---|\n| Decision | **RELEASE** |\n"
        "| Decided by | Matthew Shelton |\n| Decided at | 2026-10-20T01:00:00Z |\n",
        encoding="utf-8",
    )

    local = report.local_evidence("")
    assert "**PASSED**, 3 of 3 checks passed, captured 2026-10-16 at commit `d449a43`" in local[0]
    assert "| Host AI services | 2 | 0 |" in local and "| Data | 1 | 0 |" in local
    assert any(
        line.startswith("| MCP | managed | `dev.py ai serve mcp` |")
        and "terminal-3-mcp.log" in line
        for line in local
    )
    assert not _todos(local)
    summary = report.cloud_summary("")
    assert "| Deployment | **succeeded**" in summary[2]
    assert any("**RELEASE** by Matthew Shelton, 2026-10-20" in line for line in summary)
    assert not _todos(summary)


def test_committed_evidence_renders_without_errors() -> None:
    security = report.security_summary("")
    assert any(line.startswith("| Ruff |") for line in security)
    assert any(line.startswith("| Student 5 |") for line in security)
    runs = report.multi_agent_runs("student-1")
    assert any("18740ca5" in line for line in runs)
    assert report.workflow_history("multi-agent/student-1/18740ca5-ui")[0] == "```text"


def test_committed_figures_match_their_mermaid_sources() -> None:
    report_pdf.validate_diagrams(report.SPEC)
    source = report.SOURCE.read_text(encoding="utf-8")
    for asset in report.SPEC.diagram_pairs.values():
        assert f"assets/release-2/{asset}" in source


@pytest.fixture
def complete_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    """A tiny real Git repository makes commit and evidence checks deterministic."""

    def git(*arguments: str) -> str:
        completed = subprocess.run(  # noqa: S603 - fixed git argv, no shell
            ["git", "-C", str(tmp_path), *arguments],  # noqa: S607 - git is resolved from the developer PATH
            capture_output=True,
            text=True,
            check=True,
        )
        return completed.stdout.strip()

    git("init", "--quiet")
    git("config", "user.name", "Report test")
    git("config", "user.email", "report-test@example.invalid")
    (tmp_path / "evidence.txt").write_text("Recorded validation; fixture data.\n", encoding="utf-8")
    git("add", "evidence.txt")
    git("commit", "--quiet", "-m", "test: retain evidence")
    baseline = git("rev-parse", "HEAD")
    monkeypatch.setattr(report, "ROOT", tmp_path)
    repository = report_pdf.REPOSITORY_URL
    workflow_url = f"{repository}/actions/runs/123"
    sections = {key: key.replace("_", " ").title() for key in report.REQUIRED_SECTIONS}
    evidence = [
        {
            "kind": kind,
            "section": sections["architecture"],
            "boundary": "Recorded fixture evidence.",
            **({"url": workflow_url} if kind == "cloud-workflow" else {"path": "evidence.txt"}),
        }
        for kind in report.SHARED_EVIDENCE
    ] + [
        {
            "kind": kind,
            "student": int(student),
            "section": sections["architecture"],
            "path": "evidence.txt",
            "boundary": "Recorded fixture evidence.",
        }
        for student in report.TEAM
        for kind in report.STUDENT_EVIDENCE
    ]
    metadata = {
        "schema_version": 1,
        "baseline": "[[BASELINE]]",
        "repository_url": repository,
        "showcase_url": "https://youtu.be/example",
        "sections": sections,
        "evidence": evidence,
        "contributions": [
            {"student": int(student), "section": f"Student {student}", "commits": [baseline[:7]]}
            for student in report.TEAM
        ],
        "attendance": {int(student): f"{name} presented." for student, name in report.TEAM.items()},
    }
    content = (
        "# Report\n\n| Field | Value |\n|---|---|\n"
        f"| Repository | [Repository]({repository}) |\n"
        "| Showcase video | [Showcase](https://youtu.be/example) |\n"
        "| Commit reference | `[[BASELINE]]` |\n\n"
        "<!-- RELEASE2_METADATA\n" + yaml.safe_dump(metadata) + "-->\n\n"
    )
    for key, title in sections.items():
        content += f"## {title}\n\nDocumented {key} content.\n\n"
        if key == "architecture":
            content += f"[Evidence](evidence.txt) and [workflow run]({workflow_url}).\n\n"
        if key == "commits":
            content += f"[History]({repository}/commits/main)\n\n"
        if key == "contributions":
            for student in report.TEAM:
                content += f"### Student {student}\n\n{baseline[:7]} delivered work.\n\n"
        if key == "showcase":
            content += " ".join(f"{name} presented." for name in report.TEAM.values()) + "\n\n"
    source = tmp_path / "report.md"
    source.write_text(content, encoding="utf-8")
    return source, baseline


def test_final_accepts_a_complete_traceable_report(
    complete_report: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    source, baseline = complete_report
    assert report.final_content_blockers(source, baseline) == []
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(report_pdf, "build", lambda *args: calls.append(args))
    assert report.main(["--source", str(source), "--final", "--baseline", baseline]) == 0
    assert calls[0][1] == report.OUTPUT


def test_final_refuses_todos_and_pending_images(
    complete_report: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    source, baseline = complete_report
    source.write_text(
        source.read_text(encoding="utf-8")
        + "\n[[TODO: Derek Song | Finish F5]]\n\n![Figure 9 Pending](missing.png)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(report_pdf, "build", lambda *args: pytest.fail("must not build"))
    assert report.main(["--source", str(source), "--final", "--baseline", baseline]) == 1
    blockers = report_pdf.review(source, report.SPEC).final_blockers(report.SPEC, baseline)
    assert any("TODO for Derek Song" in item for item in blockers)
    assert any("missing image missing.png" in item for item in blockers)


def test_final_requires_each_students_evidence_and_commits(
    complete_report: tuple[Path, str],
) -> None:
    source, baseline = complete_report
    metadata = report._metadata(source)
    metadata["evidence"] = [
        item
        for item in metadata["evidence"]
        if not (item.get("student") == 3 and item["kind"] == "ci")
        and item["kind"] != "release-decision"
    ]
    metadata["contributions"] = [item for item in metadata["contributions"] if item["student"] != 4]
    text = source.read_text(encoding="utf-8")
    start, end = text.index("<!-- RELEASE2_METADATA"), text.index("-->") + 3
    source.write_text(
        text[:start] + "<!-- RELEASE2_METADATA\n" + yaml.safe_dump(metadata) + "-->" + text[end:],
        encoding="utf-8",
    )
    blockers = report.final_content_blockers(source, baseline)
    assert "missing evidence: ci for Student 3" in blockers
    assert "missing evidence: release-decision" in blockers
    assert "missing contribution log and commits for Student 4" in blockers


def test_final_rejects_unlinked_untracked_or_changed_evidence(
    complete_report: tuple[Path, str],
) -> None:
    source, baseline = complete_report
    (source.parent / "new.txt").write_text("Uncommitted validation", encoding="utf-8")
    source.write_text(
        source.read_text(encoding="utf-8").replace("(evidence.txt)", "(new.txt)", 1),
        encoding="utf-8",
    )
    blockers = report.final_content_blockers(source, baseline)
    assert any("evidence.txt is not shown or linked" in issue for issue in blockers)
    (source.parent / "evidence.txt").write_text("Edited after the baseline", encoding="utf-8")
    source.write_text(
        source.read_text(encoding="utf-8").replace("(new.txt)", "(evidence.txt)", 1),
        encoding="utf-8",
    )
    assert any(
        "differs from the baseline evidence" in issue
        for issue in report.final_content_blockers(source, baseline)
    )


def test_final_rejects_fake_baseline_missing_video_and_commit_log(
    complete_report: tuple[Path, str],
) -> None:
    source, baseline = complete_report
    assert any(
        "does not resolve" in issue for issue in report.final_content_blockers(source, "0" * 40)
    )
    source.write_text(
        source.read_text(encoding="utf-8")
        .replace("[Showcase](https://youtu.be/example)", "Pending")
        .replace("/commits/main", "/commits"),
        encoding="utf-8",
    )
    blockers = report.final_content_blockers(source, baseline)
    assert "cover and metadata must contain the same HTTPS showcase URL" in blockers
    assert any("commit log section must link" in issue for issue in blockers)
