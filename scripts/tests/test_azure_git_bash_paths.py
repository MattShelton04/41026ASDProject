"""deploy.sh and its validators hand Azure resource IDs to az unchanged under Git Bash.

Git Bash (MSYS) rewrites arguments that look like POSIX paths when it starts a native Windows
program, so ``--ids /subscriptions/...`` reached az as ``C:/Program Files/Git/subscriptions/...``.
The fake az here is a bash script that hands every call carrying an ID or a file to the test's
Python, so on Windows the same rewrite happens at that boundary unless the caller turned it off; on
Linux nothing is rewritten and the tests check that the guard is in place. Other calls stay in bash
(starting Python for each is too slow under the gate's parallel load). No Azure, Docker or network.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from scripts.tests.test_azure_deployment import AZURE, _run_bash
from scripts.tests.test_azure_rehearsal_shell import _deploy_bash

SCOPE = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-test"
DISK = f"{SCOPE}/providers/Microsoft.Compute/disks/os-disk"
FAKE_AZ = """\
import json
import os
import sys
from pathlib import Path

DISK = {disk!r}
args = sys.argv[1:]
with (Path(__file__).parent / "az-calls.jsonl").open("a", encoding="utf-8") as log:
    record = {{"argv": args, "no_pathconv": os.environ.get("MSYS_NO_PATHCONV")}}
    log.write(json.dumps(record) + "\\n")
if "storageProfile.osDisk.managedDisk.id" in args:
    print(DISK)
elif args[:2] == ["disk", "show"]:
    print("EncryptionAtRestWithPlatformKey" if args[args.index("--ids") + 1] == DISK else "")
for index, arg in enumerate(args):
    # File arguments must name a file this native program can open.
    if arg == "--file":
        print("file:" + Path(args[index + 1]).read_text(encoding="utf-8"))
    elif arg.startswith("@"):
        print("script:" + Path(arg[1:]).read_text(encoding="utf-8"))
"""
# Every call logs MSYS_NO_PATHCONV; calls with an ID or a file argument go to the native Python.
FAKE_AZ_BASH = r"""#!/usr/bin/env bash
printf '%s %s %s\n' "${MSYS_NO_PATHCONV:-unset}" "${1:-}" "${2:-}" >>"$FAKE_AZ_LOG"
case " $* " in
    *" --ids "* | *" --scope "* | *" --file "* | *" @"* | *managedDisk.id*)
        exec "$FAKE_PYTHON" -I -S "$FAKE_AZ_SCRIPT" "$@"
        ;;
esac
[[ "${1:-} ${2:-}" != "account show" ]] # deploy.sh vm-validate-data stops at the sign-in check
"""
# Puts the fake az first on PATH (as a POSIX path: C:/... would split PATH at the drive colon).
FAKE_AZ_ON_PATH = r"""
PATH="$(cd "$WORK/bin" && pwd):$PATH"
export PATH
"""


def _fake_az(tmp_path: Path) -> dict[str, str]:
    script = tmp_path / "az.py"
    script.write_text(FAKE_AZ.format(disk=DISK), encoding="utf-8")
    fake = tmp_path / "bin" / "az"
    fake.parent.mkdir()
    fake.write_bytes(FAKE_AZ_BASH.encode("utf-8"))
    fake.chmod(0o755)
    return {
        "FAKE_PYTHON": Path(sys.executable).as_posix(),
        "FAKE_AZ_SCRIPT": script.as_posix(),
        "FAKE_AZ_LOG": (tmp_path / "az-env.log").as_posix(),
    }


def _calls(tmp_path: Path) -> list[dict[str, Any]]:
    """The calls the native Python saw: those with an ID or a file argument."""
    log = tmp_path / "az-calls.jsonl"
    lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return [json.loads(line) for line in lines]


def _guards(tmp_path: Path) -> list[str]:
    """MSYS_NO_PATHCONV as every az call saw it ("unset" when absent)."""
    lines = (tmp_path / "az-env.log").read_text(encoding="utf-8").splitlines()
    return [line.split(" ", 1)[0] for line in lines]


def test_deploy_script_passes_resource_ids_and_file_arguments_to_az_intact(
    tmp_path: Path,
) -> None:
    script = (
        FAKE_AZ_ON_PATH
        + r"""
az role assignment create --assignee-object-id 1 --role Reader --scope "$SCOPE" --output none
az_query disk show --ids "$DISK" --query encryption.type --output tsv
printf 'from-a-file' >"$WORK/payload"
az keyvault secret set --vault-name kv --name n --file "$(native_path "$WORK/payload")"
az vm run-command invoke --scripts "@$(native_path "$WORK/payload")"
"""
    )
    completed = _deploy_bash(script, tmp_path, **_fake_az(tmp_path), DISK=DISK, SCOPE=SCOPE)

    assert completed.returncode == 0, completed.stderr
    assert "EncryptionAtRestWithPlatformKey" in completed.stdout
    assert "file:from-a-file" in completed.stdout
    assert "script:from-a-file" in completed.stdout
    calls = _calls(tmp_path)
    assert len(calls) == 4
    assert all(call["no_pathconv"] == "1" for call in calls), calls
    assert calls[0]["argv"][calls[0]["argv"].index("--scope") + 1] == SCOPE
    assert calls[1]["argv"][calls[1]["argv"].index("--ids") + 1] == DISK


def test_data_validator_reads_the_os_disk_by_its_resource_id(tmp_path: Path) -> None:
    # The validator runs standalone (deploy.sh's az() does not reach a child script). A copy runs
    # beside a stub deploy.sh, so its on-host half fails at once instead of starting deploy.sh.
    validator = tmp_path / "azure" / "validate-data-security.sh"
    validator.parent.mkdir()
    validator.write_bytes((AZURE / "validate-data-security.sh").read_bytes())
    (validator.parent / "deploy.sh").write_bytes(b"exit 1\n")
    script = (
        "WORK=$1\n"
        + FAKE_AZ_ON_PATH
        + r"""
LOG_DIR="$WORK/out" AZURE_RESOURCE_GROUP=rg-test ACR_NAME=acr VM_NAME=vm KEY_VAULT_NAME=kv \
    bash "$WORK/azure/validate-data-security.sh" >/dev/null 2>&1 || true
"""
    )
    completed = _run_bash(script, tmp_path, **_fake_az(tmp_path))

    assert completed.returncode == 0, completed.stderr
    report = (tmp_path / "out" / "data-security.txt").read_text(encoding="utf-8")
    assert "PASS OS disk is encrypted at rest (EncryptionAtRestWithPlatformKey)" in report
    disk_calls = [call for call in _calls(tmp_path) if call["argv"][:2] == ["disk", "show"]]
    assert [call["argv"][call["argv"].index("--ids") + 1] for call in disk_calls] == [DISK]
    guards = _guards(tmp_path)
    assert len(guards) > 10
    assert set(guards) == {"1"}, guards


def test_endpoint_validator_skips_the_nsg_check_without_an_az_program() -> None:
    # Its az() wrapper is a function, so `command -v az` would always succeed.
    script = (AZURE / "validate-endpoint-security.sh").read_text(encoding="utf-8")
    assert "az() { MSYS_NO_PATHCONV=1" in script
    assert "if type -P az >/dev/null 2>&1 &&" in script
    assert "command -v az" not in script
