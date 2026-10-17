"""Security audit fixes (17 October 2026): the IMDS guard, the B6 validator and CODEOWNERS.

Shell behaviour runs only where a POSIX bash is available; no Azure, Docker or network. The fake
az here is a bash script, so no Windows path conversion is involved.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from scripts.tests.test_azure_deployment import AZURE, ROOT, VM_HARNESS, _run_bash

IMDS_CHECK = "a container cannot reach the instance metadata service (IMDS guard)"

# --- IMDS guard on the VM ------------------------------------------------------------------------

GUARD_FAKES = r"""
install() { printf 'install %s\n' "$*" >>"$WORK/actions"; }
systemctl() {
    printf 'systemctl %s\n' "$*" >>"$WORK/actions"
    [[ $1 != restart || -z ${FAIL_RESTART:-} ]]
}
"""


def test_vm_installs_enables_and_restarts_the_imds_guard(tmp_path: Path) -> None:
    script = VM_HARNESS + GUARD_FAKES + "(install_imds_guard) && echo installed\n"
    completed = _run_bash(script, tmp_path, FAKE_RESPONSES="200:{}")
    assert "installed" in completed.stdout, completed.stderr
    assert (tmp_path / "actions").read_text(encoding="utf-8").splitlines() == [
        "install -m 0644 /opt/propertyscope/app/deployment/azure/systemd/"
        "propertyscope-imds-guard.service /etc/systemd/system/",
        "systemctl daemon-reload",
        "systemctl enable propertyscope-imds-guard.service",
        "systemctl restart propertyscope-imds-guard.service",
    ]


def test_vm_deploy_stops_when_the_imds_guard_does_not_start(tmp_path: Path) -> None:
    script = VM_HARNESS + GUARD_FAKES + "(install_imds_guard) && echo installed\n"
    completed = _run_bash(script, tmp_path, FAKE_RESPONSES="200:{}", FAIL_RESTART="1")
    assert "installed" not in completed.stdout
    assert "the IMDS guard did not start" in completed.stderr


@pytest.mark.parametrize(
    ("probe", "verdict"),
    [("blocked", "PASS"), ("reachable", "FAIL"), ("", "FAIL")],
    ids=["blocked", "reachable", "exec-failed"],
)
def test_vm_imds_check_passes_only_when_the_connection_fails(
    tmp_path: Path, probe: str, verdict: str
) -> None:
    # A missing container or a failed exec prints nothing, which must never pass.
    script = VM_HARNESS + (
        'docker() { printf "%s\\n" "$*" >"$WORK/docker"; [[ -n $PROBE ]] && echo "$PROBE"; }\n'
        "validate_imds_guard\n"
        'echo "failures=$VALIDATION_FAILURES"\n'
    )
    completed = _run_bash(script, tmp_path, FAKE_RESPONSES="200:{}", PROBE=probe)
    assert f"{verdict} {IMDS_CHECK}\n" in completed.stdout, completed.stderr
    assert f"failures={0 if verdict == 'PASS' else 1}" in completed.stdout
    docker = (tmp_path / "docker").read_text(encoding="utf-8")
    assert docker.startswith("exec ps-azure-f1-backend-1 python -c import socket")
    assert '("169.254.169.254", 80)' in docker


def test_the_rehearsal_skips_the_imds_guard_and_its_check(tmp_path: Path) -> None:
    script = (
        VM_HARNESS
        + GUARD_FAKES
        + "source deployment/azure/rehearsal/vm/rehearsal.sh\n"
        + "install_imds_guard\nvalidate_imds_guard\n"
    )
    completed = _run_bash(script, tmp_path, FAKE_RESPONSES="200:{}")
    assert completed.returncode == 0, completed.stderr
    assert "skipping propertyscope-imds-guard.service" in completed.stdout
    assert f"SKIP {IMDS_CHECK.split(' (')[0]} (rehearsal: no IMDS, no systemd)" in completed.stdout
    assert not (tmp_path / "actions").exists()  # nothing installed, no systemctl call


# --- B6 control-plane validator ------------------------------------------------------------------

DEPLOYER = "00000000-0000-0000-0000-00000000c11d"
PRODUCTION = "repo:owner@1/repo@2:environment:production"
# Answers the validator's queries by their arguments; everything else prints nothing.
FAKE_AZ = r"""#!/usr/bin/env bash
args=" $* "
case $args in
    *" identity list "*) [[ -n ${FAKE_IDENTITY:-} ]] && echo "$FAKE_IDENTITY" ;;
    *" identity federated-credential list "*) echo "$FAKE_SUBJECTS" ;;
    *" ad app federated-credential list "*) echo "$FAKE_SUBJECTS" ;;
    *" ad app credential list "*) echo "${FAKE_APP_SECRETS:-0}" ;;
    *" disk show "*) printf 'EncryptionAtRestWithPlatformKey\n%s\n' "$FAKE_DISK_ACCESS" ;;
esac
printf '%s\n' "$*" >>"$FAKE_AZ_LOG"
exit 0
"""


def _validate_data(tmp_path: Path, **environment: str) -> tuple[str, str]:
    """Runs a copy of the validator beside a stub deploy.sh; returns (report, az calls)."""
    validator = tmp_path / "azure" / "validate-data-security.sh"
    validator.parent.mkdir()
    validator.write_bytes((AZURE / "validate-data-security.sh").read_bytes())
    (validator.parent / "deploy.sh").write_bytes(b"echo 'PASS stub on-host check'\n")
    fake = tmp_path / "bin" / "az"
    fake.parent.mkdir()
    fake.write_bytes(FAKE_AZ.encode("utf-8"))
    fake.chmod(0o755)
    script = r"""
