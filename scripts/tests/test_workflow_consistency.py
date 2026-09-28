"""All quality workflows use the same immutable tool action references."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_integration_ci_validates_the_compose_models_without_any_ai_service() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/integration-ci.yml").read_text(encoding="utf-8")
    )
    assert workflow["env"]["AI_MODE_MCP_ENABLED"] == "false"
    assert workflow["env"]["AI_MODE_RAG_ENABLED"] == "false"
    steps = workflow["jobs"]["quality"]["steps"]
    compose = next(
        step["run"] for step in steps if step["name"] == "Validate integrated Compose model"
    )
    commands = compose.strip().splitlines()
    assert len(commands) == 2
    assert all(command.endswith(" config --quiet") for command in commands)
    assert commands[-1].split() == [
        "docker",
        "compose",
        "--file",
        "docker-compose.yml",
        "--file",
        "deployment/enabled-features.compose.yml",
        "--file",
        "docker-compose.dev.yml",
        "--profile",
        "release-0",
        "config",
        "--quiet",
    ]
    assert "ai-container" not in compose


@pytest.mark.parametrize("number", range(1, 6))
def test_feature_workflows_pin_external_actions(number: int) -> None:
    source = (ROOT / f".github/workflows/student-{number}.yml").read_text(encoding="utf-8")
    workflow = yaml.safe_load(source)
    assert workflow["permissions"] == {"contents": "read"}
    for job in workflow["jobs"].values():
        for step in job.get("steps", []):
            action = step.get("uses", "")
            if action and not action.startswith("./"):
                assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", action), action


@pytest.mark.parametrize("number", (2, 4, 5))
def test_newer_feature_jobs_install_node_and_disable_persisted_credentials(number: int) -> None:
    source = (ROOT / f".github/workflows/student-{number}.yml").read_text(encoding="utf-8")
    workflow = yaml.safe_load(source)
    assert workflow["concurrency"]["cancel-in-progress"] is True
    for job in workflow["jobs"].values():
        assert job["timeout-minutes"] <= 25
        steps = job["steps"]
        checkout = next(
            step for step in steps if step.get("uses", "").startswith("actions/checkout@")
        )
        assert checkout["with"]["persist-credentials"] is False
        assert any(step.get("uses", "").startswith("actions/setup-node@") for step in steps)
