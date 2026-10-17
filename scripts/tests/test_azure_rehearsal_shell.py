"""deploy.sh smoke identity, image reuse and rehearsal mode, and the VM rehearsal hook.

Shell behaviour runs only where a POSIX bash is available; no Azure, Docker or network.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from scripts.tests.test_azure_deployment import AZURE, ROOT, VM_HARNESS, _bash, _run_bash

COMMIT = "3f2a9c1d8e7b6a5f4e3d2c1b0a9f8e7d6c5b4a39"
REHEARSAL_DIRECTORY = AZURE / "rehearsal"
# Sources deploy.sh (functions only) and configures it the way `main` does.
DEPLOY_HARNESS = r"""
set -euo pipefail
WORK=$1
source deployment/azure/deploy.sh
configure
"""
REHEARSAL_ENVIRONMENT = {
    "PROPERTYSCOPE_REHEARSAL": "true",
    "PROPERTYSCOPE_REHEARSAL_VM": "ps-azure-rehearsal-vm",
    "PROPERTYSCOPE_PUSH_REGISTRY": "127.0.0.1:5000",
}
# Azure outputs already known, so load_outputs never asks az.
KNOWN_OUTPUTS = {
    "ACR_LOGIN_SERVER": "psg20acr.azurecr.io",
    "ACR_NAME": "psg20acr",
    "VM_NAME": "propertyscope-prod-vm",
    "KEY_VAULT_NAME": "property-kv-example",
    "PUBLIC_FQDN": "demo.australiaeast.cloudapp.azure.com",
}


def _deploy_bash(
    script: str, tmp_path: Path, **environment: str
) -> subprocess.CompletedProcess[str]:
    base = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("PROPERTYSCOPE_", "AZURE_", "ACR_")) and key != "IMAGE_TAG"
    }
    harness = tmp_path / "harness.sh"
    harness.write_bytes((DEPLOY_HARNESS + script).encode("utf-8"))
    return subprocess.run(  # noqa: S603 - fixed bash and a harness written by this test
        [_bash(), harness.as_posix(), tmp_path.as_posix()],
        cwd=ROOT,
        env={
            **base,
            "PROPERTYSCOPE_CLOUD_LOG_DIR": (tmp_path / "cloud").as_posix(),
            "AZURE_ENV_FILE": (tmp_path / "missing.env").as_posix(),
            **environment,
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


SMOKE_CAPTURE = r"""
run() { printf '%s\n' "$@" >"$WORK/argv"; }
python_runner() { printf 'python'; }
if [[ -n ${TAG_FILE:-} ]]; then printf '%s\n' "$TAG_FILE" >"$LOG_DIR/image-tag.txt"; fi
echo 'PROPERTYSCOPE_EXIT=0' >"$LOG_DIR/vm-deploy.log"
cmd_smoke --insecure
"""


@pytest.mark.parametrize(
    ("environment", "expected", "absent"),
    [
        (
            # The workflow: IMAGE_TAG and PROPERTYSCOPE_DEPLOY_SHA set, outputs from Azure.
            {**KNOWN_OUTPUTS, "IMAGE_TAG": COMMIT, "PROPERTYSCOPE_DEPLOY_SHA": COMMIT},
            [
                "--base-url\nhttps://demo.australiaeast.cloudapp.azure.com\n",
                f"--image-tag\n{COMMIT}\n",
                f"--commit-sha\n{COMMIT}\n",
                "--registry\npsg20acr.azurecr.io\n",
                "--vm-log\n",
                "--insecure\n",
            ],
            [],
        ),
        (
            # A laptop after `deploy.sh push`: the recorded tag; a non-SHA tag names no commit.
            {**KNOWN_OUTPUTS, "TAG_FILE": "0000000"},
            ["--image-tag\n0000000\n"],
            ["--commit-sha"],
        ),
        (
            # The rehearsal: stand-in names, never an Azure lookup.
            {
                **REHEARSAL_ENVIRONMENT,
                **KNOWN_OUTPUTS,
                "ACR_LOGIN_SERVER": "ps-rehearsal-registry:5000",
                "PUBLIC_FQDN": "localhost",
                "TAG_FILE": f"{COMMIT}-dirty",
            },
            [
                "--base-url\nhttps://localhost\n",
                f"--image-tag\n{COMMIT}-dirty\n",
                f"--commit-sha\n{COMMIT}\n",
                "--registry\nps-rehearsal-registry:5000\n",
            ],
            [],
        ),
    ],
    ids=["workflow", "laptop-recorded-tag", "rehearsal"],
)
def test_smoke_passes_the_deployment_identity_to_cloud_smoke(
    tmp_path: Path, environment: dict[str, str], expected: list[str], absent: list[str]
) -> None:
    completed = _deploy_bash(SMOKE_CAPTURE, tmp_path, **environment)
    assert completed.returncode == 0, completed.stderr
    argv = (tmp_path / "argv").read_text(encoding="utf-8")
    assert argv.startswith("python\nscripts/cloud_smoke.py\n")
    for fragment in expected:
        assert fragment in argv, (fragment, argv)
    for fragment in absent:
        assert fragment not in argv


def test_rehearsal_refuses_every_az_call_and_needs_its_stand_ins(tmp_path: Path) -> None:
    script = r"""
