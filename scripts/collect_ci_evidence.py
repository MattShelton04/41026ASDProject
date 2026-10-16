"""Record a green ``student-N.yml`` GitHub Actions run as CI evidence.

For each requested student the script asks the GitHub CLI for the latest successful run of
``.github/workflows/student-N.yml`` on a branch (``main`` by default) or for an explicit run
ID, downloads the run's ``student-N-endpoint-tests`` artifact when it exists, and writes
``docs/release-2/evidence/ci/student-N.md`` with the run URL, head SHA, branch, event,
conclusion, timestamps, every job and step result, and the endpoint-test table rendered
from the JUnit XML. It also retains the raw JUnit XML and the log of the endpoint-test steps
in ``docs/release-2/evidence/ci/student-N/`` (``run.log``: bounded, ANSI-free and with
secret-shaped lines redacted), so the CI test reports and run logs outlive GitHub's artifact
and log retention.

It only reads from GitHub (``gh`` must be installed and authenticated) and never triggers,
re-runs or cancels a workflow::

    uv run python scripts/collect_ci_evidence.py --student 1
    uv run python scripts/collect_ci_evidence.py --all
    uv run python scripts/collect_ci_evidence.py --student 1 --run-id 37095447883
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.devtools.review.cloud import SECRET_PATTERNS
from shared_testkit.junit_summary import load_junit, markdown_summary

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIRECTORY = REPOSITORY_ROOT / "docs" / "release-2" / "evidence" / "ci"
STUDENTS = range(1, 6)
RUN_FIELDS = (
    "attempt,conclusion,createdAt,databaseId,displayTitle,event,headBranch,headSha,jobs,"
    "number,startedAt,status,updatedAt,url,workflowName"
)
# R2-32: each student tests two endpoint functions, so a report needs two passing tests.
MIN_PASSING_ENDPOINT_TESTS = 2
RUN_LOG_NAME = "run.log"
MAX_RUN_LOG_BYTES = 512 * 1024
ENDPOINT_STEP = re.compile(r"endpoint", re.IGNORECASE)
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
REDACTED = "[line redacted: matched a secret pattern]"

GhRunner = Callable[[Sequence[str]], str]


class EvidenceError(RuntimeError):
    """The requested run cannot be recorded as evidence."""


def run_gh(arguments: Sequence[str]) -> str:
    """Run one read-only ``gh`` command and return its standard output."""
    try:
        completed = subprocess.run(  # noqa: S603 - fixed gh argv built by this script, no shell
            ["gh", *arguments],  # noqa: S607 - gh is resolved from PATH like the other dev tools
            check=True,
            capture_output=True,
            # gh writes UTF-8; the Windows locale default (cp1252) crashes on run logs.
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except FileNotFoundError as exc:
        raise EvidenceError("the GitHub CLI (gh) is not installed or not on PATH") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip().splitlines()
        raise EvidenceError(
            f"gh {' '.join(arguments[:2])} failed: {detail[-1] if detail else exc}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise EvidenceError(f"gh {' '.join(arguments[:2])} timed out") from exc
    return completed.stdout


@dataclass(frozen=True, slots=True)
class EndpointReport:
    """One JUnit file from the run's endpoint-test artifact, rendered as Markdown."""

    file_name: str
    markdown: str
    succeeded: bool


@dataclass(frozen=True, slots=True)
class RunLog:
    """The retained log of the jobs that ran the endpoint tests."""

    text: str
    jobs: tuple[str, ...]
    scope: str
    truncated_bytes: int = 0
    redacted_lines: int = 0


@dataclass(frozen=True, slots=True)
class Evidence:
    """Everything recorded for one student's run."""

    student: int
    workflow_file: str
    artifact_name: str
    run: Mapping[str, Any]
    endpoint_reports: tuple[EndpointReport, ...]
    artifact_note: str | None
    junit_files: tuple[tuple[str, bytes], ...] = ()
    run_log: RunLog | None = None
    log_note: str | None = None


def workflow_file(student: int) -> str:
    return f".github/workflows/student-{student}.yml"


