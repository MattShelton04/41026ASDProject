"""Small, realistic Release 2 evidence used by the review-mode tests.

The shapes follow what the evidence producers write: Multi-Agent Server ``WorkflowHistoryEntry``
and ``CoordinationAuditEntry`` JSON Lines, Ruff/detect-secrets/pip-audit JSON, the CI evidence
Markdown built from ``shared_testkit.junit_summary``, and the cloud smoke JSON.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

COMMIT = "3f2a9c1d8e7b6a5f4e3d2c1b0a9f8e7d6c5b4a39"
REPOSITORY = "https://github.com/MattShelton04/41026ASDProject"
STUDENTS = tuple(f"student-{number}" for number in range(1, 6))
TOOLS = {
    "student-1": ("platform.capabilities.v1", "data.releases.list.v1"),
    "student-2": ("market.capabilities.v1", "market.trends.v1"),
    "student-3": ("suburbs.capabilities.v1", "suburbs.profile.v1"),
    "student-4": ("diligence.capabilities.v1", "diligence.dossier.read.v1"),
    "student-5": ("workspaces.capabilities.v1", "workspaces.shortlist.v1"),
}


def write_evidence(root: Path) -> Path:
    """Write complete evidence for all three review modes below ``root``."""
    write_multi_agent(root)
    write_testing(root)
    write_cloud(root)
    return root


def drop_student(root: Path, student: str) -> None:
    """Remove one student's multi-agent and CI evidence, as if they had not submitted it."""
    shutil.rmtree(root / "multi-agent" / student, ignore_errors=True)
    shutil.rmtree(root / "ci" / student, ignore_errors=True)
    (root / "ci" / f"{student}.md").unlink(missing_ok=True)


def run_id_for(student: str) -> str:
    return str(UUID(int=int(student[-1]) * 0x1111))


def history(student: str, *, decision_state: str = "approved") -> list[dict[str, object]]:
    run_id = run_id_for(student)
    start = datetime(2026, 10, 14, 1, 0, tzinfo=UTC)
    steps = [
        (None, "planning", "system", "multi-agent-server", "Run created"),
        ("planning", "working", "planner", "planner", "Plan accepted"),
        ("working", "reviewing", "worker", "worker", "Evidence gathered"),
        ("reviewing", "awaiting_human", "reviewer", "reviewer", "Review ready"),
        ("awaiting_human", decision_state, "human", f"{student} owner", "Human decision"),
    ]
    return [
        {
            "sequence": index,
            "run_id": run_id,
            "request_id": f"req-{student}",
            "at": (start + timedelta(seconds=index * 7)).isoformat(),
            "from_state": source,
            "to_state": target,
            "round": 1,
            "actor": actor,
            "role": role,
            "reason": reason,
        }
        for index, (source, target, role, actor, reason) in enumerate(steps, start=1)
    ]


def audit(student: str, *, tool: str | None = None) -> list[dict[str, object]]:
    run_id = run_id_for(student)
    allowed = list(TOOLS[student])
    start = datetime(2026, 10, 14, 1, 0, 1, tzinfo=UTC)
    events: list[tuple[str, str, str, dict[str, object]]] = [
        (
            "run.created",
            "system",
            "multi-agent-server",
            {"template_id": f"{student}-review", "allowed_tools": allowed},
        ),
        ("model.invocation", "planner", "planner", {"outcome": "succeeded"}),
        ("plan.created", "planner", "planner", {"steps": 1}),
        ("agent.handoff", "planner", "planner", {"from": "planner", "to": "worker"}),
        (
            "tool.call",
            "worker",
            "worker",
            {"tool_name": tool or allowed[1], "outcome": "succeeded", "transport": "mcp"},
        ),
        ("worker.completed", "worker", "worker", {"steps": 1}),
        ("agent.handoff", "worker", "worker", {"from": "worker", "to": "reviewer"}),
        ("review.completed", "reviewer", "reviewer", {"recommendation": "approve"}),
        ("agent.handoff", "reviewer", "reviewer", {"from": "reviewer", "to": "human"}),
        (
            "decision.recorded",
            "human",
            f"{student} owner",
            {"decision": "approve", "note": "Evidence matches the release."},
        ),
    ]
    return [
        {
            "sequence": index,
            "run_id": run_id,
            "request_id": f"req-{student}",
            "at": (start + timedelta(seconds=index * 4)).isoformat(),
            "event": event,
            "role": role,
            "actor": actor,
            "round": 1,
            "detail": detail,
        }
        for index, (event, role, actor, detail) in enumerate(events, start=1)
    ]


