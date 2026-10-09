"""CI evidence collection uses canned ``gh`` output and never reaches GitHub."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from scripts.collect_ci_evidence import EvidenceError, collect, main, render, run_gh

RUN_ID = 37095447883
RUN = {
    "attempt": 1,
    "conclusion": "success",
    "createdAt": "2026-10-09T04:06:45Z",
    "databaseId": RUN_ID,
    "displayTitle": "ci(feature-1): run endpoint tests | with JUnit",
    "event": "push",
    "headBranch": "main",
    "headSha": "69b20c4b70860f1dfdae3fad06fe9c8805cb5d54",
    "jobs": [
        {
            "completedAt": "2026-10-09T04:10:03Z",
            "conclusion": "success",
            "name": "Feature 1 integrated stack",
            "startedAt": "2026-10-09T04:06:48Z",
            "url": "https://github.com/o/r/actions/runs/37095447883/job/1",
            "steps": [
                {"conclusion": "success", "name": "Set up job", "number": 1},
                {
                    "conclusion": "success",
                    "name": "Run Feature 1 endpoint tests on the feature origin",
                    "number": 9,
                },
            ],
        }
    ],
    "number": 342,
    "startedAt": "2026-10-09T04:06:45Z",
    "status": "completed",
    "updatedAt": "2026-10-09T04:10:04Z",
    "url": "https://github.com/o/r/actions/runs/37095447883",
    "workflowName": "Student 1 CI",
}
PASSING_JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="2">
  <testcase classname="student-1.tests.endpoints.test_search" name="test_ok" time="0.2"/>
  <testcase classname="student-1.tests.endpoints.test_search" name="test_bad_q[missing-q]"
    time="0.01"/>
</testsuite></testsuites>
"""
FAILING_JUNIT = """<testsuite><testcase classname="c" name="test_crud" time="0.3">
  <failure message="expected HTTP 201, got 422">trace</failure></testcase></testsuite>
"""


class FakeGh:
    """Records ``gh`` invocations and serves canned output for each subcommand."""

    def __init__(
        self,
        *,
        runs: list[dict[str, Any]] | None = None,
        run: dict[str, Any] | None = None,
        artifact: dict[str, str] | None = None,
    ) -> None:
        self.calls: list[list[str]] = []
        self.runs = [{"databaseId": RUN_ID}] if runs is None else runs
        self.run = RUN if run is None else run
        self.artifact = artifact

    def __call__(self, arguments: Sequence[str]) -> str:
        call = list(arguments)
        self.calls.append(call)
        match call[:2]:
            case ["run", "list"]:
                return json.dumps(self.runs)
            case ["run", "view"]:
                return json.dumps(self.run)
            case ["run", "download"]:
                if self.artifact is None:
                    raise EvidenceError("gh run download failed: no artifact matches")
                directory = Path(call[call.index("--dir") + 1])
                for name, text in self.artifact.items():
                    (directory / name).parent.mkdir(parents=True, exist_ok=True)
                    (directory / name).write_text(text, encoding="utf-8")
                return ""
        raise AssertionError(f"unexpected gh call {call}")


def test_collects_latest_green_main_run_with_endpoint_table() -> None:
    gh = FakeGh(artifact={"student-1-feature-origin.xml": PASSING_JUNIT, "notes.txt": "x"})

    evidence = collect(gh, 1, branch="main")

    assert gh.calls[0] == [
        "run",
        "list",
        "--workflow",
        "student-1.yml",
        "--branch",
        "main",
        "--status",
        "success",
        "--limit",
        "1",
        "--json",
        "databaseId",
    ]
    assert gh.calls[1][:3] == ["run", "view", str(RUN_ID)]
    assert "headSha" in gh.calls[1][4] and "jobs" in gh.calls[1][4]
    assert gh.calls[2][:5] == ["run", "download", str(RUN_ID), "--name", "student-1-endpoint-tests"]
    assert [report.file_name for report in evidence.endpoint_reports] == [
        "student-1-feature-origin.xml"
    ]
    markdown = render(evidence)
    assert markdown.startswith("# Student 1 CI evidence\n")
    assert f"[#342 (ID {RUN_ID}, attempt 1)]({RUN['url']})" in markdown
    assert "| Head SHA | `69b20c4b70860f1dfdae3fad06fe9c8805cb5d54` |" in markdown
    assert "| Branch | main |" in markdown and "| Event | push |" in markdown
    assert "completed / **success**" in markdown
    assert "run endpoint tests \\| with JUnit" in markdown
    assert "| 9 | Run Feature 1 endpoint tests on the feature origin | success |" in markdown
    assert "### `student-1-feature-origin.xml`" in markdown
    assert "**PASSED**: 2 passed, 0 failed" in markdown
    assert "test_bad_q[missing-q]` | passed |" in markdown
    assert markdown.endswith("|\n")


def test_explicit_run_id_skips_listing_and_passes_the_repository() -> None:
    gh = FakeGh(artifact={"nested/report.xml": PASSING_JUNIT})

    evidence = collect(gh, 1, branch="ignored", run_id=RUN_ID, repository="o/r")

    assert [call[:2] for call in gh.calls] == [["run", "view"], ["run", "download"]]
    assert all(call[-2:] == ["--repo", "o/r"] for call in gh.calls)
    assert evidence.endpoint_reports[0].succeeded is True


