"""cloud-ai.yml: the manual bonus-tier workflow (B1-B4) beside the AI-off deployment."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _workflow(name: str) -> dict[Any, Any]:
    document = yaml.safe_load((ROOT / f".github/workflows/{name}").read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _job() -> dict[str, Any]:
    job = _workflow("cloud-ai.yml")["jobs"]["ai-tier"]
    assert isinstance(job, dict)
    return job


def _step(job: dict[str, Any], name_start: str) -> dict[str, Any]:
    return next(step for step in job["steps"] if step["name"].startswith(name_start))


def test_it_runs_only_by_hand_from_main_once_azure_is_configured() -> None:
    workflow = _workflow("cloud-ai.yml")
    triggers = workflow[True]  # PyYAML reads the bare key `on` as True
    assert set(triggers) == {"workflow_dispatch"}
    assert triggers["workflow_dispatch"]["inputs"]["action"]["options"] == ["on", "probe", "off"]
    job = _job()
    assert "vars.AZURE_SUBSCRIPTION_ID != ''" in job["if"]
    assert "github.ref == 'refs/heads/main'" in job["if"]
    assert workflow["permissions"] == {"contents": "read"}


def test_it_shares_the_reviewed_environment_and_the_deployment_lock() -> None:
    job = _job()
    deploy = _workflow("cloud-deployment.yml")["jobs"]["deploy"]
    assert job["environment"] == "production"
    assert job["concurrency"] == deploy["concurrency"]
    assert job["concurrency"]["cancel-in-progress"] is False
    login = _step(job, "Sign in to Azure")
    assert login["with"]["client-id"] == "${{ vars.AZURE_CLIENT_ID }}"


def test_the_ai_tier_is_switched_from_the_commit_the_vm_runs() -> None:
    job = _job()
    deployed = _step(job, "Read the commit the VM is running")
    assert "deploy.sh status" in deployed["run"]
    assert "^[0-9a-f]{40}$" in deployed["run"]
    checkout = _step(job, "Check out the deployed commit")
    assert checkout["with"]["ref"] == "${{ steps.deployed.outputs.sha }}"
    toggle = _step(job, "Turn the AI tier")
    assert toggle["working-directory"] == "deployed"
    assert toggle["env"]["IMAGE_TAG"] == "${{ steps.deployed.outputs.sha }}"
    assert toggle["env"]["PROPERTYSCOPE_GIT_SHA"] == "${{ steps.deployed.outputs.sha }}"
    assert 'deploy.sh ai "$ACTION"' in toggle["run"]
    assert toggle["if"] == "inputs.action != 'probe'"


def test_only_the_probe_step_sees_the_operator_password() -> None:
    job = _job()
    probe = _step(job, "Probe B1-B4")
    assert probe["env"]["PROPERTYSCOPE_OPERATOR_PASSWORD"] == (
        "${{ secrets.PROPERTYSCOPE_OPERATOR_PASSWORD }}"
    )
    assert "deploy.sh ai-probe" in probe["run"]
    assert probe["if"] == "inputs.action != 'off'"
    holders = [
        step["name"]
        for step in job["steps"]
        if "PROPERTYSCOPE_OPERATOR_PASSWORD" in str(step.get("env", {}))
    ]
    assert holders == [probe["name"]]
    assert "PROPERTYSCOPE_OPERATOR_PASSWORD" not in str(job["env"])
    assert job["env"]["PROPERTYSCOPE_ACME_EMAIL"] == "${{ secrets.PROPERTYSCOPE_ACME_EMAIL }}"


def test_the_report_is_uploaded_without_run_command_payloads() -> None:
    job = _job()
    upload = next(
        step for step in job["steps"] if step.get("uses", "").startswith("actions/upload-artifact@")
    )
    assert upload["if"] == "always()"
    assert "!.propertyscope-runtime/cloud/*.payload.sh" in upload["with"]["path"]
    assert _step(job, "Sign out of Azure")["if"] == "always()"


def test_every_action_is_pinned_to_a_commit() -> None:
    for step in _job()["steps"]:
        if "uses" in step:
            reference = step["uses"].split("@", 1)[1]
            assert len(reference.split()[0]) == 40, step["uses"]
