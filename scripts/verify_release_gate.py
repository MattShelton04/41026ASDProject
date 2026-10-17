"""Verify the CI gate for a cloud deployment: every required workflow is green (R2-43).

``cloud-deployment.yml`` runs this first, for the commit it is about to deploy. The brief's flow
is pre-commit -> GitHub Actions -> post-commit endpoint tests (``student-N.yml``) -> Docker
build/validation -> ``cloud-deployment.yml`` -> Azure, so a deployment needs:

- **Integration CI** (``integration-ci.yml``) concluded ``success`` for exactly this commit. It runs
  on every push to ``main`` and is the run that triggers the deployment.
- **Student 1..5 CI** (``student-N.yml``). These are path-filtered, so a commit that does not touch
  a feature's inputs has no run of its own. For each, the gate takes the most recently created
  push or manual run on ``main`` whose head commit **is the deploy commit or one of its
  ancestors** (GitHub's compare API: ``identical`` or ``ahead``). That run must have completed
  with ``success``. Any other conclusion (including ``cancelled``) fails the gate; a re-run that
  succeeds clears it.

A run that is still queued or in progress is *pending*: with ``--wait-minutes`` the gate polls
until it completes or the time runs out (then it fails). The result names the run, commit and
relation that satisfied each workflow, and is written as ``release-gate.json`` and
``release-gate.md`` (a GitHub step summary table) for the deployment report and the Cloud
Deployment Report Review.

It only reads from GitHub through ``gh api`` (``GH_TOKEN`` with ``actions: read`` and
``contents: read``) and never triggers, re-runs or cancels anything::

    uv run python scripts/verify_release_gate.py --repo MattShelton04/41026ASDProject \\
        --sha <40-hex commit> --output-dir .propertyscope-runtime/cloud/gate

Exit status: 0 when the gate passed, 1 when it failed, 2 for invalid arguments or a GitHub error.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIRECTORY = REPOSITORY_ROOT / ".propertyscope-runtime" / "cloud" / "gate"
GATE_JSON = "release-gate.json"
GATE_MARKDOWN = "release-gate.md"
SCHEMA_VERSION = 1
COMMIT_SHA = re.compile(r"[0-9a-f]{40}")
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
BRANCH = re.compile(r"[A-Za-z0-9._/-]{1,200}")
# Events whose runs describe the branch itself (pull-request runs test a merge ref instead).
GATE_EVENTS = frozenset({"push", "workflow_dispatch"})
ANCESTOR_STATUSES = frozenset({"identical", "ahead"})
RUNS_PER_PAGE = 50
MAX_COMPARISONS = 25
RULE = (
    "Integration CI must have succeeded for the deploy commit itself. Each Student N CI "
    "workflow is path-filtered, so its most recently created push or manual run on the branch "
    "whose head is the deploy commit or an ancestor of it must have completed with success. "
    "Queued or running runs are waited for; any other conclusion fails the gate."
)


@dataclass(frozen=True, slots=True)
class WorkflowRule:
    """One workflow the gate requires, by display name and file."""

    name: str
    file: str
    exact: bool


REQUIRED_WORKFLOWS: tuple[WorkflowRule, ...] = (
    WorkflowRule("Integration CI", "integration-ci.yml", exact=True),
    *(WorkflowRule(f"Student {n} CI", f"student-{n}.yml", exact=False) for n in range(1, 6)),
)
REQUIRED_WORKFLOW_NAMES = tuple(rule.name for rule in REQUIRED_WORKFLOWS)

GhApi = Callable[[str, str | None], Any]


class GateError(RuntimeError):
    """GitHub could not be asked (not a failed gate)."""


def gh_api(path: str, jq: str | None = None) -> Any:
    """Call ``gh api`` read-only and parse its JSON output."""
    arguments = ["gh", "api", path, *(("--jq", jq) if jq else ())]
    try:
        completed = subprocess.run(  # noqa: S603 - fixed gh argv built by this script, no shell
            arguments,
            check=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except FileNotFoundError as exc:
        raise GateError("the GitHub CLI (gh) is not installed or not on PATH") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip().splitlines()
        raise GateError(f"gh api {path} failed: {detail[-1] if detail else exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise GateError(f"gh api {path} timed out") from exc
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise GateError(f"gh api {path} returned invalid JSON") from exc


@dataclass(slots=True)
class WorkflowVerdict:
    """The run that decided one required workflow, and why."""

    workflow: str
    file: str
    rule: str
    state: str  # success | failure | pending | missing
    passed: bool
    detail: str
    run_id: int | None = None
    run_number: int | None = None
    run_attempt: int | None = None
    run_url: str | None = None
    head_sha: str | None = None
    event: str | None = None
    status: str | None = None
    conclusion: str | None = None
    created_at: str | None = None
    relation: str | None = None  # identical | ancestor
    commits_behind: int | None = None


@dataclass(slots=True)
class Gate:
    """Evaluates the required workflows for one deploy commit."""

    api: GhApi
    repository: str
    sha: str
    branch: str = "main"
    _relations: dict[str, tuple[str, int | None]] = field(default_factory=dict)

    def relation(self, head: str) -> tuple[str, int | None]:
        """How ``head`` relates to the deploy commit: identical, ancestor or unrelated."""
        if head == self.sha:
            return "identical", 0
        if head not in self._relations:
            try:
                value = self.api(
                    f"repos/{self.repository}/compare/{head}...{self.sha}",
                    "{status: .status, ahead_by: .ahead_by}",
                )
            except GateError:
                # An unknown or force-pushed commit cannot vouch for the deploy commit.
                value = {}
            status = value.get("status") if isinstance(value, dict) else None
            ahead = value.get("ahead_by") if isinstance(value, dict) else None
            self._relations[head] = (
                "ancestor" if status in ANCESTOR_STATUSES else str(status or "unrelated"),
                ahead if isinstance(ahead, int) else None,
            )
        return self._relations[head]

    def runs(self, rule: WorkflowRule) -> list[dict[str, Any]]:
        path = (
            f"repos/{self.repository}/actions/workflows/{rule.file}/runs"
            f"?branch={quote(self.branch, safe='')}&per_page={RUNS_PER_PAGE}"
            "&exclude_pull_requests=true"
        )
        value = self.api(
            path,
            ".workflow_runs | map({id, run_number, run_attempt, head_sha, event, status, "
            "conclusion, html_url, created_at})",
        )
        if not isinstance(value, list):
            raise GateError(f"unexpected workflow run listing for {rule.file}")
        runs = [run for run in value if isinstance(run, dict) and run.get("event") in GATE_EVENTS]
        # Newest first, whatever order the API used.
        return sorted(runs, key=lambda run: str(run.get("created_at", "")), reverse=True)

    def evaluate(self, rule: WorkflowRule) -> WorkflowVerdict:
        verdict = WorkflowVerdict(
            workflow=rule.name,
            file=rule.file,
            rule="exact commit" if rule.exact else "latest run at the commit or an ancestor",
            state="missing",
            passed=False,
            detail="",
        )
        chosen: dict[str, Any] | None = None
        relation: str = "unrelated"
        behind: int | None = None
        compared = 0
        for run in self.runs(rule):
            head = str(run.get("head_sha", "")).lower()
            if rule.exact:
                if head == self.sha:
                    chosen, relation, behind = run, "identical", 0
                    break
                continue
            if head != self.sha:
                if compared >= MAX_COMPARISONS:
                    break
                compared += 1
            relation, behind = self.relation(head)
            if relation in {"identical", "ancestor"}:
                chosen = run
                break
        if chosen is None:
            verdict.detail = (
                f"no {'/'.join(sorted(GATE_EVENTS))} run of {rule.file} on {self.branch} for "
                + (
                    "this commit"
                    if rule.exact
                    else "this commit or an ancestor among the latest runs"
                )
            )
            return verdict
        verdict.run_id = _int(chosen.get("id"))
        verdict.run_number = _int(chosen.get("run_number"))
        verdict.run_attempt = _int(chosen.get("run_attempt"))
        verdict.run_url = _text(chosen.get("html_url"))
        verdict.head_sha = _text(chosen.get("head_sha"))
        verdict.event = _text(chosen.get("event"))
        verdict.status = _text(chosen.get("status"))
        verdict.conclusion = _text(chosen.get("conclusion"))
        verdict.created_at = _text(chosen.get("created_at"))
        verdict.relation = relation
        verdict.commits_behind = behind
        at = f"run #{verdict.run_number} at {str(verdict.head_sha)[:12]} ({relation}"
        at += f", {behind} commit(s) earlier)" if relation == "ancestor" and behind else ")"
        if verdict.status != "completed":
            verdict.state = "pending"
            verdict.detail = f"{at} is {verdict.status or 'not completed'}"
        elif verdict.conclusion == "success":
            verdict.state, verdict.passed = "success", True
            verdict.detail = f"{at} succeeded"
        else:
            verdict.state = "failure"
            verdict.detail = f"{at} concluded {verdict.conclusion or 'without a conclusion'}"
        return verdict


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def verify(
    gate: Gate,
    *,
    rules: Sequence[WorkflowRule] = REQUIRED_WORKFLOWS,
    wait_seconds: float = 0.0,
    poll_seconds: float = 60.0,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    log: Callable[[str], None] = print,
) -> list[WorkflowVerdict]:
    """Evaluate every rule, re-checking pending ones until they finish or time runs out."""
    deadline = monotonic() + max(wait_seconds, 0.0)
    verdicts = {rule.name: gate.evaluate(rule) for rule in rules}
    while True:
        pending = [rule for rule in rules if verdicts[rule.name].state == "pending"]
        if not pending or monotonic() >= deadline:
            break
        names = ", ".join(rule.name for rule in pending)
        log(f"Waiting {poll_seconds:.0f}s for {names}")
        sleep(min(poll_seconds, max(deadline - monotonic(), 0.0)))
        for rule in pending:
            verdicts[rule.name] = gate.evaluate(rule)
    for verdict in verdicts.values():
        if verdict.state == "pending":
            verdict.detail += f"; still not completed after {wait_seconds / 60:.0f} minute(s)"
    return [verdicts[rule.name] for rule in rules]


def build_document(
    gate: Gate, verdicts: Sequence[WorkflowVerdict], *, checked_at: datetime
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": "scripts/verify_release_gate.py",
        "repository": gate.repository,
        "branch": gate.branch,
        "deploy_sha": gate.sha,
        "checked_at": checked_at.isoformat(timespec="seconds"),
        "rule": RULE,
        "required_workflows": [rule.name for rule in REQUIRED_WORKFLOWS],
        "passed": bool(verdicts) and all(verdict.passed for verdict in verdicts),
        "workflows": [asdict(verdict) for verdict in verdicts],
    }


def render_markdown(document: Mapping[str, Any]) -> str:
    verdict = "PASSED" if document["passed"] else "FAILED"
    lines = [
        "## Release gate: required CI workflows",
        "",
        f"**{verdict}** for `{document['deploy_sha']}` on `{document['branch']}` "
        f"(checked {document['checked_at']}).",
        "",
        "| Workflow | Result | Run | Commit | Relation | Detail |",
        "|---|---|---|---|---|---|",
    ]
    for item in document["workflows"]:
        run = f"[#{item['run_number']}]({item['run_url']})" if item.get("run_url") else "none"
        commit = f"`{item['head_sha'][:12]}`" if item.get("head_sha") else ""
        lines.append(
            f"| {item['workflow']} | {item['state']} | {run} | {commit} "
            f"| {item.get('relation') or ''} | {str(item['detail']).replace('|', '/')} |"
        )
    lines += ["", f"Rule: {document['rule']}", ""]
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--repo", default=os.environ.get("GITHUB_REPOSITORY"), help="owner/name (GITHUB_REPOSITORY)"
    )
    parser.add_argument("--sha", required=True, help="The 40-character commit being deployed")
    parser.add_argument("--branch", default="main", help="Branch whose runs count (main)")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIRECTORY)
    parser.add_argument(
        "--wait-minutes",
        type=float,
        default=0.0,
        help="Wait this long for queued or running workflows before failing (default 0)",
    )
    parser.add_argument("--poll-seconds", type=float, default=60.0)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    api: GhApi = gh_api,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> int:
    arguments = _parser().parse_args(argv)
    sha = str(arguments.sha).strip().lower()
    if not COMMIT_SHA.fullmatch(sha):
        print("--sha must be a full 40-character commit SHA", file=sys.stderr)
        return 2
    if not arguments.repo or not REPOSITORY.fullmatch(arguments.repo):
        print("--repo must be owner/name (or set GITHUB_REPOSITORY)", file=sys.stderr)
        return 2
    if not BRANCH.fullmatch(arguments.branch):
        print("--branch is not a valid branch name", file=sys.stderr)
        return 2
    gate = Gate(api, arguments.repo, sha, arguments.branch)
    try:
        verdicts = verify(
            gate,
            wait_seconds=arguments.wait_minutes * 60,
            poll_seconds=max(arguments.poll_seconds, 1.0),
            sleep=sleep,
            monotonic=monotonic,
        )
    except GateError as exc:
        print(f"Release gate could not be evaluated: {exc}", file=sys.stderr)
        return 2
    document = build_document(gate, verdicts, checked_at=clock())
    arguments.output_dir.mkdir(parents=True, exist_ok=True)
    (arguments.output_dir / GATE_JSON).write_text(
        json.dumps(document, indent=2) + "\n", encoding="utf-8"
    )
    (arguments.output_dir / GATE_MARKDOWN).write_text(render_markdown(document), encoding="utf-8")
    for verdict in verdicts:
        print(f"{'PASS' if verdict.passed else 'FAIL'} {verdict.workflow}: {verdict.detail}")
    print(f"Release gate {'PASSED' if document['passed'] else 'FAILED'} for {sha}")
    return 0 if document["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