def write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )


def write_multi_agent(root: Path) -> None:
    for student in STUDENTS:
        directory = root / "multi-agent" / student
        write_jsonl(directory / "workflow_history.jsonl", history(student))
        write_jsonl(directory / "coordination_audit.jsonl", audit(student))


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def write_testing(root: Path) -> None:
    security = root / "security"
    security.mkdir(parents=True, exist_ok=True)
    (security / "pre-commit-report.md").write_text(
        f"""# Pre-commit security report

Commit: {COMMIT}

| Scan | Result |
|---|---|
| Ruff security rules (S) | 1 finding, explained below |
| detect-secrets | 1 audited false positive |
| pip-audit | 1 accepted vulnerability |

## Explained findings

- S603 in devtools/host_runtime.py: the subprocess arguments are a fixed interpreter
  command built from `sys.executable`; no shell and no user input.

## Accepted risks

- GHSA-4xqq-73wg-5mjp (pip 24.0): build-time only, not shipped in any image; upgrade
  scheduled for Release 3.
""",
        encoding="utf-8",
    )
    write_json(
        security / "ruff-security.json",
        [
            {
                "code": "S603",
                "message": "`subprocess` call: check for execution of untrusted input",
                "filename": "C:/repo/scripts/devtools/host_runtime.py",
                "location": {"row": 386, "column": 27},
                "end_location": {"row": 386, "column": 43},
                "fix": None,
                "noqa_row": 386,
                "url": "https://docs.astral.sh/ruff/rules/subprocess-without-shell-equals-true",
            }
        ],
    )
    write_json(
        security / "detect-secrets.json",
        {
            "version": "1.5.0",
            "results": {
                "docs/release-1/host-runtime.md": [
                    {
                        "type": "Secret Keyword",
                        "filename": "docs/release-1/host-runtime.md",
                        "hashed_secret": "0" * 40,
                        "is_verified": False,
                        "line_number": 42,
                        "is_secret": False,
                    }
                ]
            },
        },
    )
    write_json(
        security / "pip-audit.json",
        {
            "dependencies": [
                {"name": "flask", "version": "3.1.2", "vulns": []},
                {"name": "httpx", "version": "0.28.1", "vulns": []},
                {
                    "name": "pip",
                    "version": "24.0",
                    "vulns": [
                        {
                            "id": "GHSA-4xqq-73wg-5mjp",
                            "fix_versions": ["25.0"],
                            "aliases": ["CVE-2025-8869"],
                            "description": "Tar extraction may write outside the target.",
                        }
                    ],
                },
            ],
            "fixes": [],
        },
    )
    for number, student in enumerate(STUDENTS, start=1):
        write_ci(root, student, run=1_234_567_890 + number)


def write_ci(
    root: Path,
    student: str,
    *,
    run: int,
    conclusion: str = "success",
    outcomes: tuple[str, str] = ("passed", "passed"),
) -> None:
    failed = sum(1 for outcome in outcomes if outcome == "failed")
    passed = len(outcomes) - failed
    verdict = "PASSED" if not failed else "FAILED"
    totals = (
        f"**{verdict}**: {passed} passed, {failed} failed, 0 errors, 0 skipped "
        f"of {len(outcomes)} tests in 1.42s"
    )
    path = root / "ci" / f"{student}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""# {student} CI endpoint evidence

| Field | Value |
|---|---|
| Workflow | {student}.yml |
| Run URL | {REPOSITORY}/actions/runs/{run} |
| Commit SHA | {COMMIT} |
| Conclusion | {conclusion} |

Endpoints under test: GET /api/v1/items and POST /api/v1/items.

### {student} endpoint tests

{totals}