if (az account show) 2>"$WORK/az.err"; then echo az-ran; else echo az-refused; fi
if bash -c 'az account show' 2>/dev/null; then echo child-ran; else echo "child=$?"; fi
if (unset ACR_LOGIN_SERVER; load_outputs) 2>"$WORK/outputs.err"; then
    echo outputs-ran
else
    echo outputs-refused
fi
"""
    completed = _deploy_bash(script, tmp_path, **REHEARSAL_ENVIRONMENT)
    assert completed.returncode == 0, completed.stderr
    assert "az-refused" in completed.stdout
    assert "child=97" in completed.stdout  # child scripts find the refusing az stub first
    assert "never calls Azure" in (tmp_path / "az.err").read_text(encoding="utf-8")
    assert "outputs-refused" in completed.stdout
    assert "names its stand-ins" in (tmp_path / "outputs.err").read_text(encoding="utf-8")

    for name, value in (
        ("PROPERTYSCOPE_PUSH_REGISTRY", "psg20acr.azurecr.io"),
        ("PROPERTYSCOPE_REHEARSAL_VM", "bad name"),
        ("PROPERTYSCOPE_REHEARSAL", "yes"),
    ):
        bad = _deploy_bash("echo configured\n", tmp_path, **{**REHEARSAL_ENVIRONMENT, name: value})
        assert bad.returncode != 0 and "configured" not in bad.stdout, name


REUSE_HARNESS = r"""
docker() {
    if [[ $1 == image && $2 == inspect ]]; then
        case ${*: -1} in
            propertyscope/a:rehearsal) echo "sha256:${ID_A:-aaa}" ;;
            propertyscope/b:rehearsal) echo sha256:bbb ;;
            *) return 1 ;;
        esac
    fi
}
check() {
    if (verify_reusable_images "$@") 2>"$WORK/err"; then
        echo ok
    else
        echo "refused: $(cat "$WORK/err")"
    fi
}
"""


def test_push_reuses_only_images_it_built_for_the_same_clean_commit(tmp_path: Path) -> None:
    script = REUSE_HARNESS + (
        f"check {COMMIT} rehearsal a b\n"
        f"record_build_manifest {COMMIT} rehearsal a b\n"
        f"check {COMMIT} rehearsal a b\n"
        f"ID_A=changed check {COMMIT} rehearsal a b\n"
        f"record_build_manifest {COMMIT}-dirty rehearsal a b\n"
        f"check {COMMIT}-dirty rehearsal a b\n"
    )
    completed = _deploy_bash(
        script, tmp_path, PROPERTYSCOPE_BUILD_MANIFEST_DIR=(tmp_path / "builds").as_posix()
    )
    assert completed.returncode == 0, completed.stderr
    lines = completed.stdout.splitlines()
    assert lines[0].startswith("refused:") and "nothing was built" in lines[0]
    assert lines[1] == "ok"
    assert lines[2].startswith("refused:") and "is not the image built" in lines[2]
    assert lines[3].startswith("refused:") and "committed tree" in lines[3]
    manifest = (tmp_path / "builds" / f"{COMMIT}.rehearsal.images").read_text(encoding="utf-8")
    assert manifest == "a sha256:aaa\nb sha256:bbb\n"


def test_push_builds_under_another_tag_without_touching_dev_images(tmp_path: Path) -> None:
    script = r"""
