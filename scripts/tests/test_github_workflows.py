"""Regression tests for the intentionally small GitHub Actions surface."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
PINNED_ACTION = re.compile(r"^[^\s]+@[0-9a-f]{40}$")


def _workflow(name: str) -> dict[str, object]:
    document = yaml.load((WORKFLOWS / name).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(document, dict)
    return document


def test_student_1_working_set_matches_its_integrated_runtime_dependencies() -> None:
    workflow = _workflow("student-1.yml")
    triggers = workflow["on"]
    assert isinstance(triggers, dict)
    push = triggers["push"]
    pull_request = triggers["pull_request"]
    assert isinstance(push, dict)
    assert isinstance(pull_request, dict)

    expected = {
        ".dockerignore",
        ".github/workflows/student-1.yml",
        ".python-version",
        "ai-services/agent-core/**",
        "ai-services/ai-mode/**",
        "docker-compose.yml",
        "docker-compose.dev.yml",
        "pyproject.toml",
        "scripts/__init__.py",
        "scripts/dev.py",
        "scripts/devtools/**",
        "scripts/verify_release0_stack.py",
        "shared/contracts/**",
        "shared/frontend/**",
        "student-1/**",
        "student-2/pyproject.toml",
        "student-3/pyproject.toml",
        "student-4/pyproject.toml",
        "student-5/pyproject.toml",
        "uv.lock",
    }
    assert set(push["paths"]) == expected
    assert set(pull_request["paths"]) == expected


def test_integration_gate_does_not_duplicate_the_feature_stack_build() -> None:
    workflow = _workflow("integration-ci.yml")
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    assert set(jobs) == {"quality"}


def test_workflows_pin_remote_actions_to_commit_shas() -> None:
    uses: list[str] = []
    for path in WORKFLOWS.glob("*.yml"):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("uses:"):
                uses.append(stripped.removeprefix("uses:").split("#", maxsplit=1)[0].strip())

    assert uses
    assert all(PINNED_ACTION.fullmatch(action) for action in uses)
