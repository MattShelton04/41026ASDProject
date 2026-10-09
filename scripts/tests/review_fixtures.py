"""Small, realistic Release 2 evidence used by the review-mode tests.

The shapes follow what the evidence producers write: Multi-Agent Server ``WorkflowHistoryEntry``
and ``CoordinationAuditEntry`` JSON Lines, Ruff/detect-secrets/pip-audit JSON, the CI evidence
Markdown built from ``shared_testkit.junit_summary``, and the cloud smoke JSON.
"""

from __future__ import annotations

import json
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
SERVICES = (
    "shared-frontend",
    "f1-backend",
    "f2-backend",
    "f3-backend",
    "f4-backend",
    "f5-backend",
)


def write_evidence(root: Path) -> Path:
    """Write complete evidence for all three review modes below ``root``."""
    write_multi_agent(root)
    write_testing(root)
    write_cloud(root)
    return root


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


def smoke(**changes: object) -> dict[str, object]:
    checks: list[dict[str, object]] = [
        {"name": "shared home page", "category": "frontend", "passed": True, "status_code": 200}
    ]
    checks += [
        {"name": f"{student} CRUD", "category": "crud", "feature": student, "passed": True}
        for student in STUDENTS
    ]
    checks.append({"name": "AI routes disabled", "category": "ai_disabled", "passed": True})
    value: dict[str, object] = {
        "schema_version": "1.0",
        "base_url": "https://propertyscope-g20.australiaeast.cloudapp.azure.com",
        "commit_sha": COMMIT,
        "generated_at": "2026-10-20T03:15:00Z",
        "ai_enabled": False,
        "images": {
            service: f"psg20acr.azurecr.io/propertyscope/{service}:{COMMIT}" for service in SERVICES
        },
        "checks": checks,
    }
    value.update(changes)
    return value


def write_cloud(root: Path) -> None:
    cloud = root / "cloud"
    cloud.mkdir(parents=True, exist_ok=True)
    (cloud / "cloud-deployment-report.md").write_text(
        f"""# Cloud deployment report

Deployed commit {COMMIT} to Azure (australiaeast) by cloud-deployment.yml run
{REPOSITORY}/actions/runs/1234567999.

Public URL: https://propertyscope-g20.australiaeast.cloudapp.azure.com

AI-mode, MCP, RAG and the Multi-Agent Server are disabled in this baseline deployment.
""",
        encoding="utf-8",
    )
    write_json(cloud / "smoke.json", smoke())
    logs = cloud / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "deploy.log").write_text(
        "2026-10-20T03:10:00Z Logging in with OIDC federated credential\n"
        "2026-10-20T03:11:00Z Pushing images tagged " + COMMIT + "\n"
        "2026-10-20T03:13:00Z az vm run-command invoke: compose up --wait completed\n"
        "2026-10-20T03:15:00Z Smoke test passed: 7 of 7 cases\n",
        encoding="utf-8",
    )