run() { printf '%s\n' "$*" >>"$WORK/commands"; }
build_images rehearsal shared-frontend f1-backend
build_images dev shared-frontend
"""
    completed = _deploy_bash(script, tmp_path)
    assert completed.returncode == 0, completed.stderr
    commands = (tmp_path / "commands").read_text(encoding="utf-8").splitlines()
    assert commands[0].startswith("compose_base -f ")
    assert commands[0].endswith("build-tag.compose.yml build --pull shared-frontend f1-backend")
    assert commands[1] == "compose_base build --pull shared-frontend"
    override = yaml.safe_load(
        (tmp_path / "cloud" / "build-tag.compose.yml").read_text(encoding="utf-8")
    )
    assert override == {
        "services": {
            "shared-frontend": {"image": "propertyscope/shared-frontend:rehearsal"},
            "f1-backend": {"image": "propertyscope/f1-backend:rehearsal"},
        }
    }


VM_IMAGES_SCRIPT = r"""
unset -f jq
compose() {
    case "$*" in
        *--format*) printf '%s\n' 'f1-backend reg:5000/propertyscope/f1-backend:abc' \
            'shared-edge-proxy reg:5000/propertyscope/mirror/caddy:2.10.2-alpine' ;;
        *) printf 'id1\nid2\n' ;;
    esac
}
docker() {
    if [[ ${*: -1} == *f1-backend* ]]; then
        printf '%s\n' "other/repo@sha256:$B64" "reg:5000/propertyscope/f1-backend@sha256:$A64"
    fi
}
summary deploy
"""


@pytest.mark.skipif(shutil.which("jq") is None, reason="needs jq, like the VM")
def test_vm_reports_running_images_on_their_own_line_before_the_result(tmp_path: Path) -> None:
    completed = _run_bash(
        VM_HARNESS + VM_IMAGES_SCRIPT, tmp_path, FAKE_RESPONSES="200:{}", A64="a" * 64, B64="b" * 64
    )
    assert completed.returncode == 0, completed.stderr
    lines = completed.stdout.splitlines()
    images = next(i for i, line in enumerate(lines) if line.startswith("PROPERTYSCOPE_IMAGES="))
    result = next(i for i, line in enumerate(lines) if line.startswith("PROPERTYSCOPE_RESULT="))
    # run-command keeps only the output's tail: the result line must come last.
    assert images < result
    assert json.loads(lines[images].split("=", 1)[1]) == {
        "f1-backend": "reg:5000/propertyscope/f1-backend:abc@sha256:" + "a" * 64,
        "shared-edge-proxy": "reg:5000/propertyscope/mirror/caddy:2.10.2-alpine",
    }
    assert json.loads(lines[result].split("=", 1)[1])["containers_running"] == 2


def test_the_rehearsal_hook_is_never_installed_on_an_azure_vm() -> None:
    vm = (AZURE / "vm" / "propertyscope-vm.sh").read_text(encoding="utf-8")
    assert "readonly REHEARSAL_HOOK=/etc/propertyscope/rehearsal.sh" in vm
    # Sourced after every function is defined and before main runs.
    assert vm.index('. "$REHEARSAL_HOOK"') > vm.index("validate_data() {")
    assert vm.index('. "$REHEARSAL_HOOK"') < vm.index('    main "$@"')
    assert "rehearsal" not in (AZURE / "cloud-init.yaml").read_text(encoding="utf-8")
    dockerfile = (REHEARSAL_DIRECTORY / "vm" / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY --chmod=0644 rehearsal.sh /etc/propertyscope/rehearsal.sh" in dockerfile
    shim = (REHEARSAL_DIRECTORY / "vm" / "rehearsal.sh").read_text(encoding="utf-8")
    overridden = set(re.findall(r"^([a-z_]+)\(\) \{", shim, re.M))
    # Only the Azure-only steps are replaced; everything else is the real VM script.
    assert overridden == {"imds_token", "kv_get", "acr_login", "acr_logout", "verify_deployment"}


SHIM_SCRIPT = r"""
source deployment/azure/rehearsal/vm/rehearsal.sh
REHEARSAL_KEY_VAULT="$WORK/kv"
echo "value=$(kv_get internal-token)"
kv_get openai-api-key optional; echo "optional=$?"
(kv_get runner-token) 2>"$WORK/err"; echo "required=$?"
(kv_get "../etc") 2>/dev/null; echo "traversal=$?"
echo "imds=$(imds_token https://vault.azure.net)"
if declare -F azure_verify_deployment >/dev/null; then echo wrapped; fi
"""


def test_the_rehearsal_shim_reads_the_stand_in_key_vault(tmp_path: Path) -> None:
    (tmp_path / "kv").mkdir()
    (tmp_path / "kv" / "internal-token").write_text("t" * 64, encoding="ascii")
    completed = _run_bash(VM_HARNESS + SHIM_SCRIPT, tmp_path, FAKE_RESPONSES="200:{}")
    assert completed.returncode == 0, completed.stderr
    assert f"value={'t' * 64}" in completed.stdout
    assert "optional=3" in completed.stdout
    assert "required=1" in completed.stdout
    assert "rehearsal Key Vault has no secret" in (tmp_path / "err").read_text(encoding="utf-8")
    assert "traversal=1" in completed.stdout
    assert "imds=rehearsal-without-imds" in completed.stdout
    assert "wrapped" in completed.stdout


def _expect_pattern(script: str, description: str) -> re.Pattern[str]:
    match = re.search(rf'expect "{re.escape(description)}" "[^"]*" \'([^\']+)\'', script)
    assert match is not None, description
    return re.compile(match.group(1))


def test_endpoint_checks_never_pass_on_a_dead_edge() -> None:
    script = (AZURE / "validate-endpoint-security.sh").read_text(encoding="utf-8")
    # Found by the local rehearsal: "000" (no answer at all) used to pass both checks.
    credentials = _expect_pattern(script, "valid operator credentials pass the edge")
    for code in ("200", "302", "404", "405", "503"):
        assert credentials.fullmatch(code), code
    for code in ("000", "401", "403"):
        assert not credentials.search(code), code
    legacy = _expect_pattern(script, "TLS 1.1 and older are refused while TLS 1.2+ is served")
    assert legacy.search("tls<=1.1:000 tls>=1.2:200")
    assert not legacy.search("tls<=1.1:000 tls>=1.2:000")


def test_endpoint_script_trusts_a_private_ca_only_for_the_http_level_checks() -> None:
    script = (AZURE / "validate-endpoint-security.sh").read_text(encoding="utf-8")
    trust_check = script[script.index("# --- TLS") : script.index('result PASS "HTTPS serves')]
    assert "env -u CURL_CA_BUNDLE -u SSL_CERT_FILE curl" in trust_check
    assert "TLS_OPTIONS" not in trust_check and "edge_curl" not in trust_check
    # Every other HTTPS request goes through the CA options.
    https_calls = [
        line
        for line in script.splitlines()
        if "$BASE" in line and "curl" in line and "env -u CURL_CA_BUNDLE" not in line
    ]
    assert https_calls
    for line in https_calls:
        assert "edge_curl" in line or "TLS_OPTIONS" in line, line


def test_rehearsal_runs_the_payload_as_a_file_without_stdin() -> None:
    deploy = (AZURE / "deploy.sh").read_text(encoding="utf-8")
    # A payload fed on stdin would be read by `compose exec` inside the VM script, and its
    # PROPERTYSCOPE_EXIT line lost (found by the local rehearsal).
    assert "bash -s" not in deploy
    assert "bash /var/lib/propertyscope-rehearsal/run-command/script.sh 2>&1 </dev/null" in deploy
