"""Refresh every Release 2 evidence file in one ordered, logged pass.

One command replaces the hand-run sequence in ``docs/release-2/README.md`` ("Evidence refresh at
the freeze"). Each step runs an existing tool, in this order:

1. ``preflight``  the commit, source tree, Git hooks, stack edge, host AI ports and CI state
2. ``security``   ``python -m scripts.security report``           -> ``security/``
3. ``ci``         ``scripts/collect_ci_evidence.py --student N``    -> ``ci/``
4. ``local``      ``scripts/capture_local_deployment.py``           -> ``local/``
5. ``ui``         waits for a Feature 1 Readiness review that a person decides in the UI, then
                  ``multi-agent-server export``                     -> ``multi-agent/student-1/``
6. ``reviews``    ``dev.py ai review multi-agent|testing|cloud``    -> ``reviews/``
7. ``report``     ``scripts/build_release2_report.py --status``

Two modes:

* **Dry run (default).** The committed evidence is copied to a scratch folder under the gitignored
  ``.propertyscope-runtime/evidence-refresh/`` and every step writes there, so the reviews read the
  fresh evidence beside everything else and nothing in the repository changes.
* **``--final``.** Steps write into ``docs/release-2/evidence/`` in place. The command refuses to
  start unless the checkout is ``main`` at ``origin/main`` with a clean source tree. The capture
  tools ignore ``docs/release-2/evidence`` when they check for uncommitted changes, so the earlier
  steps' output never marks the later captures as dirty. Commit the result afterwards.

Every step continues after a failure unless ``--stop-on-failure`` is given; the summary
(``summary.md`` / ``summary.json`` plus one log per step) records what passed. The exit code is 1
when any step failed and 2 when ``--final`` preconditions are not met.

The command may run from another checkout with ``--repo``: every step runs in that checkout, which
must be the one whose stack and host AI services are running (their tokens live in its
``.propertyscope-runtime/``).

Usage::

    uv run python scripts/refresh_release2_evidence.py                 # dry run
    uv run python scripts/refresh_release2_evidence.py --final --ci-students all
    uv run python scripts/refresh_release2_evidence.py --only reviews --deterministic-reviews
"""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = Path("docs/release-2/evidence")
SCRATCH = Path(".propertyscope-runtime/evidence-refresh")
EVIDENCE_PATHSPEC = ":(exclude)docs/release-2/evidence"
STEPS = ("preflight", "security", "ci", "local", "ui", "reviews", "report")
REVIEW_MODES = ("multi-agent", "testing", "cloud")
STUDENTS = ("1", "2", "3", "4", "5")
UI_TEMPLATE = "f1-release-readiness-review"
UI_STUDENT_DIRECTORY = Path("multi-agent/student-1")
DECIDED_STATES = frozenset({"approved", "corrected", "partially_accepted", "rejected"})
UNDECIDED_STATES = frozenset({"planning", "working", "reviewing", "awaiting_human"})
HOST_PORTS = {"ai-mode": 5005, "mcp": 5011, "rag": 5012, "multi-agent": 5013}
EDGE_HEALTH = "http://127.0.0.1:5100/healthz"
CI_WORKFLOWS = ("Integration CI", *(f"Student {number} CI" for number in STUDENTS))
UV = ("uv", "run", "--locked")
MULTI_AGENT = (*UV, "multi-agent-server")

# argv, working directory, log file -> exit code. Output is streamed and also written to the log.
StepRunner = Callable[[Sequence[str], Path, Path], int]
# argv, working directory -> (exit code, stdout).
Reader = Callable[[Sequence[str], Path], tuple[int, str]]


@dataclass
class StepResult:
    """Outcome of one refresh step, as it appears in the summary."""

    step: str
    status: str  # passed | failed | warning | skipped
    detail: str
    seconds: float = 0.0
    commands: list[str] = field(default_factory=list)
    log: str | None = None


@dataclass
class Context:
    """Everything a step needs; tests replace the runner, reader, clock and probes."""

    repo: Path
    out: Path
    run_directory: Path
    final: bool
    ci_students: tuple[str, ...]
    deterministic_reviews: bool
    ui_run_id: str | None
    ui_timeout: float
    interactive: bool
    run: StepRunner
    read: Reader
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    now: Callable[[], datetime] = lambda: datetime.now(UTC)
    port_open: Callable[[int], bool] = lambda port: _port_open(port)
    edge_healthy: Callable[[], bool] = lambda: _edge_healthy()
    poll_seconds: float = 5.0
    say: Callable[[str], None] = print

    def log(self, step: str) -> Path:
        return self.run_directory / "logs" / f"{step}.log"


