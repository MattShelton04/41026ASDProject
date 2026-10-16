"""CI evidence collection uses canned ``gh`` output and never reaches GitHub."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from scripts.collect_ci_evidence import (
    REPOSITORY_ROOT,
    EvidenceError,
    bound_log,
    collect,
    main,
    render,
    run_gh,
)

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
            "completedAt": "2026-10-09T04:08:03Z",
            "conclusion": "success",
            "databaseId": 50,
            "name": "Feature 1 browser forms",
            "startedAt": "2026-10-09T04:06:48Z",
            "url": "https://github.com/o/r/actions/runs/37095447883/job/50",
            "steps": [{"conclusion": "success", "name": "Run form checks", "number": 1}],
        },
        {
            "completedAt": "2026-10-09T04:10:03Z",
            "conclusion": "success",
            "databaseId": 51,
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
        },
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
_STACK = "Feature 1 integrated stack"
_ENDPOINT_STEP = "Run Feature 1 endpoint tests on the feature origin"
JOB_LOG = "\n".join(
    [
        f"{_STACK}\tBuild cached Shared and Feature 1 targets\t2026-10-09T04:07:00Z #12 DONE",
        f"{_STACK}\t{_ENDPOINT_STEP}\t2026-10-09T04:09:00Z \x1b[32mPASSED\x1b[0m "
        "student-1/tests/endpoints/test_search.py::test_ok",
        f"{_STACK}\t{_ENDPOINT_STEP}\t2026-10-09T04:09:01Z token=ghp_" + "a" * 36,
        f"{_STACK}\t{_ENDPOINT_STEP}\t2026-10-09T04:09:02Z 2 passed in 0.42s",
        f"{_STACK}\tSmoke the Shared and Feature 1 boundary\t2026-10-09T04:09:30Z ok",
    ]
)


class FakeGh:
    """Records ``gh`` invocations and serves canned output for each subcommand."""

    def __init__(
        self,
        *,
        runs: list[dict[str, Any]] | None = None,
        run: dict[str, Any] | None = None,
        artifact: dict[str, str] | None = None,
        log: str | None = JOB_LOG,
    ) -> None:
        self.calls: list[list[str]] = []
        self.runs = [{"databaseId": RUN_ID}] if runs is None else runs
        self.run = RUN if run is None else run
        self.artifact = artifact
        self.log = log

    def __call__(self, arguments: Sequence[str]) -> str:
        call = list(arguments)
        self.calls.append(call)
        match call[:2]:
            case ["run", "list"]:
                return json.dumps(self.runs)
            case ["run", "view"] if "--log" in call:
                if self.log is None:
                    raise EvidenceError("gh run view failed: log not found")
                return self.log
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
    assert "| Status | completed |\n| Conclusion | **success** |" in markdown
    assert gh.calls[3] == ["run", "view", "--job", "51", "--log"]
    assert len(gh.calls) == 4, "only the job with endpoint steps is logged"
    assert evidence.run_log is not None
    assert evidence.run_log.jobs == ("Feature 1 integrated stack",)
    assert evidence.run_log.scope == "Endpoint-test steps"
    assert "[`student-1/run.log`](student-1/run.log)" in markdown
    assert "[`student-1/student-1-feature-origin.xml`]" in markdown
    assert "run endpoint tests \\| with JUnit" in markdown
    assert "| 9 | Run Feature 1 endpoint tests on the feature origin | success |" in markdown
    assert "### `student-1-feature-origin.xml`" in markdown
    assert "**PASSED**: 2 passed, 0 failed" in markdown
    assert "test_bad_q[missing-q]` | passed |" in markdown
    assert markdown.endswith("1 secret-shaped line(s) redacted)\n")


def test_explicit_run_id_skips_listing_and_passes_the_repository() -> None:
    gh = FakeGh(artifact={"nested/report.xml": PASSING_JUNIT})

    evidence = collect(gh, 1, branch="ignored", run_id=RUN_ID, repository="o/r")

    assert [call[:2] for call in gh.calls] == [
        ["run", "view"],
        ["run", "download"],
        ["run", "view"],
    ]
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

    single = FakeGh(
        artifact={"a.xml": '<testsuite><testcase classname="c" name="only"/></testsuite>'}
    )
    assert main(["--student", "1", "--output-dir", str(tmp_path / "one")], gh=single) == 1
    assert "at least 2 passing tests" in capsys.readouterr().err

    red = FakeGh(artifact={"a.xml": FAILING_JUNIT})
    red_dir = tmp_path / "red"
    assert main(["--student", "1", "--output-dir", str(red_dir)], gh=red) == 1
    assert not (red_dir / "student-1.md").exists()
    assert "--allow-failed-endpoints" in capsys.readouterr().err
    arguments = ["--student", "1", "--output-dir", str(red_dir), "--allow-failed-endpoints"]
    assert main(arguments, gh=red) == 0
    assert "**FAILED**" in (red_dir / "student-1.md").read_text(encoding="utf-8")


def test_main_retains_junit_xml_and_a_redacted_endpoint_run_log(tmp_path: Path) -> None:
    gh = FakeGh(artifact={"origin.xml": PASSING_JUNIT, "edge/shared.xml": PASSING_JUNIT})
    stale = tmp_path / "student-1" / "old-run.xml"
    stale.parent.mkdir(parents=True)
    stale.write_text(FAILING_JUNIT, encoding="utf-8")
    keep = tmp_path / "student-1" / "README.md"
    keep.write_text("not written by the collector", encoding="utf-8")

    assert main(["--student", "1", "--output-dir", str(tmp_path)], gh=gh) == 0

    raw = tmp_path / "student-1"
    assert sorted(path.name for path in raw.iterdir()) == [
        "README.md",
        "edge-shared.xml",
        "origin.xml",
        "run.log",
    ], "the previous run's XML is replaced; unrelated files are kept"
    assert (raw / "origin.xml").read_text(encoding="utf-8") == PASSING_JUNIT
    log = (raw / "run.log").read_text(encoding="utf-8")
    assert "\x1b[" not in log
    assert "PASSED student-1/tests/endpoints/test_search.py::test_ok" in log
    assert "2 passed in 0.42s" in log
    assert "ghp_" not in log and "[line redacted: matched a secret pattern]" in log
    assert "Build cached" not in log and "Smoke" not in log, "only endpoint steps are kept"
    markdown = (tmp_path / "student-1.md").read_text(encoding="utf-8")
    assert "1 secret-shaped line(s) redacted" in markdown


def test_unknown_step_names_locate_endpoint_steps_by_their_run_command() -> None:
    prefix = "Feature 1 integrated stack\tUNKNOWN STEP\t2026-10-15T10:17:0"
    unknown = "\n".join(
        [
            f"{prefix}1Z ##[group]Run docker buildx bake shared feature-1",
            f"{prefix}2Z #67 DONE 0.1s",
            f"{prefix}3Z ##[group]Run uv run pytest student-1/tests/endpoints -m endpoint",
            f"{prefix}4Z PASSED test_accepted_address_returns_typed_ranked_matches",
            f"{prefix}5Z ##[group]Run docker compose logs",
            f"{prefix}6Z f1-backend | ready",
        ]
    )
    evidence = collect(FakeGh(artifact={"a.xml": PASSING_JUNIT}, log=unknown), 1, branch="main")
    assert evidence.run_log is not None
    assert evidence.run_log.scope == "Endpoint-test steps, matched by run command,"
    assert "PASSED test_accepted_address" in evidence.run_log.text
    assert "#67 DONE" not in evidence.run_log.text
    assert "f1-backend | ready" not in evidence.run_log.text


def test_unknown_step_names_keep_the_whole_job_log_and_missing_logs_are_noted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    unknown = "\n".join(
        f"Feature 1 integrated stack\tUNKNOWN STEP\t2026-10-09T04:09:0{i}Z line {i}"
        for i in range(3)
    )
    evidence = collect(FakeGh(artifact={"a.xml": PASSING_JUNIT}, log=unknown), 1, branch="main")
    assert evidence.run_log is not None
    assert evidence.run_log.scope.startswith("Complete job log")
    assert evidence.run_log.text.count("UNKNOWN STEP") == 3

    no_log = FakeGh(artifact={"a.xml": PASSING_JUNIT}, log=None)
    assert main(["--student", "1", "--output-dir", str(tmp_path)], gh=no_log) == 0
    assert not (tmp_path / "student-1" / "run.log").exists()
    assert "Run log: not retained" in (tmp_path / "student-1.md").read_text(encoding="utf-8")
    assert "warning: The log of job `Feature 1 integrated stack`" in capsys.readouterr().err


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_retained_evidence_logs_are_not_gitignored() -> None:
    """`*.log` and `logs/` are ignored repository-wide; committed evidence logs must not be."""
    evidence = [
        "docs/release-2/evidence/ci/student-1/run.log",
        "docs/release-2/evidence/ci/student-1/feature-origin.xml",
        "docs/release-2/evidence/cloud/deploy.log",
        "docs/release-2/evidence/cloud/logs/deploy.log",
        "docs/release-2/evidence/cloud/logs/smoke.txt",
    ]
    completed = subprocess.run(  # noqa: S603 - fixed git argv, no shell
        [shutil.which("git") or "git", "check-ignore", "--no-index", *evidence, "student-1/x.log"],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.stdout.split() == ["student-1/x.log"], completed.stderr


def test_bound_log_keeps_whole_lines_from_the_end() -> None:
    text = "\n".join(f"line {number:04d}" for number in range(1000))

    kept, dropped, redacted = bound_log(text, max_bytes=100)

    assert len(kept.encode("utf-8")) <= 100
    assert kept.startswith("line ") and kept.endswith("line 0999\n")
    assert dropped == len(text) + 1 - len(kept)
    assert redacted == 0
    assert bound_log("", max_bytes=10) == ("", 0, 0)


def test_main_all_students_reports_each_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeGh(artifact={"a.xml": PASSING_JUNIT})

    def only_student_1_has_runs(arguments: Sequence[str]) -> str:
        if "--workflow" in arguments and "student-1.yml" not in arguments:
            return "[]"
        return fake(arguments)

    assert main(["--all", "--output-dir", str(tmp_path)], gh=only_student_1_has_runs) == 1
    assert sorted(path.name for path in tmp_path.iterdir()) == ["student-1", "student-1.md"]
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
    calls: list[dict[str, object]] = []

    def completed(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(kwargs)
        return subprocess.CompletedProcess(["gh"], 0, stdout="[]", stderr="")

    monkeypatch.setattr(subprocess, "run", completed)
    assert run_gh(["run", "list"]) == "[]"
    # Run logs are UTF-8; the Windows locale codec must never decode them.
    assert calls[0]["encoding"] == "utf-8"
    assert calls[0]["errors"] == "replace"

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