def artifact_name(student: int) -> str:
    return f"student-{student}-endpoint-tests"


def _repository_arguments(repository: str | None) -> list[str]:
    return ["--repo", repository] if repository else []


def _json(text: str, *, command: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise EvidenceError(f"gh {command} returned invalid JSON") from exc


def latest_successful_run_id(
    gh: GhRunner, student: int, *, branch: str, repository: str | None
) -> int:
    """Return the newest successful run of the student's workflow on ``branch``."""
    runs = _json(
        gh(
            [
                "run",
                "list",
                "--workflow",
                Path(workflow_file(student)).name,
                "--branch",
                branch,
                "--status",
                "success",
                "--limit",
                "1",
                "--json",
                "databaseId",
                *_repository_arguments(repository),
            ]
        ),
        command="run list",
    )
    if not isinstance(runs, list) or not runs:
        raise EvidenceError(
            f"no successful {Path(workflow_file(student)).name} run was found on {branch!r}"
        )
    return int(runs[0]["databaseId"])


def view_run(gh: GhRunner, run_id: int, *, repository: str | None) -> dict[str, Any]:
    run = _json(
        gh(
            [
                "run",
                "view",
                str(run_id),
                "--json",
                RUN_FIELDS,
                *_repository_arguments(repository),
            ]
        ),
        command="run view",
    )
    if not isinstance(run, dict):
        raise EvidenceError("gh run view did not return a JSON object")
    return run


def expected_workflow_name(student: int, root: Path) -> str:
    """Read the workflow's display name so a mismatched ``--run-id`` is refused."""
    document = yaml.safe_load((root / workflow_file(student)).read_text(encoding="utf-8"))
    name = document.get("name") if isinstance(document, dict) else None
    if not isinstance(name, str) or not name:
        raise EvidenceError(f"{workflow_file(student)} has no workflow name")
    return name


def download_endpoint_reports(
    gh: GhRunner, student: int, run_id: int, *, repository: str | None
) -> tuple[tuple[EndpointReport, ...], str | None, tuple[tuple[str, bytes], ...]]:
    """Download the endpoint artifact; render each JUnit file and keep its raw bytes."""
    name = artifact_name(student)
    raw_files: list[tuple[str, bytes]] = []
    with tempfile.TemporaryDirectory(prefix=f"ci-evidence-{student}-") as directory:
        try:
            gh(
                [
                    "run",
                    "download",
                    str(run_id),
                    "--name",
                    name,
                    "--dir",
                    directory,
                    *_repository_arguments(repository),
                ]
            )
        except EvidenceError as exc:
            return (), f"The `{name}` artifact could not be downloaded ({exc}).", ()
        reports: list[EndpointReport] = []
        for path in sorted(Path(directory).rglob("*.xml")):
            try:
                report = load_junit(path)
            except ValueError as exc:
                return (), f"`{path.name}` in `{name}` is not a JUnit report ({exc}).", ()
            flat_name = path.relative_to(directory).as_posix().replace("/", "-")
            raw_files.append((flat_name, path.read_bytes()))
            reports.append(
                EndpointReport(
                    file_name=path.name,
                    markdown=markdown_summary(
                        report, title=f"`{path.name}`", min_passed=MIN_PASSING_ENDPOINT_TESTS
                    ),
                    succeeded=report.succeeded_with(min_passed=MIN_PASSING_ENDPOINT_TESTS),
                )
            )
    if not reports:
        return (), f"The `{name}` artifact contains no JUnit XML report.", ()
    return tuple(reports), None, tuple(raw_files)


def _endpoint_jobs(run: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Jobs with an endpoint-test step, or every job when no step names endpoints."""
    jobs = [job for job in run.get("jobs") or () if isinstance(job, Mapping)]
    with_endpoints = [
        job
        for job in jobs
        if any(
            isinstance(step, Mapping) and ENDPOINT_STEP.search(str(step.get("name", "")))
            for step in job.get("steps") or ()
        )
    ]
    return with_endpoints or jobs


GROUP_RUN = re.compile(r"##\[group\]Run (?P<command>.*)")


def _endpoint_sections(lines: Sequence[str]) -> list[str]:
    """Lines of each ``##[group]Run`` step whose command mentions endpoints.

    ``gh`` names archived steps "UNKNOWN STEP", but each step still opens with a
    ``##[group]Run <command>`` line, so the endpoint-test steps can be located by command.
    """
    kept: list[str] = []
    keeping = False
    for line in lines:
        text = line.split("	", 2)[-1]
        match = GROUP_RUN.search(text)
        if match:
            keeping = bool(ENDPOINT_STEP.search(match.group("command")))
        if keeping:
            kept.append(line)
    return kept


def _step_name(line: str) -> str:
    """Return the step column of a ``gh run view --log`` line (``job<TAB>step<TAB>text``)."""
    parts = line.split("\t", 2)
    return parts[1] if len(parts) == 3 else ""


def bound_log(text: str, *, max_bytes: int = MAX_RUN_LOG_BYTES) -> tuple[str, int, int]:
    """Strip ANSI codes, redact secret-shaped lines and keep at most the final ``max_bytes``.

    Returns the text, the number of bytes dropped from the start and the number of lines
    redacted. GitHub already masks registered secrets; this also catches unregistered ones.
    """
    lines: list[str] = []
    redacted = 0
    for line in ANSI_ESCAPE.sub("", text).splitlines():
        if any(pattern.search(line) for pattern in SECRET_PATTERNS):
            parts = line.split("\t", 2)
            prefix = "\t".join(parts[:2]) + "\t" if len(parts) == 3 else ""
            lines.append(prefix + REDACTED)
            redacted += 1
        else:
            lines.append(line)
    encoded = ("\n".join(lines) + "\n").encode("utf-8") if lines else b""
    dropped = max(0, len(encoded) - max_bytes)
    if dropped:
        tail = encoded[dropped:]
        # Start at a whole line so the retained log never begins mid-line or mid-character.
        newline = tail.find(b"\n")
        if 0 <= newline < len(tail) - 1:
            dropped += newline + 1
            tail = tail[newline + 1 :]
        encoded = tail
    return encoded.decode("utf-8", errors="replace"), dropped, redacted


def download_run_log(
    gh: GhRunner, run: Mapping[str, Any], *, repository: str | None
) -> tuple[RunLog | None, str | None]:
    """Fetch the log of each job that ran endpoint tests, keeping only those steps if possible."""
    selected: list[str] = []
    endpoint_lines: list[str] = []
    all_lines: list[str] = []
    for job in _endpoint_jobs(run):
        job_id = job.get("databaseId")
        if job_id is None:
            continue
        try:
            text = gh(
                ["run", "view", "--job", str(job_id), "--log", *_repository_arguments(repository)]
            )
        except EvidenceError as exc:
            return None, f"The log of job `{job.get('name')}` could not be downloaded ({exc})."
        selected.append(str(job.get("name") or job_id))
        lines = text.splitlines()
        all_lines.extend(lines)
        endpoint_lines.extend(line for line in lines if ENDPOINT_STEP.search(_step_name(line)))
    if not selected:
        return None, "The run lists no jobs with an ID, so no run log was retained."
    by_command = [] if endpoint_lines else _endpoint_sections(all_lines)
    if endpoint_lines:
        kept, scope = endpoint_lines, "Endpoint-test steps"
    elif by_command:
        kept, scope = by_command, "Endpoint-test steps, matched by run command,"
    else:
        # gh labels some archived steps "UNKNOWN STEP"; keep the whole job log instead.
        kept, scope = all_lines, "Complete job log (step names unavailable)"
    if not kept:
        return None, "The run log is empty, so no run log was retained."
    text, dropped, redacted = bound_log("\n".join(kept))
    return RunLog(text, tuple(selected), scope, dropped, redacted), None


def collect(
    gh: GhRunner,
    student: int,
    *,
    branch: str,
    run_id: int | None = None,
    repository: str | None = None,
    root: Path = REPOSITORY_ROOT,
) -> Evidence:
    """Gather run metadata and endpoint results for one student."""
    resolved_run_id = run_id or latest_successful_run_id(
        gh, student, branch=branch, repository=repository
    )
    run = view_run(gh, resolved_run_id, repository=repository)
    expected = expected_workflow_name(student, root)
    if run.get("workflowName") != expected:
        raise EvidenceError(
            f"run {resolved_run_id} belongs to {run.get('workflowName')!r}, not {expected!r}"
        )
    reports, note, raw_files = download_endpoint_reports(
        gh, student, resolved_run_id, repository=repository
    )
    run_log, log_note = download_run_log(gh, run, repository=repository)
    return Evidence(
        student=student,
        workflow_file=workflow_file(student),
        artifact_name=artifact_name(student),
        run=run,
        endpoint_reports=reports,
        artifact_note=note,
        junit_files=raw_files,
        run_log=run_log,
        log_note=log_note,
    )


def evidence_directory(student: int) -> str:
    """Directory, relative to the CI evidence root, for the retained raw files."""
    return f"student-{student}"


def _cell(value: object) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ").strip() or "-"


def render(evidence: Evidence) -> str:
    """Render deterministic Markdown from the recorded evidence only."""
    run = evidence.run
    head_sha = str(run.get("headSha", ""))
    lines = [
        f"# Student {evidence.student} CI evidence",
        "",
        "Generated by `scripts/collect_ci_evidence.py` from `gh run view` metadata and the "
        f"run's `{evidence.artifact_name}` artifact. Re-run the script instead of editing "
        "this file.",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Workflow | {_cell(run.get('workflowName'))} (`{evidence.workflow_file}`) |",
        f"| Run | [#{_cell(run.get('number'))} (ID {_cell(run.get('databaseId'))}, "
        f"attempt {_cell(run.get('attempt'))})]({run.get('url', '')}) |",
        # One field per row: `ai review testing` reads the `| Conclusion | ... |` row.
        f"| Status | {_cell(run.get('status'))} |",
        f"| Conclusion | **{_cell(run.get('conclusion'))}** |",
        f"| Event | {_cell(run.get('event'))} |",
        f"| Branch | {_cell(run.get('headBranch'))} |",
        f"| Head SHA | `{_cell(head_sha)}` |",
        f"| Commit title | {_cell(run.get('displayTitle'))} |",
        f"| Created | {_cell(run.get('createdAt'))} |",
        f"| Started | {_cell(run.get('startedAt'))} |",
        f"| Updated | {_cell(run.get('updatedAt'))} |",
        "",
        "## Jobs",
        "",
        "| Job | Conclusion | Started | Completed |",
        "|---|---|---|---|",
    ]
    jobs = [job for job in run.get("jobs") or () if isinstance(job, Mapping)]
    for job in jobs:
        lines.append(
            f"| [{_cell(job.get('name'))}]({job.get('url', '')}) | "
            f"{_cell(job.get('conclusion'))} | {_cell(job.get('startedAt'))} | "
            f"{_cell(job.get('completedAt'))} |"
        )
    for job in jobs:
        lines.extend(
            [
                "",
                f"### Steps: {_cell(job.get('name'))}",
                "",
                "| # | Step | Conclusion |",
                "|---:|---|---|",
            ]
        )
        for step in job.get("steps") or ():
            lines.append(
                f"| {_cell(step.get('number'))} | {_cell(step.get('name'))} | "
                f"{_cell(step.get('conclusion'))} |"
            )
    lines.extend(["", "## Endpoint tests", ""])
    if evidence.artifact_note:
        lines.append(evidence.artifact_note)
    for report in evidence.endpoint_reports:
        lines.append(report.markdown.rstrip("\n"))
        lines.append("")
    directory = evidence_directory(evidence.student)
    lines.extend(["", "## Retained test reports and run log", ""])
    if evidence.junit_files:
        lines.extend(
            f"- JUnit XML: [`{directory}/{name}`]({directory}/{name})"
            for name, _ in evidence.junit_files
        )
    if evidence.run_log is not None:
        log = evidence.run_log
        detail = [f"{log.scope} of {', '.join(f'`{_cell(job)}`' for job in log.jobs)}"]
        if log.truncated_bytes:
            detail.append(f"first {log.truncated_bytes} bytes omitted")
        if log.redacted_lines:
            detail.append(f"{log.redacted_lines} secret-shaped line(s) redacted")
        lines.append(
            f"- Run log: [`{directory}/{RUN_LOG_NAME}`]({directory}/{RUN_LOG_NAME}) "
            f"({'; '.join(detail)})"
        )
    else:
        lines.append(f"- Run log: not retained. {evidence.log_note or ''}".rstrip())
    return "\n".join(lines).rstrip("\n") + "\n"


def write_evidence(evidence: Evidence, output_directory: Path) -> Path:
    """Write ``student-N.md`` and replace the retained JUnit XML and run log beside it."""
    output_directory.mkdir(parents=True, exist_ok=True)
    raw_directory = output_directory / evidence_directory(evidence.student)
    if raw_directory.is_dir():
        # Remove only files this script writes, so a previous run's reports cannot linger.
        for stale in (*raw_directory.glob("*.xml"), raw_directory / RUN_LOG_NAME):
            if stale.is_file():
                stale.unlink()
    if evidence.junit_files or evidence.run_log is not None:
        raw_directory.mkdir(parents=True, exist_ok=True)
    for name, content in evidence.junit_files:
        (raw_directory / name).write_bytes(content)
    if evidence.run_log is not None:
        (raw_directory / RUN_LOG_NAME).write_bytes(evidence.run_log.text.encode("utf-8"))
    path = output_directory / f"student-{evidence.student}.md"
    path.write_text(render(evidence), encoding="utf-8")
    return path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record a successful student-N.yml run as docs/release-2/evidence/ci."
    )
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--student", type=int, choices=STUDENTS, action="append", help="student number"
    )
    selection.add_argument("--all", action="store_true", help="every student workflow")
    parser.add_argument("--run-id", type=int, help="record this run instead of the latest")
    parser.add_argument("--branch", default="main", help="branch to search (default: main)")
    parser.add_argument("--repo", help="OWNER/REPO when not run inside the repository")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIRECTORY,
        help="directory for student-N.md (default: docs/release-2/evidence/ci)",
    )
    parser.add_argument(
        "--allow-failed-endpoints",
        action="store_true",
        help="write evidence even when the endpoint artifact is missing or not all green",
    )
    return parser


def main(argv: Sequence[str] | None = None, *, gh: GhRunner = run_gh) -> int:
    arguments = _parser().parse_args(argv)
    students: list[int] = list(STUDENTS) if arguments.all else sorted(set(arguments.student))
    if arguments.run_id is not None and len(students) != 1:
        print("error: --run-id needs exactly one --student", file=sys.stderr)
        return 2
    failures = 0
    for student in students:
        try:
            evidence = collect(
                gh,
                student,
                branch=arguments.branch,
                run_id=arguments.run_id,
                repository=arguments.repo,
            )
        except EvidenceError as exc:
            print(f"student-{student}: error: {exc}", file=sys.stderr)
            failures += 1
            continue
        endpoint_green = bool(evidence.endpoint_reports) and all(
            report.succeeded for report in evidence.endpoint_reports
        )
        if not endpoint_green and not arguments.allow_failed_endpoints:
            print(
                f"student-{student}: error: run {evidence.run.get('url')} has no fully passing "
                f"endpoint-test report (at least {MIN_PASSING_ENDPOINT_TESTS} passing tests, "
                "none failed); pass --allow-failed-endpoints to record it anyway",
                file=sys.stderr,
            )
            failures += 1
            continue
        path = write_evidence(evidence, arguments.output_dir)
        print(f"student-{student}: wrote {path} for {evidence.run.get('url')}")
        if evidence.run_log is None:
            print(f"student-{student}: warning: {evidence.log_note}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