class PreconditionError(RuntimeError):
    """``--final`` refused to start; nothing was written."""


# --- process helpers ----------------------------------------------------------------------------


def stream(argv: Sequence[str], cwd: Path, log: Path) -> int:
    """Run ``argv`` in ``cwd``, echoing its output and appending it to ``log``."""
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as handle:
        handle.write(f"$ {' '.join(argv)}\n")
        handle.flush()
        try:
            process = subprocess.Popen(  # noqa: S603 - fixed argv built by this script
                list(argv),
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            handle.write(f"cannot start: {exc}\n")
            return 127
        assert process.stdout is not None  # noqa: S101 - set by stdout=PIPE
        for line in process.stdout:
            sys.stdout.write(line)
            handle.write(line)
        code = process.wait()
        handle.write(f"[exit {code}]\n\n")
        return code


def read(argv: Sequence[str], cwd: Path) -> tuple[int, str]:
    """Run a short query command and return its exit code and stdout."""
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv built by this script
            list(argv),
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 127, ""
    return completed.returncode, completed.stdout


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.0):
            return True
    except OSError:
        return False


def _edge_healthy() -> bool:
    try:
        with urllib.request.urlopen(EDGE_HEALTH, timeout=3.0) as response:
            return bool(200 <= response.status < 300)
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _git(context: Context, *arguments: str) -> str:
    code, output = context.read(("git", *arguments), context.repo)
    return output.strip() if code == 0 else ""


# --- steps --------------------------------------------------------------------------------------


def preflight(context: Context) -> StepResult:
    """Record the commit and environment; under ``--final`` refuse anything but clean main."""
    if context.final:
        context.read(("git", "fetch", "--quiet", "origin", "main"), context.repo)
    branch = _git(context, "branch", "--show-current") or "detached"
    head = _git(context, "rev-parse", "HEAD") or "unknown"
    upstream = _git(context, "rev-parse", "origin/main") or "unknown"
    changed = [
        line
        for line in _git(
            context, "status", "--porcelain", "--", ".", EVIDENCE_PATHSPEC
        ).splitlines()
        if line.strip()
    ]
    hooks = [
        hook
        for hook in ("pre-commit", "pre-push")
        if not (
            context.repo / (_git(context, "rev-parse", "--git-path", f"hooks/{hook}") or "-")
        ).is_file()
    ]
    problems: list[str] = []
    if context.final:
        if branch != "main":
            problems.append(f"the checkout is on {branch}, not main")
        if head != upstream:
            problems.append(f"HEAD {head[:12]} is not origin/main {upstream[:12]}")
        if changed:
            problems.append(
                f"{len(changed)} uncommitted source path(s) outside {EVIDENCE.as_posix()}"
            )
    if problems:
        raise PreconditionError("; ".join(problems))
    edge = context.edge_healthy()
    ports = {service: context.port_open(port) for service, port in HOST_PORTS.items()}
    code, runs = context.read(
        ("gh", "run", "list", "--commit", head, "--json", "workflowName,status,conclusion"),
        context.repo,
    )
    ci = _ci_state(runs) if code == 0 else {}
    warnings = [
        *([f"source tree has {len(changed)} uncommitted path(s)"] if changed else []),
        *([f"Git hook(s) not installed: {', '.join(hooks)}"] if hooks else []),
        *([] if edge else [f"the stack edge did not answer {EDGE_HEALTH}"]),
        *(
            f"{service} is not listening on {HOST_PORTS[service]}"
            for service, up in ports.items()
            if not up
        ),
        *(f"{name} is {state} for {head[:12]}" for name, state in ci.items() if state != "success"),
        *([] if code == 0 else ["could not read CI runs with gh"]),
    ]
    facts = f"{branch} at {head[:12]} (origin/main {upstream[:12]})"
    summary = {
        "branch": branch,
        "head": head,
        "origin_main": upstream,
        "uncommitted_source_paths": len(changed),
        "missing_hooks": hooks,
        "edge_healthy": edge,
        "host_services": ports,
        "ci": ci,
    }
    path = context.run_directory / "preflight.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    if warnings:
        return StepResult("preflight", "warning", f"{facts}; " + "; ".join(warnings))
    return StepResult("preflight", "passed", facts)