WORK=$1
PATH="$(cd "$WORK/bin" && pwd):$PATH"
export PATH FAKE_AZ_LOG="$WORK/az.log"
LOG_DIR="$WORK/out" AZURE_RESOURCE_GROUP=rg-test ACR_NAME=acr VM_NAME=vm KEY_VAULT_NAME=kv \
    bash "$WORK/azure/validate-data-security.sh" >/dev/null 2>&1 || true
"""
    defaults = {"FAKE_SUBJECTS": PRODUCTION, "FAKE_DISK_ACCESS": "DenyAll"}
    completed = _run_bash(script, tmp_path, **{**defaults, **environment})
    assert completed.returncode == 0, completed.stderr
    report = (tmp_path / "out" / "data-security.txt").read_text(encoding="utf-8")
    return report, (tmp_path / "az.log").read_text(encoding="utf-8")


def test_b6_reads_a_managed_identity_deployer_without_entra_app_calls(tmp_path: Path) -> None:
    report, calls = _validate_data(
        tmp_path, AZURE_CLIENT_ID=DEPLOYER, FAKE_IDENTITY="propertyscope-github-deployer"
    )
    kind = "managed identity propertyscope-github-deployer"
    assert (
        f"PASS GitHub Actions deploys through OIDC ({kind}, federated subject: {PRODUCTION})"
        in (report)
    )
    assert f"PASS the deployer has no client secrets ({kind}) (0)" in report
    assert f"[?clientId=='{DEPLOYER}'].name | [0]" in calls
    assert "identity federated-credential list --resource-group rg-test" in calls
    assert "--identity-name propertyscope-github-deployer" in calls
    assert not [line for line in calls.splitlines() if line.startswith("ad ")]


def test_b6_still_reads_an_app_registration_deployer(tmp_path: Path) -> None:
    report, calls = _validate_data(tmp_path, AZURE_CLIENT_ID=DEPLOYER, FAKE_APP_SECRETS="1")
    assert "PASS GitHub Actions deploys through OIDC (app registration" in report
    assert (
        "FAIL the deployer has no client secrets (app registration) (expected 0, got 1)" in report
    )
    assert f"ad app federated-credential list --id {DEPLOYER}" in calls


def test_b6_fails_without_a_production_federated_credential(tmp_path: Path) -> None:
    report, _ = _validate_data(
        tmp_path,
        AZURE_CLIENT_ID=DEPLOYER,
        FAKE_IDENTITY="propertyscope-github-deployer",
        FAKE_SUBJECTS="repo:owner@1/repo@2:environment:operations",
    )
    assert f"FAIL no federated credential for the production environment on {DEPLOYER}" in report


@pytest.mark.parametrize(
    ("access", "verdict"), [("DenyAll", "PASS"), ("AllowAll", "FAIL")], ids=["denied", "allowed"]
)
def test_b6_checks_that_the_os_disk_cannot_be_exported(
    tmp_path: Path, access: str, verdict: str
) -> None:
    report, calls = _validate_data(tmp_path, FAKE_DISK_ACCESS=access)
    assert "PASS OS disk is encrypted at rest (EncryptionAtRestWithPlatformKey)" in report
    assert f"{verdict} OS disk cannot be exported (network access policy)" in report
    assert calls.count("disk show") == 1  # both values from one call
    assert "SKIP GitHub OIDC federated credential (set AZURE_CLIENT_ID)" in report
    assert "  vm: PASS stub on-host check" in report


def test_b6_keeps_skipped_on_host_checks_in_the_report() -> None:
    validator = (AZURE / "validate-data-security.sh").read_text(encoding="utf-8")
    assert "grep -E '^(PASS|FAIL|SKIP) ' \"$OUTPUT_DIR/data-security-vm.txt\"" in validator


# --- Workflows -----------------------------------------------------------------------------------


def test_the_acme_email_reaches_the_deploy_job_only_as_a_masked_secret() -> None:
    workflows = ROOT / ".github" / "workflows"
    deploy = yaml.safe_load((workflows / "cloud-deployment.yml").read_text(encoding="utf-8"))
    env = deploy["jobs"]["deploy"]["env"]
    assert env["PROPERTYSCOPE_ACME_EMAIL"] == "${{ secrets.PROPERTYSCOPE_ACME_EMAIL }}"
    for workflow in workflows.glob("*.yml"):
        assert "vars.PROPERTYSCOPE_ACME_EMAIL" not in workflow.read_text(encoding="utf-8")
    readme = (AZURE / "README.md").read_text(encoding="utf-8")
    assert "`production` *environment* secret `PROPERTYSCOPE_ACME_EMAIL`" in readme
    assert "| `PROPERTYSCOPE_ACME_EMAIL` |" not in readme  # not a repository variable


# --- Code owners -------------------------------------------------------------------------------


def test_codeowners_cover_only_the_sensitive_cloud_setup() -> None:
    lines = (ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8").splitlines()
    rules = dict(line.split() for line in lines if line.strip() and not line.startswith("#"))
    assert rules == {
        "/deployment/azure/": "@MattShelton04",
        "/.github/workflows/cloud-deployment.yml": "@MattShelton04",
        "/.github/workflows/cloud-auto-deallocate.yml": "@MattShelton04",
        "/docker-compose.azure.yml": "@MattShelton04",
        "/docker-compose.azure-ai.yml": "@MattShelton04",
        "/.github/CODEOWNERS": "@MattShelton04",
    }
    for path in rules:
        assert (ROOT / path.strip("/")).exists(), path
