"""The cloud-deployment.yml gate, build and deploy jobs, and cloud-auto-deallocate.yml."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from scripts.verify_release_gate import REQUIRED_WORKFLOWS

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_README = ROOT / "docs/release-2/evidence/cloud/README.md"


def _workflow(name: str) -> dict[Any, Any]:
    document = yaml.safe_load((ROOT / f".github/workflows/{name}").read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _runs(job: dict[str, Any]) -> str:
    return "\n".join(step.get("run", "") for step in job["steps"])


def _uploads(job: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        step for step in job["steps"] if step.get("uses", "").startswith("actions/upload-artifact@")
    ]


def test_cloud_deployment_runs_after_integration_ci_on_main_or_by_hand() -> None:
    workflow = _workflow("cloud-deployment.yml")
    integration = _workflow("integration-ci.yml")
    # PyYAML's YAML 1.1 loader interprets the Actions `on` key as True.
    triggers = workflow[True]
    assert set(triggers) == {"workflow_run", "workflow_dispatch"}
    assert triggers["workflow_run"] == {
        "workflows": [integration["name"]],
        "types": ["completed"],
        "branches": ["main"],
    }
    # Integration CI runs on every push to main, so the deployment fires once per push.
    assert integration[True]["push"] == {"branches": ["main"]}
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["defaults"]["run"]["shell"] == "bash"  # bash -eo pipefail for the tee'd logs


def test_the_jobs_run_gate_then_build_then_deploy() -> None:
    jobs = _workflow("cloud-deployment.yml")["jobs"]
    assert list(jobs) == ["verify-ci", "build-validate", "deploy"]
    assert jobs["build-validate"]["needs"] == "verify-ci"
    assert jobs["deploy"]["needs"] == ["verify-ci", "build-validate"]


def test_the_gate_job_checks_every_required_workflow_and_always_runs() -> None:
    workflow = _workflow("cloud-deployment.yml")
    job = workflow["jobs"]["verify-ci"]
    condition = " ".join(job["if"].split())
    # Not gated on Azure: the gate is demonstrable before Azure exists.
    assert "AZURE_SUBSCRIPTION_ID" not in condition
    assert "github.event_name == 'workflow_dispatch'" in condition
    assert "github.event.workflow_run.event == 'push'" in condition
    assert "github.event.workflow_run.conclusion != 'cancelled'" in condition
    assert job["permissions"] == {"actions": "read", "contents": "read"}
    assert job["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert "head_sha" in job["env"]["DEPLOY_SHA"]
    runs = _runs(job)
    assert "scripts/verify_release_gate.py" in runs
    assert "--wait-minutes" in runs
    assert "GITHUB_STEP_SUMMARY" in runs
    upload = _uploads(job)[0]
    assert upload["with"]["name"] == "release-gate-${{ env.DEPLOY_SHA }}"
    assert upload["if"] == "always()"
    # Every workflow the gate requires really exists under that name.
    names = {
        _workflow(path.name)["name"] for path in sorted((ROOT / ".github/workflows").glob("*.yml"))
    }
    assert {rule.name for rule in REQUIRED_WORKFLOWS} <= names


def test_the_build_job_builds_and_validates_without_azure() -> None:
    job = _workflow("cloud-deployment.yml")["jobs"]["build-validate"]
    assert job["name"] == "Docker build and validation"
    assert "if" not in job
    assert job["env"]["DEPLOY_SHA"] == "${{ needs.verify-ci.outputs.sha }}"
    runs = _runs(job)
    assert "build --pull" in runs
    assert "scripts/validate_release_images.py" in runs
    assert "azure/login" not in str(job["steps"])
    assert _uploads(job)[0]["with"]["name"] == "image-build-${{ env.DEPLOY_SHA }}"


def test_the_deploy_job_is_skipped_without_azure_and_deploys_the_gated_commit() -> None:
    job = _workflow("cloud-deployment.yml")["jobs"]["deploy"]
    assert job["if"] == "vars.AZURE_SUBSCRIPTION_ID != ''"
    assert job["environment"]["name"] == "production"
    assert job["permissions"] == {"id-token": "write", "contents": "read", "actions": "read"}
    assert job["concurrency"] == {
        "group": "cloud-deployment-production",
        "cancel-in-progress": False,
    }
    environment = job["env"]
    assert environment["IMAGE_TAG"] == "${{ needs.verify-ci.outputs.sha }}"
    assert environment["PROPERTYSCOPE_DEPLOY_SHA"] == environment["IMAGE_TAG"]
    assert environment["PROPERTYSCOPE_CLOUD_AI"] == "false"
    assert environment["UV_NO_DEFAULT_GROUPS"] == "1"


def test_the_dns_label_defaults_to_the_bicep_parameter_default() -> None:
    environment = _workflow("cloud-deployment.yml")["jobs"]["deploy"]["env"]
    parameters = (ROOT / "deployment/azure/main.bicepparam").read_text(encoding="utf-8")
    default = re.search(r"readEnvironmentVariable\('AZURE_DNS_LABEL', '([^']+)'\)", parameters)
    assert default is not None
    assert environment["AZURE_DNS_LABEL"] == (
        f"${{{{ vars.AZURE_DNS_LABEL || '{default.group(1)}' }}}}"
    )


def test_the_deploy_job_keeps_the_daily_shutdown_unless_it_is_switched_off() -> None:
    environment = _workflow("cloud-deployment.yml")["jobs"]["deploy"]["env"]
    assert (
        environment["AZURE_AUTO_SHUTDOWN_TIME"] == "${{ vars.AZURE_AUTO_SHUTDOWN_TIME || '2330' }}"
    )
    parameters = (ROOT / "deployment/azure/main.bicepparam").read_text(encoding="utf-8")
    assert (
        "var autoShutdownSetting = readEnvironmentVariable('AZURE_AUTO_SHUTDOWN_TIME', '2330')"
        in parameters
    )
    # GitHub cannot pass an explicit empty value, so `off` drops the DevTestLab schedule, which
    # some regions (newzealandnorth) do not offer.
    assert (
        "param autoShutdownTime = toLower(autoShutdownSetting) == 'off' ? '' : autoShutdownSetting"
        in parameters
    )
    main = (ROOT / "deployment/azure/main.bicep").read_text(encoding="utf-8")
    assert "module shutdown 'modules/shutdown.bicep' = if (!empty(autoShutdownTime))" in main


def test_the_deploy_job_installs_only_the_root_tooling_and_keeps_ai_off() -> None:
    workflow = _workflow("cloud-deployment.yml")
    job = workflow["jobs"]["deploy"]
    assert workflow["env"] == {"AI_MODE_MCP_ENABLED": "false", "AI_MODE_RAG_ENABLED": "false"}
    runs = _runs(job)
    assert "uv sync --locked\n" in runs
    assert "--all-packages" not in runs and "--all-groups" not in runs
    steps = job["steps"]
    login = next(step for step in steps if step.get("uses", "").startswith("azure/login@"))
    assert set(login["with"]) == {"client-id", "tenant-id", "subscription-id"}
    assert "secrets." not in str(login["with"])  # OIDC: no stored client secret
    for action in ("provision", "push", "deploy", "smoke", "validate-endpoint"):
        assert f"deployment/azure/deploy.sh {action}" in runs, action
    assert "scripts/cloud_deployment_report.py" in runs
    # The gate is re-checked before the first Azure step.
    names = [step.get("name", "") for step in steps]
    recheck = next(i for i, name in enumerate(names) if name.startswith("Re-check the CI gate"))
    assert recheck < names.index("Sign in to Azure with OIDC (no stored credentials)")
    checkout = next(step for step in steps if step.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["persist-credentials"] is False
    ordered = [step.get("id") for step in steps if step.get("id")]
    assert ordered[:4] == ["provision", "push", "deploy", "smoke"]


def test_the_smoke_step_hands_the_deployment_identity_to_cloud_smoke() -> None:
    job = _workflow("cloud-deployment.yml")["jobs"]["deploy"]
    smoke = next(step for step in job["steps"] if step.get("id") == "smoke")
    assert "export ACR_LOGIN_SERVER" in smoke["run"]
    assert '--output-dir "$PROPERTYSCOPE_CLOUD_LOG_DIR/smoke"' in smoke["run"]
    # PROPERTYSCOPE_DEPLOY_SHA and IMAGE_TAG come from the job environment.
    assert {"PROPERTYSCOPE_DEPLOY_SHA", "IMAGE_TAG"} <= set(job["env"])
    for stage in ("provision", "push", "deploy", "smoke"):
        assert f"logs/{stage}.log" in _runs(job), stage


def test_the_evidence_readme_names_every_artifact_the_workflow_uploads() -> None:
    jobs = _workflow("cloud-deployment.yml")["jobs"]
    readme = EVIDENCE_README.read_text(encoding="utf-8")
    for job in jobs.values():
        for upload in _uploads(job):
            name = upload["with"]["name"].split("${{")[0]
            assert f"`{name}<sha>`" in readme, name
            assert upload["if"] == "always()"
            assert upload["with"]["retention-days"] == 90
    deploy_upload = _uploads(jobs["deploy"])[0]
    assert "!.propertyscope-runtime/cloud/*.payload.sh" in deploy_upload["with"]["path"]


def test_auto_deallocate_runs_nightly_or_by_hand_once_azure_is_configured() -> None:
    workflow = _workflow("cloud-auto-deallocate.yml")
    assert set(workflow[True]) == {"schedule", "workflow_dispatch"}
    assert workflow[True]["schedule"] == [{"cron": "30 12 * * *"}]  # 23:30 AEDT
    assert workflow["permissions"] == {"contents": "read"}
    assert list(workflow["jobs"]) == ["deallocate"]
    job = workflow["jobs"]["deallocate"]
    assert job["if"] == "vars.AZURE_SUBSCRIPTION_ID != ''"
    # Its own environment without reviewers: an unattended backstop never waits for approval.
    assert job["environment"] == "operations"
    assert job["permissions"] == {"id-token": "write", "contents": "read"}
    # The deployment's group, so it never deallocates the VM in the middle of a deployment.
    deploy = _workflow("cloud-deployment.yml")["jobs"]["deploy"]
    assert job["concurrency"] == deploy["concurrency"]
    assert job["concurrency"] == {
        "group": "cloud-deployment-production",
        "cancel-in-progress": False,
    }


def test_auto_deallocate_only_signs_in_and_deallocates_the_vm() -> None:
    job = _workflow("cloud-auto-deallocate.yml")["jobs"]["deallocate"]
    steps = job["steps"]
    assert not any(step.get("uses", "").startswith("actions/checkout@") for step in steps)
    login = next(step for step in steps if step.get("uses", "").startswith("azure/login@"))
    assert set(login["with"]) == {"client-id", "tenant-id", "subscription-id"}
    # Its own identity, which may only read, start and stop the VM, never the deployer's.
    assert login["with"]["client-id"] == "${{ vars.AZURE_OPERATIONS_CLIENT_ID }}"
    assert "AZURE_CLIENT_ID" not in str(job)
    assert "secrets." not in str(job)  # OIDC: no stored credential
    assert job["env"]["VM_NAME"] == "${{ vars.AZURE_NAME_PREFIX || 'propertyscope' }}-prod-vm"
    runs = _runs(job)
    assert 'az vm deallocate --resource-group "$AZURE_RESOURCE_GROUP" --name "$VM_NAME"' in runs
    # A VM that is already deallocated, or does not exist yet, is left alone.
    assert "PowerState/deallocated | PowerState/deallocating)" in runs
    # Only a missing VM or group counts as nothing to do; any other error fails the run.
    assert "grep -qE 'ResourceNotFound|ResourceGroupNotFound'" in runs
    assert "2>/dev/null || echo missing" not in runs
    assert "GITHUB_STEP_SUMMARY" in runs