def _ci_state(output: str) -> dict[str, str]:
    try:
        runs = json.loads(output or "[]")
    except json.JSONDecodeError:
        return {}
    state: dict[str, str] = {}
    for run in runs if isinstance(runs, list) else []:
        name = run.get("workflowName") if isinstance(run, dict) else None
        if name in CI_WORKFLOWS and name not in state:
            status = str(run.get("status") or "")
            state[name] = str(run.get("conclusion") or status) if status == "completed" else status
    return {name: state.get(name, "not run") for name in CI_WORKFLOWS}


def _commands(context: Context, step: str, commands: Sequence[Sequence[str]]) -> StepResult:
    log = context.log(step)
    shown = [" ".join(argv) for argv in commands]
    failed = [
        text
        for argv, text in zip(commands, shown, strict=True)
        if context.run(argv, context.repo, log)
    ]
    if failed:
        return StepResult(step, "failed", f"failed: {'; '.join(failed)}", commands=shown)
    return StepResult(step, "passed", f"{len(commands)} command(s) succeeded", commands=shown)


def security(context: Context) -> StepResult:
    out = context.out / "security"
    return _commands(
        context,
        "security",
        [(*UV, "python", "-m", "scripts.security", "report", "--output-dir", str(out))],
    )


def ci(context: Context) -> StepResult:
    out = context.out / "ci"
    commands = [
        (
            *UV,
            "python",
            "scripts/collect_ci_evidence.py",
            "--student",
            student,
            "--output-dir",
            str(out),
        )
        for student in context.ci_students
    ]
    return _commands(context, "ci", commands)


def local(context: Context) -> StepResult:
    out = context.out / "local"
    return _commands(
        context,
        "local",
        [(*UV, "python", "scripts/capture_local_deployment.py", "--output-dir", str(out))],
    )


def ui(context: Context) -> StepResult:
    """Wait for a person to decide a Feature 1 Readiness review in the UI, then export it."""
    run_id = context.ui_run_id
    if run_id is None and not context.interactive:
        return StepResult(
            "ui",
            "skipped",
            "manual step: decide a Readiness review in the UI, then rerun with "
            "--only ui --ui-run-id RUN_ID",
        )
    started = context.now()
    deadline = context.clock() + context.ui_timeout
    if run_id is None:
        context.say(
            "\n[ui] Open Feature 1 (http://localhost:5200), pick a candidate release, start "
            "Readiness review, follow Planner -> Worker -> Reviewer, and record your decision.\n"
            f"[ui] Waiting up to {int(context.ui_timeout)} s for a run started after "
            f"{started:%H:%M:%S} UTC to be decided ..."
        )
    run: dict[str, Any] | None = None
    while run is None:
        run = _decided_run(context, run_id, started)
        if run is not None:
            break
        if context.clock() >= deadline:
            return StepResult(
                "ui",
                "failed",
                f"no decided {UI_TEMPLATE} run "
                + (f"with id {run_id}" if run_id else f"started after {started:%H:%M:%S} UTC")
                + f" within {int(context.ui_timeout)} s",
            )
        context.sleep(context.poll_seconds)
    identifier = str(run["id"])
    target = context.out / UI_STUDENT_DIRECTORY / f"{identifier[:8]}-ui"
    if target.exists():
        shutil.rmtree(target)
    result = _commands(
        context, "ui", [(*MULTI_AGENT, "export", identifier, "--out", str(target), "--server")]
    )
    if result.status == "passed":
        result.detail = f"run {identifier[:8]} {run.get('state')} -> {_shown(context, target)}"
    return result