def test_run_from_another_workflow_is_refused() -> None:
    gh = FakeGh(run={**RUN, "workflowName": "Student 2 CI"})
    with pytest.raises(EvidenceError, match="belongs to 'Student 2 CI'"):
        collect(gh, 1, branch="main", run_id=RUN_ID)


@pytest.mark.parametrize(
    ("runs", "message"),
    [([], "no successful student-3.yml run"), ([{"databaseId": "x"}], None)],
)
def test_missing_or_malformed_run_list(runs: list[dict[str, Any]], message: str | None) -> None:
    gh = FakeGh(runs=runs)
    if message is None:
        with pytest.raises(ValueError):
            collect(gh, 3, branch="main")
    else:
        with pytest.raises(EvidenceError, match=message):
            collect(gh, 3, branch="main")


def test_invalid_gh_json_is_reported() -> None:
    def broken(arguments: Sequence[str]) -> str:
        return "[" if arguments[1] == "list" else "[]"

    with pytest.raises(EvidenceError, match="run list returned invalid JSON"):
        collect(broken, 1, branch="main")
    with pytest.raises(EvidenceError, match="did not return a JSON object"):
        collect(broken, 1, branch="main", run_id=RUN_ID)


def test_missing_empty_or_corrupt_artifacts_become_notes() -> None:
    missing = collect(FakeGh(), 1, branch="main")
    assert missing.endpoint_reports == ()
    assert "could not be downloaded" in (missing.artifact_note or "")
    assert "could not be downloaded" in render(missing)

    empty = collect(FakeGh(artifact={"summary.md": "# x"}), 1, branch="main")
    assert "contains no JUnit XML report" in (empty.artifact_note or "")

    corrupt = collect(FakeGh(artifact={"bad.xml": "<html/>"}), 1, branch="main")
    assert "is not a JUnit report" in (corrupt.artifact_note or "")


def test_main_writes_green_evidence_and_refuses_red_endpoints(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    green = FakeGh(artifact={"a.xml": PASSING_JUNIT})
    assert main(["--student", "1", "--output-dir", str(tmp_path)], gh=green) == 0
    written = (tmp_path / "student-1.md").read_text(encoding="utf-8")
    assert "**PASSED**" in written
    assert "wrote" in capsys.readouterr().out

    red = FakeGh(artifact={"a.xml": FAILING_JUNIT})
    red_dir = tmp_path / "red"
    assert main(["--student", "1", "--output-dir", str(red_dir)], gh=red) == 1
    assert not (red_dir / "student-1.md").exists()
    assert "--allow-failed-endpoints" in capsys.readouterr().err
    arguments = ["--student", "1", "--output-dir", str(red_dir), "--allow-failed-endpoints"]
    assert main(arguments, gh=red) == 0
    assert "**FAILED**" in (red_dir / "student-1.md").read_text(encoding="utf-8")


def test_main_all_students_reports_each_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeGh(artifact={"a.xml": PASSING_JUNIT})

    def only_student_1_has_runs(arguments: Sequence[str]) -> str:
        if "--workflow" in arguments and "student-1.yml" not in arguments:
            return "[]"
        return fake(arguments)

    assert main(["--all", "--output-dir", str(tmp_path)], gh=only_student_1_has_runs) == 1
    assert sorted(path.name for path in tmp_path.iterdir()) == ["student-1.md"]
    errors = capsys.readouterr().err
    assert all(f"student-{number}: error" in errors for number in range(2, 6))


def test_run_id_requires_a_single_student(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--student", "1", "--student", "2", "--run-id", "5"], gh=FakeGh()) == 2
    assert "exactly one --student" in capsys.readouterr().err


def test_workflow_without_a_name_is_refused(tmp_path: Path) -> None:
    (tmp_path / ".github/workflows").mkdir(parents=True)
    (tmp_path / ".github/workflows/student-1.yml").write_text("on: push\n", encoding="utf-8")
    with pytest.raises(EvidenceError, match="has no workflow name"):
        collect(FakeGh(), 1, branch="main", root=tmp_path)


def test_run_gh_maps_cli_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    def completed(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["gh"], 0, stdout="[]", stderr="")

    monkeypatch.setattr(subprocess, "run", completed)
    assert run_gh(["run", "list"]) == "[]"

    failures: list[BaseException] = [
        FileNotFoundError("gh"),
        subprocess.CalledProcessError(1, ["gh"], output="", stderr="first\nHTTP 404\n"),
        subprocess.CalledProcessError(1, ["gh"], output="", stderr=""),
        subprocess.TimeoutExpired(["gh"], 120),
    ]
    messages = ["not installed", "run view failed: HTTP 404", "run view failed", "timed out"]
    for failure, message in zip(failures, messages, strict=True):

        def raising(*args: object, failure: BaseException = failure, **kwargs: object) -> None:
            raise failure

        monkeypatch.setattr(subprocess, "run", raising)
        with pytest.raises(EvidenceError, match=message):
            run_gh(["run", "view", "1"])
