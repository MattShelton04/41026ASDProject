"""Record a green ``student-N.yml`` GitHub Actions run as CI evidence.

For each requested student the script asks the GitHub CLI for the latest successful run of
``.github/workflows/student-N.yml`` on a branch (``main`` by default) or for an explicit run
ID, downloads the run's ``student-N-endpoint-tests`` artifact when it exists, and writes
``docs/release-2/evidence/ci/student-N.md`` with the run URL, head SHA, branch, event,
conclusion, timestamps, every job and step result, and the endpoint-test table rendered
from the JUnit XML.

It only reads from GitHub (``gh`` must be installed and authenticated) and never triggers,
re-runs or cancels a workflow::

    uv run python scripts/collect_ci_evidence.py --student 1
    uv run python scripts/collect_ci_evidence.py --all
    uv run python scripts/collect_ci_evidence.py --student 1 --run-id 37095447883
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from shared_testkit.junit_summary import load_junit, markdown_summary

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIRECTORY = REPOSITORY_ROOT / "docs" / "release-2" / "evidence" / "ci"
STUDENTS = range(1, 6)
RUN_FIELDS = (
    "attempt,conclusion,createdAt,databaseId,displayTitle,event,headBranch,headSha,jobs,"
    "number,startedAt,status,updatedAt,url,workflowName"
)

GhRunner = Callable[[Sequence[str]], str]


class EvidenceError(RuntimeError):
    """The requested run cannot be recorded as evidence."""


def run_gh(arguments: Sequence[str]) -> str:
    """Run one read-only ``gh`` command and return its standard output."""
    try:
        completed = subprocess.run(
            ["gh", *arguments], check=True, capture_output=True, text=True, timeout=120
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
class Evidence:
    """Everything recorded for one student's run."""

    student: int
    workflow_file: str
    artifact_name: str
    run: Mapping[str, Any]
    endpoint_reports: tuple[EndpointReport, ...]
    artifact_note: str | None


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
) -> tuple[tuple[EndpointReport, ...], str | None]:
    """Download the endpoint artifact and render each JUnit file it contains."""
    name = artifact_name(student)
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
            return (), f"The `{name}` artifact could not be downloaded ({exc})."
        reports: list[EndpointReport] = []
        for path in sorted(Path(directory).rglob("*.xml")):
            try:
                report = load_junit(path)
            except ValueError as exc:
                return (), f"`{path.name}` in `{name}` is not a JUnit report ({exc})."
            reports.append(
                EndpointReport(
                    file_name=path.name,
                    markdown=markdown_summary(report, title=f"`{path.name}`"),
                    succeeded=report.succeeded,
                )
            )
    if not reports:
        return (), f"The `{name}` artifact contains no JUnit XML report."
    return tuple(reports), None


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
    reports, note = download_endpoint_reports(gh, student, resolved_run_id, repository=repository)
    return Evidence(
        student=student,
        workflow_file=workflow_file(student),
        artifact_name=artifact_name(student),
        run=run,
        endpoint_reports=reports,
        artifact_note=note,
    )


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
        f"| Status / conclusion | {_cell(run.get('status'))} / "
        f"**{_cell(run.get('conclusion'))}** |",
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
    return "\n".join(lines).rstrip("\n") + "\n"


def write_evidence(evidence: Evidence, output_directory: Path) -> Path:
    output_directory.mkdir(parents=True, exist_ok=True)
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
                "endpoint-test report; pass --allow-failed-endpoints to record it anyway",
                file=sys.stderr,
            )
            failures += 1
            continue
        path = write_evidence(evidence, arguments.output_dir)
        print(f"student-{student}: wrote {path} for {evidence.run.get('url')}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