def _decided_run(context: Context, run_id: str | None, started: datetime) -> dict[str, Any] | None:
    if run_id is not None:
        code, output = context.read(
            (*MULTI_AGENT, "status", run_id, "--server", "--json"), context.repo
        )
        runs = [_json(output)] if code == 0 else []
    else:
        code, output = context.read(
            (
                *MULTI_AGENT,
                "list",
                "--server",
                "--template",
                UI_TEMPLATE,
                "--limit",
                "10",
                "--json",
            ),
            context.repo,
        )
        listed = _json(output)
        items = listed.get("items", listed.get("runs", [])) if isinstance(listed, dict) else listed
        runs = [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
    for candidate in runs:
        run = candidate.get("run", candidate) if isinstance(candidate, dict) else {}
        if not isinstance(run, dict) or run.get("state") not in DECIDED_STATES or not run.get("id"):
            continue
        if run_id is None and not _after(run.get("created_at"), started):
            continue
        if run_id is not None or run.get("template_id", UI_TEMPLATE) == UI_TEMPLATE:
            return run
    return None


def _after(value: object, started: datetime) -> bool:
    if not isinstance(value, str):
        return False
    try:
        created = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return (created if created.tzinfo else created.replace(tzinfo=UTC)) >= started


def _json(text: str) -> Any:
    try:
        return json.loads(text or "null")
    except json.JSONDecodeError:
        return None


def reviews(context: Context) -> StepResult:
    """Run the three review modes over the refreshed evidence; a fail verdict is not an error."""
    log = context.log("reviews")
    out = context.out / "reviews"
    verdicts: list[str] = []
    shown: list[str] = []
    errors: list[str] = []
    for mode in REVIEW_MODES:
        argv = (
            *UV,
            "scripts/dev.py",
            "ai",
            "review",
            mode,
            "--evidence-dir",
            str(context.out),
            "--out",
            str(out),
            *(["--deterministic"] if context.deterministic_reviews else []),
        )
        shown.append(" ".join(argv))
        before = _log_lines(out / f"{mode}-validation-log.jsonl")
        code = context.run(argv, context.repo, log)
        lines = _log_lines(out / f"{mode}-validation-log.jsonl")
        if len(lines) <= len(before):
            errors.append(f"{mode} wrote no validation log entry (exit {code})")
            continue
        record = _json(lines[-1])
        verdict = record.get("verdict", "?") if isinstance(record, dict) else "?"
        engine = record.get("engine", "?") if isinstance(record, dict) else "?"
        verdicts.append(f"{mode} {verdict} ({engine})")
    if errors:
        return StepResult("reviews", "failed", "; ".join([*errors, *verdicts]), commands=shown)
    return StepResult("reviews", "passed", "; ".join(verdicts), commands=shown)


def _log_lines(path: Path) -> list[str]:
    try:
        return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError:
        return []


def report(context: Context) -> StepResult:
    result = _commands(
        context, "report", [(*UV, "python", "scripts/build_release2_report.py", "--status")]
    )
    if not context.final:
        result.detail += " (reads the committed docs/release-2/evidence, not the dry-run copy)"
    return result


STEP_FUNCTIONS: dict[str, Callable[[Context], StepResult]] = {
    "preflight": preflight,
    "security": security,
    "ci": ci,
    "local": local,
    "ui": ui,
    "reviews": reviews,
    "report": report,
}


# --- orchestration ------------------------------------------------------------------------------


def _shown(context: Context, path: Path) -> str:
    try:
        return path.resolve().relative_to(context.repo.resolve()).as_posix()
    except ValueError:
        return str(path)


def prepare_scratch(repo: Path, out: Path) -> None:
    """Copy the committed evidence so the dry-run reviews see a complete evidence tree."""
    source = repo / EVIDENCE
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(source, out)


def refresh(
    context: Context, steps: Sequence[str], *, stop_on_failure: bool = False
) -> list[StepResult]:
    """Run ``steps`` in order and write the summary; ``preflight`` always runs first."""
    results: list[StepResult] = []
    before = _git(context, "status", "--porcelain")
    for step in ("preflight", *(name for name in steps if name != "preflight")):
        context.say(f"\n== {step}")
        started = context.clock()
        result = STEP_FUNCTIONS[step](context)
        result.seconds = round(context.clock() - started, 1)
        log = context.log(step)
        result.log = _shown(context, log) if log.exists() else None
        results.append(result)
        context.say(f"== {step}: {result.status} - {result.detail}")
        if stop_on_failure and result.status == "failed":
            break
    if not context.final:
        after = _git(context, "status", "--porcelain")
        unchanged = after == before
        results.append(
            StepResult(
                "repository",
                "passed" if unchanged else "failed",
                "the dry run changed nothing in the repository"
                if unchanged
                else "the repository's git status changed during the dry run",
            )
        )
    write_summary(context, results)
    return results


def write_summary(context: Context, results: Sequence[StepResult]) -> None:
    context.run_directory.mkdir(parents=True, exist_ok=True)
    document = {
        "schema_version": "1.0",
        "mode": "final" if context.final else "dry-run",
        "repo": str(context.repo),
        "evidence_output": _shown(context, context.out),
        "finished_at": context.now().isoformat(timespec="seconds"),
        "passed": all(result.status != "failed" for result in results),
        "steps": [asdict(result) for result in results],
    }
    (context.run_directory / "summary.json").write_text(
        json.dumps(document, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# Release 2 evidence refresh",
        "",
        f"- **Mode:** {document['mode']}",
        f"- **Evidence written to:** `{document['evidence_output']}`",
        f"- **Finished:** {document['finished_at']}",
        "",
        "| Step | Status | Seconds | Detail |",
        "|---|---|---:|---|",
        *(
            f"| {r.step} | {r.status} | {r.seconds:g} | {r.detail.replace('|', '/')} |"
            for r in results
        ),
        "",
    ]
    if context.final:
        lines += [
            "Next: review `git diff --stat docs/release-2/evidence`, then commit the refreshed "
            "evidence and rebuild the report with "
            "`uv run python scripts/build_release2_report.py`.",
            "",
        ]
    (context.run_directory / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def _students(value: str) -> tuple[str, ...]:
    if value == "all":
        return STUDENTS
    chosen = tuple(dict.fromkeys(part.strip() for part in value.split(",") if part.strip()))
    unknown = [student for student in chosen if student not in STUDENTS]
    if unknown or not chosen:
        raise argparse.ArgumentTypeError(f"students must be 1-5, a comma list or 'all': {value!r}")
    return chosen


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--final", action="store_true", help="write into docs/release-2/evidence")
    parser.add_argument(
        "--out", type=Path, help="dry-run evidence folder (default: a new scratch folder)"
    )
    parser.add_argument(
        "--repo", type=Path, default=REPOSITORY_ROOT, help="checkout to run every step in"
    )
    parser.add_argument(
        "--only", nargs="+", choices=STEPS, help="run only these steps (plus preflight)"
    )
    parser.add_argument("--skip", nargs="+", choices=STEPS, default=[], help="skip these steps")
    parser.add_argument(
        "--ci-students",
        type=_students,
        default=("1",),
        help="1-5, a comma list, or 'all' (default: 1)",
    )
    parser.add_argument("--ui-run-id", help="export this already-decided run instead of waiting")
    parser.add_argument(
        "--ui-timeout", type=float, default=1800.0, help="seconds to wait (default 1800)"
    )
    parser.add_argument("--no-ui", action="store_true", help="skip the manual UI step")
    parser.add_argument(
        "--deterministic-reviews", action="store_true", help="review without model calls"
    )
    parser.add_argument("--stop-on-failure", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    repo = arguments.repo.resolve()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_directory = repo / SCRATCH / f"{'final' if arguments.final else 'dry-run'}-{stamp}"
    if arguments.final:
        if arguments.out is not None:
            print("error: --final writes docs/release-2/evidence; drop --out", file=sys.stderr)
            return 2
        out = repo / EVIDENCE
    else:
        out = (arguments.out or run_directory / "evidence").resolve()
        if (repo / EVIDENCE).resolve() in (out, *out.parents):
            print("error: a dry run must not write inside docs/release-2/evidence", file=sys.stderr)
            return 2
    steps = [step for step in (arguments.only or STEPS) if step not in arguments.skip]
    if arguments.no_ui:
        steps = [step for step in steps if step != "ui"]
    context = Context(
        repo=repo,
        out=out,
        run_directory=run_directory,
        final=arguments.final,
        ci_students=arguments.ci_students,
        deterministic_reviews=arguments.deterministic_reviews,
        ui_run_id=arguments.ui_run_id,
        ui_timeout=arguments.ui_timeout,
        interactive=sys.stdin.isatty(),
        run=stream,
        read=read,
    )
    try:
        if not arguments.final:
            prepare_scratch(repo, out)
        results = refresh(context, steps, stop_on_failure=arguments.stop_on_failure)
    except PreconditionError as exc:
        print(f"error: --final refused: {exc}", file=sys.stderr)
        return 2
    print(f"\nSummary: {_shown(context, run_directory / 'summary.md')}")
    return 0 if all(result.status != "failed" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
