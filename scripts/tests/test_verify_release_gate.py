"""The cloud deployment CI gate, against canned ``gh api`` JSON (no network, no gh)."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from scripts import verify_release_gate as gate_module
from scripts.verify_release_gate import (
    REQUIRED_WORKFLOWS,
    Gate,
    GateError,
    main,
    verify,
)

REPO = "MattShelton04/41026ASDProject"
DEPLOY = "d" * 40
PARENT = "c" * 40
OLDER = "b" * 40
NEWER = "e" * 40  # pushed after the deploy commit: not an ancestor


def run(
    number: int,
    head: str,
    *,
    status: str = "completed",
    conclusion: str | None = "success",
    event: str = "push",
) -> dict[str, Any]:
    return {
        "id": 9_000 + number,
        "run_number": number,
        "run_attempt": 1,
        "head_sha": head,
        "event": event,
        "status": status,
        "conclusion": conclusion if status == "completed" else None,
        "html_url": f"https://github.com/{REPO}/actions/runs/{9_000 + number}",
        "created_at": f"2026-10-17T0{number % 10}:00:00Z",
    }


class FakeGh:
    """Answers the two ``gh api`` paths the gate uses, recording each call."""

    def __init__(
        self,
        runs: dict[str, list[dict[str, Any]]],
        *,
        relations: dict[str, str] | None = None,
    ) -> None:
        self.runs = runs
        self.relations = {PARENT: "ahead", OLDER: "ahead", NEWER: "behind", **(relations or {})}
        self.calls: list[tuple[str, str | None]] = []

    def __call__(self, path: str, jq: str | None = None) -> Any:
        self.calls.append((path, jq))
        prefix = f"repos/{REPO}/"
        assert path.startswith(prefix), path
        rest = path[len(prefix) :]
        if rest.startswith("actions/workflows/"):
            file = rest.split("/")[2]
            assert "branch=main" in rest and "exclude_pull_requests=true" in rest
            assert jq is not None and jq.startswith(".workflow_runs")
            return list(self.runs.get(file, []))
        if rest.startswith("compare/"):
            base, _, head = rest[len("compare/") :].partition("...")
            assert head == DEPLOY
            if base not in self.relations:
                raise GateError("gh api compare failed: Not Found")
            return {"status": self.relations[base], "ahead_by": 3}
        raise AssertionError(f"unexpected gh api call {path}")


def green(**overrides: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    runs: dict[str, list[dict[str, Any]]] = {
        "integration-ci.yml": [run(5, DEPLOY)],
        "student-1.yml": [run(4, DEPLOY)],
        "student-2.yml": [run(3, PARENT)],
        "student-3.yml": [run(2, OLDER)],
        "student-4.yml": [run(6, NEWER), run(1, PARENT)],
        "student-5.yml": [run(7, DEPLOY, event="pull_request"), run(2, OLDER)],
    }
    runs.update(overrides)
    return runs


def _verdicts(fake: FakeGh, **kwargs: Any) -> dict[str, gate_module.WorkflowVerdict]:
    result = verify(Gate(fake, REPO, DEPLOY), log=lambda _: None, **kwargs)
    return {verdict.workflow: verdict for verdict in result}


def test_all_required_workflows_green_passes_and_records_the_deciding_runs() -> None:
    fake = FakeGh(green())

    verdicts = _verdicts(fake)

    assert list(verdicts) == [
        "Integration CI",
        *(f"Student {n} CI" for n in range(1, 6)),
    ]
    assert all(verdict.passed for verdict in verdicts.values())
    assert verdicts["Integration CI"].relation == "identical"
    assert verdicts["Student 2 CI"].relation == "ancestor"
    assert verdicts["Student 2 CI"].head_sha == PARENT
    # A newer, non-ancestor run is skipped in favour of the ancestor run.
    assert verdicts["Student 4 CI"].run_number == 1
    # Pull-request runs never count.
    assert verdicts["Student 5 CI"].run_number == 2
    assert "3 commit(s) earlier" in verdicts["Student 3 CI"].detail


def test_integration_ci_must_match_the_deploy_commit_exactly() -> None:
    fake = FakeGh(green(**{"integration-ci.yml": [run(5, PARENT)]}))

    verdict = _verdicts(fake)["Integration CI"]

    assert verdict.passed is False and verdict.state == "missing"
    assert "this commit" in verdict.detail


@pytest.mark.parametrize(
    ("conclusion", "state"),
    [("failure", "failure"), ("cancelled", "failure"), ("timed_out", "failure")],
)
def test_a_latest_run_that_did_not_succeed_fails_the_gate(conclusion: str, state: str) -> None:
    # The most recent run at an ancestor failed, even though an older one succeeded.
    fake = FakeGh(
        green(**{"student-3.yml": [run(8, PARENT, conclusion=conclusion), run(2, OLDER)]})
    )

    verdict = _verdicts(fake)["Student 3 CI"]

    assert verdict.passed is False
    assert verdict.state == state
    assert conclusion in verdict.detail
    assert verdict.run_number == 8


def test_no_run_at_the_commit_or_an_ancestor_is_missing() -> None:
    fake = FakeGh(green(**{"student-2.yml": [run(9, NEWER), run(1, "f" * 40)]}))

    verdict = _verdicts(fake)["Student 2 CI"]

    assert verdict.state == "missing" and not verdict.passed
    assert "an ancestor" in verdict.detail


def test_pending_runs_are_waited_for_until_they_complete() -> None:
    sequence = iter(
        [
            [run(9, DEPLOY, status="in_progress"), run(2, OLDER)],
            [run(9, DEPLOY, status="in_progress"), run(2, OLDER)],
            [run(9, DEPLOY), run(2, OLDER)],
        ]
    )

    class Waiting(FakeGh):
        def __call__(self, path: str, jq: str | None = None) -> Any:
            if "workflows/student-1.yml" in path:
                self.calls.append((path, jq))
                return next(sequence)
            return super().__call__(path, jq)

    fake = Waiting(green())
    sleeps: list[float] = []
    clock = {"now": 0.0}

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock["now"] += seconds

    verdicts = _verdicts(
        fake, wait_seconds=600, poll_seconds=60, sleep=sleep, monotonic=lambda: clock["now"]
    )

    assert verdicts["Student 1 CI"].passed is True
    assert sleeps == [60, 60]


def test_a_run_still_pending_when_time_runs_out_fails() -> None:
    fake = FakeGh(green(**{"student-1.yml": [run(9, DEPLOY, status="queued"), run(2, OLDER)]}))
    clock = {"now": 0.0}

    def sleep(seconds: float) -> None:
        clock["now"] += seconds

    verdict = _verdicts(
        fake, wait_seconds=120, poll_seconds=60, sleep=sleep, monotonic=lambda: clock["now"]
    )["Student 1 CI"]

    assert verdict.state == "pending" and not verdict.passed
    assert "queued" in verdict.detail and "2 minute(s)" in verdict.detail


def test_without_waiting_a_pending_run_fails_immediately() -> None:
    fake = FakeGh(green(**{"integration-ci.yml": [run(5, DEPLOY, status="in_progress")]}))

    verdict = _verdicts(fake, sleep=lambda _: pytest.fail("must not sleep"))["Integration CI"]

    assert verdict.state == "pending"


def test_an_unknown_commit_in_the_history_is_treated_as_unrelated() -> None:
    fake = FakeGh(green(**{"student-2.yml": [run(9, "a" * 40), run(1, PARENT)]}))

    verdict = _verdicts(fake)["Student 2 CI"]

    assert verdict.passed is True and verdict.run_number == 1


def test_relation_lookups_are_cached_and_bounded() -> None:
    many = [run(n, f"{n:040x}") for n in range(1, 40)]
    fake = FakeGh(green(**{"student-2.yml": many}))

    verdict = _verdicts(fake)["Student 2 CI"]

    compares = [path for path, _ in fake.calls if "/compare/" in path]
    assert verdict.state == "missing"
    assert len(compares) <= gate_module.MAX_COMPARISONS + 4  # other workflows' ancestors


def test_main_writes_json_and_markdown_and_sets_the_exit_code(tmp_path: Path) -> None:
    out = tmp_path / "gate"
    status = main(
        ["--repo", REPO, "--sha", DEPLOY.upper(), "--output-dir", str(out)],
        api=FakeGh(green()),
        clock=lambda: datetime(2026, 10, 17, 4, 0, tzinfo=UTC),
    )

    assert status == 0
    document = json.loads((out / "release-gate.json").read_text(encoding="utf-8"))
    assert document["passed"] is True
    assert document["deploy_sha"] == DEPLOY
    assert document["checked_at"] == "2026-10-17T04:00:00+00:00"
    assert document["required_workflows"] == list(gate_module.REQUIRED_WORKFLOW_NAMES)
    assert [item["workflow"] for item in document["workflows"]] == document["required_workflows"]
    first = document["workflows"][0]
    assert first["run_url"].endswith("/actions/runs/9005")
    markdown = (out / "release-gate.md").read_text(encoding="utf-8")
    assert "**PASSED**" in markdown
    assert "| Student 2 CI | success | [#3](" in markdown

    failing = FakeGh(green(**{"student-5.yml": [run(3, DEPLOY, conclusion="failure")]}))
    assert main(["--repo", REPO, "--sha", DEPLOY, "--output-dir", str(out)], api=failing) == 1
    document = json.loads((out / "release-gate.json").read_text(encoding="utf-8"))
    assert document["passed"] is False


@pytest.mark.parametrize(
    "arguments",
    [
        ["--repo", REPO, "--sha", "abc"],
        ["--repo", "not a repo", "--sha", DEPLOY],
        ["--repo", REPO, "--sha", DEPLOY, "--branch", "bad branch"],
    ],
    ids=["short-sha", "bad-repo", "bad-branch"],
)
def test_main_rejects_invalid_arguments(tmp_path: Path, arguments: list[str]) -> None:
    def api(path: str, jq: str | None = None) -> Any:
        raise AssertionError("must not call GitHub")

    assert main([*arguments, "--output-dir", str(tmp_path)], api=api) == 2


def test_a_github_error_is_reported_as_unavailable_not_failed(tmp_path: Path) -> None:
    def api(path: str, jq: str | None = None) -> Any:
        raise GateError("gh api failed: HTTP 401")

    assert main(["--repo", REPO, "--sha", DEPLOY, "--output-dir", str(tmp_path)], api=api) == 2
    assert not (tmp_path / "release-gate.json").exists()


def test_gh_api_parses_output_and_maps_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(arguments: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        if "boom" in arguments[2]:
            raise subprocess.CalledProcessError(1, arguments, stderr="HTTP 404: Not Found\n")
        if "slow" in arguments[2]:
            raise subprocess.TimeoutExpired(arguments, 60)
        if "garbage" in arguments[2]:
            return subprocess.CompletedProcess(arguments, 0, stdout="not json")
        return subprocess.CompletedProcess(arguments, 0, stdout='{"ok": true}')

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert gate_module.gh_api("repos/x/y", ".a") == {"ok": True}
    assert calls[0] == ["gh", "api", "repos/x/y", "--jq", ".a"]
    for path, message in (("boom", "Not Found"), ("slow", "timed out"), ("garbage", "JSON")):
        with pytest.raises(GateError, match=message):
            gate_module.gh_api(path)

    def missing(arguments: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("gh")

    monkeypatch.setattr(subprocess, "run", missing)
    with pytest.raises(GateError, match="not installed"):
        gate_module.gh_api("repos/x/y")


def test_the_workflow_files_named_by_the_gate_exist_with_those_names() -> None:
    import yaml

    root = Path(__file__).resolve().parents[2] / ".github" / "workflows"
    for rule in REQUIRED_WORKFLOWS:
        document = yaml.safe_load((root / rule.file).read_text(encoding="utf-8"))
        assert document["name"] == rule.name, rule.file
    assert [rule.file for rule in REQUIRED_WORKFLOWS] == [
        "integration-ci.yml",
        *(f"student-{n}.yml" for n in range(1, 6)),
    ]
