"""The one-command Release 2 evidence refresh, with every external command faked."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from scripts import refresh_release2_evidence as refresh

HEAD = "f" * 40
STARTED = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)


class Fakes:
    """Answers git, gh and multi-agent-server queries and records every step command."""

    def __init__(self, *, branch: str = "main", origin: str = HEAD, dirty: str = "") -> None:
        self.branch = branch
        self.origin = origin
        self.dirty = dirty
        self.status_after: str | None = None
        self.ran: list[tuple[str, ...]] = []
        self.failing: set[str] = set()
        self.runs: list[dict[str, object]] = []
        self.polls = 0
        self.review_verdict = "fail"

    def read(self, argv: Sequence[str], cwd: Path) -> tuple[int, str]:
        command = tuple(argv)
        if command[:2] == ("git", "branch"):
            return 0, self.branch + "\n"
        if command[:3] == ("git", "rev-parse", "HEAD"):
            return 0, HEAD + "\n"
        if command[:3] == ("git", "rev-parse", "origin/main"):
            return 0, self.origin + "\n"
        if command[:3] == ("git", "rev-parse", "--git-path"):
            return 0, f".git/{command[3]}\n"
        if command[:2] == ("git", "status"):
            if "--" in command:
                return 0, self.dirty
            text = self.status_after if self.status_after is not None and self.ran else ""
            return 0, text
        if command[:2] == ("git", "fetch"):
            return 0, ""
        if command[:3] == ("gh", "run", "list"):
            runs = [
                {"workflowName": name, "status": "completed", "conclusion": "success"}
                for name in refresh.CI_WORKFLOWS
            ]
            return 0, json.dumps(runs)
        if "list" in command and "multi-agent-server" in command:
            self.polls += 1
            visible = self.runs if self.polls > 1 else []
            return 0, json.dumps({"items": visible, "count": len(visible)})
        if "status" in command and "multi-agent-server" in command:
            run = next(
                (run for run in self.runs if run["id"] == command[command.index("status") + 1]),
                None,
            )
            return (0, json.dumps(run)) if run else (1, "")
        raise AssertionError(f"unexpected query {command}")

    def run(self, argv: Sequence[str], cwd: Path, log: Path) -> int:
        command = tuple(argv)
        self.ran.append(command)
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as handle:
            handle.write(" ".join(command) + "\n")
        if "review" in command:
            mode = command[command.index("review") + 1]
            out = Path(command[command.index("--out") + 1])
            out.mkdir(parents=True, exist_ok=True)
            record = {"verdict": self.review_verdict, "engine": "deterministic"}
            with (out / f"{mode}-validation-log.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")
            return 1 if self.review_verdict == "fail" else 0
        return 1 if any(name in " ".join(command) for name in self.failing) else 0


def _context(
    tmp_path: Path,
    fakes: Fakes,
    *,
    final: bool = False,
    interactive: bool = False,
    **changes: object,
) -> refresh.Context:
    repo = tmp_path / "repo"
    (repo / ".git" / "hooks").mkdir(parents=True, exist_ok=True)
    for hook in ("pre-commit", "pre-push"):
        (repo / ".git" / "hooks" / hook).write_text("#!/bin/sh\n", encoding="utf-8")
    run_directory = repo / refresh.SCRATCH / "run"
    out = repo / refresh.EVIDENCE if final else run_directory / "evidence"
    ticks = iter(range(10_000))
    options: dict[str, object] = {
        "repo": repo,
        "out": out,
        "run_directory": run_directory,
        "final": final,
        "ci_students": ("1",),
        "deterministic_reviews": True,
        "ui_run_id": None,
        "ui_timeout": 60.0,
        "interactive": interactive,
        "run": fakes.run,
        "read": fakes.read,
        "clock": lambda: float(next(ticks)),
        "sleep": lambda _seconds: None,
        "now": lambda: STARTED,
        "port_open": lambda _port: True,
        "edge_healthy": lambda: True,
        "say": lambda _text: None,
    }
    options.update(changes)
    return refresh.Context(**options)  # type: ignore[arg-type]


def _by_step(results: Sequence[refresh.StepResult]) -> dict[str, refresh.StepResult]:
    return {result.step: result for result in results}


def test_a_dry_run_runs_every_step_in_order_into_the_scratch_folder(tmp_path: Path) -> None:
    fakes = Fakes()
    context = _context(tmp_path, fakes)

    results = refresh.refresh(context, [step for step in refresh.STEPS if step != "ui"])

    steps = [result.step for result in results]
    assert steps == ["preflight", "security", "ci", "local", "reviews", "report", "repository"]
    commands = [" ".join(command) for command in fakes.ran]
    assert f"--output-dir {context.out / 'security'}" in commands[0]
    assert "collect_ci_evidence.py --student 1" in commands[1]
    assert "capture_local_deployment.py" in commands[2]
    assert [command.split(" review ", 1)[1].split()[0] for command in commands[3:6]] == list(
        refresh.REVIEW_MODES
    )
    assert all(f"--evidence-dir {context.out}" in command for command in commands[3:6])
    assert all("--deterministic" in command for command in commands[3:6])
    by_step = _by_step(results)
    assert by_step["reviews"].status == "passed"
    assert by_step["reviews"].detail.startswith("multi-agent fail (deterministic)")
    assert by_step["repository"].status == "passed"
    summary = json.loads((context.run_directory / "summary.json").read_text(encoding="utf-8"))
    assert summary["mode"] == "dry-run"
    assert summary["passed"] is True
    assert "| reviews | passed |" in (context.run_directory / "summary.md").read_text(
        encoding="utf-8"
    )


def test_a_failing_step_is_recorded_and_the_rest_still_run(tmp_path: Path) -> None:
    fakes = Fakes()
    fakes.failing = {"capture_local_deployment.py"}

    results = _by_step(refresh.refresh(_context(tmp_path, fakes), ["security", "local", "report"]))

    assert results["local"].status == "failed"
    assert results["report"].status == "passed"


def test_stop_on_failure_ends_the_refresh_at_the_failed_step(tmp_path: Path) -> None:
    fakes = Fakes()
    fakes.failing = {"scripts.security"}

    results = refresh.refresh(
        _context(tmp_path, fakes), ["security", "local"], stop_on_failure=True
    )

    assert [result.step for result in results] == ["preflight", "security", "repository"]


@pytest.mark.parametrize(
    ("fakes", "reason"),
    [
        (Fakes(branch="release-2/x"), "not main"),
        (Fakes(origin="0" * 40), "is not origin/main"),
        (Fakes(dirty=" M scripts/x.py\n"), "uncommitted source path"),
    ],
)
def test_final_refuses_anything_but_clean_main_at_origin(
    tmp_path: Path, fakes: Fakes, reason: str
) -> None:
    with pytest.raises(refresh.PreconditionError, match=reason):
        refresh.refresh(_context(tmp_path, fakes, final=True), ["security"])
    assert fakes.ran == []


def test_final_writes_in_place_and_skips_the_dry_run_repository_check(tmp_path: Path) -> None:
    fakes = Fakes()
    context = _context(tmp_path, fakes, final=True)

    results = refresh.refresh(context, ["security"])

    assert [result.step for result in results] == ["preflight", "security"]
    assert str(context.repo / refresh.EVIDENCE / "security") in " ".join(fakes.ran[0])
    assert "Next: review" in (context.run_directory / "summary.md").read_text(encoding="utf-8")


def test_preflight_warns_about_missing_services_ci_and_hooks(tmp_path: Path) -> None:
    fakes = Fakes(dirty=" M scripts/x.py\n")
    context = _context(
        tmp_path, fakes, port_open=lambda port: port != 5013, edge_healthy=lambda: False
    )
    (context.repo / ".git" / "hooks" / "pre-push").unlink()

    result = refresh.preflight(context)

    assert result.status == "warning"
    assert "1 uncommitted path(s)" in result.detail
    assert "pre-push" in result.detail
    assert "did not answer" in result.detail
    assert "multi-agent is not listening on 5013" in result.detail
    recorded = json.loads((context.run_directory / "preflight.json").read_text(encoding="utf-8"))
    assert recorded["host_services"]["multi-agent"] is False
    assert recorded["ci"]["Student 1 CI"] == "success"


def test_the_dry_run_flags_a_repository_change(tmp_path: Path) -> None:
    fakes = Fakes()
    fakes.status_after = " M docs/release-2/evidence/security/pre-commit-report.md\n"

    results = _by_step(refresh.refresh(_context(tmp_path, fakes), ["security"]))

    assert results["repository"].status == "failed"


def test_a_review_that_writes_no_log_entry_fails_the_step(tmp_path: Path) -> None:
    fakes = Fakes()

    def broken(argv: Sequence[str], cwd: Path, log: Path) -> int:
        return 2

    result = refresh.reviews(_context(tmp_path, fakes, run=broken))

    assert result.status == "failed"
    assert "multi-agent wrote no validation log entry (exit 2)" in result.detail


def _run(identifier: str, state: str, created: datetime) -> dict[str, object]:
    return {
        "id": identifier,
        "template_id": refresh.UI_TEMPLATE,
        "state": state,
        "created_at": created.isoformat().replace("+00:00", "Z"),
    }


def test_the_ui_step_waits_for_a_new_decided_run_and_exports_it(tmp_path: Path) -> None:
    fakes = Fakes()
    fakes.runs = [
        _run("11111111-old", "approved", STARTED - timedelta(minutes=5)),
        _run("22222222-open", "awaiting_human", STARTED + timedelta(minutes=1)),
        _run("33333333-new", "corrected", STARTED + timedelta(minutes=2)),
    ]
    context = _context(tmp_path, fakes, interactive=True)

    result = refresh.ui(context)

    assert result.status == "passed", result.detail
    assert fakes.polls == 2
    export = fakes.ran[0]
    assert export[export.index("export") + 1] == "33333333-new"
    target = Path(export[export.index("--out") + 1])
    assert target == context.out / "multi-agent" / "student-1" / "33333333-ui"
    assert "run 33333333 corrected" in result.detail


def test_the_ui_step_times_out_without_a_decision(tmp_path: Path) -> None:
    fakes = Fakes()
    fakes.runs = [_run("22222222-open", "awaiting_human", STARTED + timedelta(minutes=1))]

    result = refresh.ui(_context(tmp_path, fakes, interactive=True, ui_timeout=3.0))

    assert result.status == "failed"
    assert "no decided" in result.detail
    assert fakes.ran == []


def test_the_ui_step_exports_a_named_run_without_waiting(tmp_path: Path) -> None:
    fakes = Fakes()
    fakes.runs = [_run("44444444-named", "rejected", STARTED - timedelta(days=1))]

    result = refresh.ui(_context(tmp_path, fakes, ui_run_id="44444444-named"))

    assert result.status == "passed", result.detail
    assert fakes.ran[0][fakes.ran[0].index("export") + 1] == "44444444-named"


def test_the_ui_step_is_skipped_when_nobody_can_decide(tmp_path: Path) -> None:
    result = refresh.ui(_context(tmp_path, Fakes(), interactive=False))

    assert result.status == "skipped"
    assert "--ui-run-id" in result.detail


def test_prepare_scratch_copies_the_committed_evidence(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    committed = repo / refresh.EVIDENCE / "ci" / "student-1.md"
    committed.parent.mkdir(parents=True)
    committed.write_text("ci\n", encoding="utf-8")
    out = tmp_path / "scratch" / "evidence"
    (out / "stale.txt").parent.mkdir(parents=True)
    (out / "stale.txt").write_text("old\n", encoding="utf-8")

    refresh.prepare_scratch(repo, out)

    assert (out / "ci" / "student-1.md").read_text(encoding="utf-8") == "ci\n"
    assert not (out / "stale.txt").exists()


def test_ci_students_accepts_all_or_a_list() -> None:
    assert refresh._students("all") == refresh.STUDENTS
    assert refresh._students("1,3,3") == ("1", "3")
    with pytest.raises(Exception, match="students must be"):
        refresh._students("6")


@pytest.mark.parametrize(
    "arguments",
    [
        ["--final", "--out", "x"],
        ["--out", "docs/release-2/evidence/scratch"],
    ],
)
def test_main_rejects_outputs_that_would_mix_the_modes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arguments: list[str]
) -> None:
    repo = tmp_path / "repo"
    (repo / refresh.EVIDENCE).mkdir(parents=True)
    monkeypatch.chdir(repo)
    resolved = [str(repo / value) if value.startswith("docs/") else value for value in arguments]

    assert refresh.main(["--repo", str(repo), *resolved]) == 2


def test_stream_survives_output_the_console_cannot_encode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import io
    import sys

    console = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="replace")
    monkeypatch.setattr(sys, "stdout", console)
    log = tmp_path / "step.log"
    code = refresh.stream((sys.executable, "-c", "print('quote \u2019 and \ufffd')"), tmp_path, log)

    assert code == 0
    # The child wrote UTF-8, so the quote survives the pipe instead of decoding to U+FFFD.
    assert "quote \u2019 and \ufffd" in log.read_text(encoding="utf-8")
