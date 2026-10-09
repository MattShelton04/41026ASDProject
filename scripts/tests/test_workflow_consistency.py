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


@pytest.mark.parametrize("number", range(1, 6))
def test_feature_endpoint_tests_run_in_ci_with_junit_evidence(number: int) -> None:
    """A slice with `tests/endpoints` must run them live and keep the JUnit report."""
    if not (ROOT / f"student-{number}/tests/endpoints").is_dir():
        pytest.skip(f"student-{number} has no endpoint tests yet")
    workflow_path = f".github/workflows/student-{number}.yml"
    workflow = yaml.safe_load((ROOT / workflow_path).read_text(encoding="utf-8"))
    for event in ("push", "pull_request"):
        assert "shared/testkit/**" in workflow[True][event]["paths"], (workflow_path, event)
    steps = [step for job in workflow["jobs"].values() for step in job.get("steps", [])]
    runs = [
        step
        for step in steps
        if f"pytest student-{number}/tests/endpoints -m endpoint" in step.get("run", "")
    ]
    assert runs, f"{workflow_path} never runs its endpoint tests"
    for step in runs:
        assert step["env"]["PROPERTYSCOPE_ENDPOINT_BASE_URL"].startswith("http://127.0.0.1:")
        assert "--junitxml=" in step["run"]
    summary = [step for step in steps if "shared_testkit.junit_summary" in step.get("run", "")]
    assert summary and all("$GITHUB_STEP_SUMMARY" in step["run"] for step in summary)
    assert all("--require-success" in step["run"] for step in summary)
    uploads = [
        step for step in steps if step.get("uses", "").startswith("actions/upload-artifact@")
    ]
    assert any(
        step["with"]["name"] == f"student-{number}-endpoint-tests"
        and step["if"].startswith("${{ !cancelled()")
        for step in uploads
    ), f"{workflow_path} must upload student-{number}-endpoint-tests"


def _workflow(name: str) -> dict[object, object]:
    document = yaml.safe_load((ROOT / f".github/workflows/{name}").read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def test_cloud_deployment_runs_only_after_integration_ci_or_by_hand() -> None:
    workflow = _workflow("cloud-deployment.yml")
    integration = _workflow("integration-ci.yml")
    # PyYAML's YAML 1.1 loader interprets the Actions `on` key as True.
    triggers = workflow[True]
    assert isinstance(triggers, dict)
    assert set(triggers) == {"workflow_run", "workflow_dispatch"}
    assert triggers["workflow_run"] == {
        "workflows": [integration["name"]],
        "types": ["completed"],
        "branches": ["main"],
    }
    job = workflow["jobs"]["deploy"]  # type: ignore[index]
    condition = " ".join(job["if"].split())
    assert "vars.AZURE_SUBSCRIPTION_ID != ''" in condition
    assert "github.event.workflow_run.conclusion == 'success'" in condition
    assert "github.event.workflow_run.event == 'push'" in condition
    assert "github.event_name == 'workflow_dispatch'" in condition
    assert job["environment"]["name"] == "production"
    assert job["permissions"] == {"id-token": "write", "contents": "read"}
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"]["cancel-in-progress"] is False  # type: ignore[index]


def test_cloud_deployment_keeps_ai_off_uses_oidc_and_the_reusable_script() -> None:
    workflow = _workflow("cloud-deployment.yml")
    job = workflow["jobs"]["deploy"]  # type: ignore[index]
    assert workflow["env"] == {"AI_MODE_MCP_ENABLED": "false", "AI_MODE_RAG_ENABLED": "false"}
    assert job["env"]["PROPERTYSCOPE_CLOUD_AI"] == "false"
    assert "head_sha" in job["env"]["IMAGE_TAG"]
    steps = job["steps"]
    login = next(step for step in steps if step.get("uses", "").startswith("azure/login@"))
    assert set(login["with"]) == {"client-id", "tenant-id", "subscription-id"}
    assert "secrets." not in str(login["with"])  # OIDC: no stored client secret
    runs = "\n".join(step.get("run", "") for step in steps)
    for action in ("provision", "push", "deploy", "smoke", "validate-endpoint"):
        assert f"deployment/azure/deploy.sh {action}" in runs, action
    assert "scripts/cloud_deployment_report.py" in runs
    checkout = next(step for step in steps if step.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["persist-credentials"] is False
    upload = next(
        step for step in steps if step.get("uses", "").startswith("actions/upload-artifact@")
    )
    assert upload["if"] == "always()"
    ordered = [step.get("id") for step in steps if step.get("id")]
    assert ordered[:4] == ["provision", "push", "deploy", "smoke"]


def test_every_workflow_pins_each_action_to_one_full_commit_sha() -> None:
    pins: dict[str, set[str]] = {}
    for path in sorted((ROOT / ".github/workflows").glob("*.yml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job in workflow["jobs"].values():
            for step in job.get("steps", []):
                action = step.get("uses", "")
                if not action or action.startswith("./"):
                    continue
                assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", action), (path.name, action)
                name, sha = action.split("@")
                pins.setdefault(name, set()).add(sha)
    inconsistent = {name: shas for name, shas in pins.items() if len(shas) > 1}
    assert not inconsistent