| Test | Outcome | Duration (s) | Message |
|---|---|---:|---|
| `tests.endpoint.test_api::test_list_items` | {outcomes[0]} | 0.512 | |
| `tests.endpoint.test_api::test_create_item` | {outcomes[1]} | 0.908 | |
""",
        encoding="utf-8",
    )
    result = f"{passed} passed" + (f", {failed} failed" if failed else "") + " in 1.42s"
    log = root / "ci" / student / "run.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(
        "".join(
            f"Feature integrated stack\tRun {student} endpoint tests\t2026-10-09T04:09:0{i}Z "
            f"{line}\n"
            for i, line in enumerate(
                (
                    f"{outcomes[0].upper()} tests/endpoints/test_api.py::test_list_items",
                    f"{outcomes[1].upper()} tests/endpoints/test_api.py::test_create_item",
                    result,
                )
            )
        ),
        encoding="utf-8",
    )


# --- Cloud evidence ---------------------------------------------------------------------------
# Built by the real producers (scripts/cloud_smoke.py, scripts/verify_release_gate.py and
# scripts/validate_release_images.py) against fakes in cloud_fixtures, never written by hand, so
# a producer/collector mismatch fails the cloud review tests.

CLOUD_URL = "https://propertyscope-nsw-g20.australiaeast.cloudapp.azure.com"
REGISTRY = "psg20acr.azurecr.io"
SMOKE_PATH = "cloud/cloud-smoke.json"
GATE_PATH = "cloud/release-gate.json"
BUILD_PATH = "cloud/image-build.json"
GITHUB_REPOSITORY = "MattShelton04/41026ASDProject"


def smoke(**changes: object) -> dict[str, object]:
    """``cloud-smoke.json`` for a passing deployment of COMMIT, with ``changes`` applied."""
    from scripts.tests import cloud_fixtures

    value: dict[str, object] = cloud_fixtures.smoke_document(
        base_url=CLOUD_URL, commit_sha=COMMIT, registry=REGISTRY
    )
    value.update(changes)
    return value


def release_gate(**changes: object) -> dict[str, object]:
    """``release-gate.json`` with every required workflow green at COMMIT."""
    from scripts.tests import cloud_fixtures

    value: dict[str, object] = cloud_fixtures.release_gate_document(
        sha=COMMIT, repository=GITHUB_REPOSITORY
    )
    value.update(changes)
    return value


def image_build(**changes: object) -> dict[str, object]:
    """``image-build.json`` for a passing Docker build and validation of COMMIT."""
    from scripts.tests import cloud_fixtures

    value: dict[str, object] = cloud_fixtures.image_build_document(sha=COMMIT)
    value.update(changes)
    return value


def write_cloud(root: Path) -> None:
    cloud = root / "cloud"
    cloud.mkdir(parents=True, exist_ok=True)
    (cloud / "cloud-deployment-report.md").write_text(
        f"""# Cloud deployment report

Generated 2026-10-20T03:16:00+00:00 by `scripts/cloud_deployment_report.py` from the deployment's
own logs.

## Summary

| Item | Value |
|---|---|
| Result | **SUCCEEDED** |
| Public URL | {CLOUD_URL} |
| Commit / image tag | `{COMMIT}` / `{COMMIT}` |
| Trigger | workflow_run by MattShelton04 |
| Workflow run | {REPOSITORY}/actions/runs/1234567999 |
| Gating CI run | {REPOSITORY}/actions/runs/1234567990 |
| AI tier | flag off (PROPERTYSCOPE_CLOUD_AI), edge reports disabled |
""",
        encoding="utf-8",
    )
    write_json(root / SMOKE_PATH, smoke())
    write_json(root / GATE_PATH, release_gate())
    write_json(root / BUILD_PATH, image_build())
    logs = cloud / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "deploy.log").write_text(
        "[deploy.sh 03:10:00] Running 'deploy' on propertyscope-prod-vm through az vm "
        "run-command invoke\n"
        f"[deploy.sh 03:11:00] Pushed {REGISTRY}/propertyscope/f1-backend:{COMMIT}\n"
        "[deploy.sh 03:13:00] PROPERTYSCOPE_EXIT=0\n"
        f"[deploy.sh 03:13:01] Deployed {COMMIT} to {CLOUD_URL}\n",
        encoding="utf-8",
    )
