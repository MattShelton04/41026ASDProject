"""All quality workflows use the same immutable tool action references."""

from __future__ import annotations

import re
import tomllib
from fnmatch import fnmatchcase
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


@pytest.mark.parametrize("number", range(1, 6))
def test_feature_workflow_triggers_cover_workspace_and_compose_build_inputs(number: int) -> None:
    """A manifest-only or workflow-only change must still test affected images."""
    workflow_path = f".github/workflows/student-{number}.yml"
    workflow = yaml.safe_load((ROOT / workflow_path).read_text(encoding="utf-8"))
    workspace = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    build_inputs = {
        workflow_path,
        ".dockerignore",
        ".python-version",
        "pyproject.toml",
        "uv.lock",
        "docker-compose.yml",
        "docker-compose.dev.yml",
        "deployment/enabled-features.compose.yml",
        *(f"{member}/pyproject.toml" for member in workspace["tool"]["uv"]["workspace"]["members"]),
    }
    for event in ("push", "pull_request"):
        # PyYAML's YAML 1.1 loader interprets the Actions `on` key as True.
        patterns = workflow[True][event]["paths"]
        missing = sorted(
            path
            for path in build_inputs
            if not any(fnmatchcase(path, pattern) for pattern in patterns)
        )
        assert not missing, f"{workflow_path} {event} omits build inputs: {missing}"


def test_feature_3_smoke_uses_images_loaded_by_the_managed_builder() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/student-3.yml").read_text())
    steps = workflow["jobs"]["feature-stack"]["steps"]
    builder_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("uses", "").startswith("docker/setup-buildx-action@")
    )
    build_index = next(index for index, step in enumerate(steps) if step.get("id") == "build")
    assert builder_index < build_index
    build = steps[build_index]
    assert build["uses"].startswith("docker/bake-action@")
    assert build["with"]["load"] is True
    targets = set(build["with"]["targets"].split(","))
    assert targets == {"f3-database", "f3-backend", "f3-frontend"}
    cache_options = build["with"]["set"].splitlines()
    for target in targets:
        assert any(option.startswith(f"{target}.cache-from=type=gha,") for option in cache_options)
        assert any(option.startswith(f"{target}.cache-to=type=gha,") for option in cache_options)
    start = next(
        step["run"] for step in steps if step["name"] == "Start the Feature 3 fixture stack"
    )
    assert "--no-build" in start.split()
    assert targets <= set(start.split())
    diagnostics = next(
        step for step in steps if step["name"] == "Capture Docker builder diagnostics"
    )
    assert diagnostics["if"] == "failure() && steps.build.outcome == 'failure'"
    assert "docker logs" in diagnostics["run"]


@pytest.mark.parametrize("number", (1, 3))
def test_build_cache_exports_are_optional_and_bounded(number: int) -> None:
    workflow = yaml.safe_load((ROOT / f".github/workflows/student-{number}.yml").read_text())
    builds = [
        step
        for job in workflow["jobs"].values()
        for step in job["steps"]
        if step.get("uses", "").startswith("docker/bake-action@")
    ]
    assert builds
    for build in builds:
        options = build["with"]["set"].splitlines()
        imports = [option for option in options if ".cache-from=" in option]
        exports = [option for option in options if ".cache-to=" in option]
        assert imports and exports
        assert all("timeout=2m" in option for option in [*imports, *exports])
        assert all("ignore-error=true" in option for option in exports)
        assert build.get("continue-on-error", False) is False
