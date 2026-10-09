"""`dev.py cloud ...`: a thin, cross-platform wrapper around deployment/azure/deploy.sh (ADR-048).

The Azure workflow lives in one Bash script so a laptop and GitHub Actions run exactly the same
steps. This module only finds a suitable Bash (Git Bash on Windows, never the WSL launcher in
System32), forwards the arguments and offers ``--dry-run``.

It also provides ``python -m scripts.devtools.cloud host-env``, which the VM operations script
calls to render the systemd environment file for the optional cloud AI tier. That reuses the
local host-runtime preparation (``host_runtime.prepare_environment``) so the cloud AI processes
get the same catalogues, corpora and capability flags as ``dev.py ai start --mode combined``.
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

if __package__ in {None, ""}:  # pragma: no cover - direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.devtools.config import REPOSITORY_ROOT
from scripts.devtools.runtime_settings import AI_CAPABILITY_MODES

DEPLOY_SCRIPT = REPOSITORY_ROOT / "deployment" / "azure" / "deploy.sh"
SIMPLE_ACTIONS = (
    "provision",
    "secrets",
    "push",
    "deploy",
    "status",
    "outputs",
    "all",
)
# Settings the host AI processes need. Provider credentials never enter the environment file:
# systemd passes the key as a credential file (LoadCredential, OPENAI_API_KEY_FILE).
HOST_ENV_PREFIXES = ("AI_MODE_", "MCP_", "RAG_", "MULTI_AGENT_", "OPENAI_", "GEMINI_")
HOST_ENV_EXCLUDED = frozenset({"OPENAI_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY_FILE"})
MULTI_AGENT_DEFAULT_PORT = "5013"


def add_cloud_commands(root: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``cloud`` command group on the dev.py parser."""
    cloud = root.add_parser(
        "cloud",
        help="Provision, deploy and validate the Azure environment (deployment/azure/deploy.sh)",
    )
    commands = cloud.add_subparsers(dest="action", required=True)
    help_texts = {
        "provision": "Create the resource group and apply the Bicep template",
        "secrets": "Create missing Key Vault secrets (one-time; never overwrites)",
        "push": "Build every enabled image and push it to ACR tagged with the commit SHA",
        "deploy": "Converge the VM through az vm run-command (pull, compose up --wait, seed)",
        "status": "Show container and host AI state on the VM",
        "outputs": "Print the Bicep outputs (FQDN, ACR, VM, Key Vault)",
        "all": "provision, push, deploy and smoke in order",
    }
    for action in SIMPLE_ACTIONS:
        _add_dry_run(commands.add_parser(action, help=help_texts[action]))
    smoke = commands.add_parser("smoke", help="Run scripts/cloud_smoke.py against the public URL")
    smoke.add_argument("--output-dir", type=Path, default=None)
    smoke.add_argument("--expect-ai", action="store_true", help="Require the AI tier to be on")
    _add_dry_run(smoke)
    ai = commands.add_parser("ai", help="Turn the systemd host AI tier on or off (bonus tiers)")
    ai.add_argument("state", choices=("on", "off"))
    _add_dry_run(ai)
    logs = commands.add_parser("logs", help="Recent Compose or host AI logs from the VM")
    logs.add_argument("service", nargs="?", default="", help="Compose service or AI unit name")
    logs.add_argument("--lines", type=int, default=80)
    _add_dry_run(logs)
    validate = commands.add_parser("validate", help="Run a bonus security validation script")
    validate.add_argument("control", choices=("endpoint", "data"))
    _add_dry_run(validate)


def _add_dry_run(command: argparse.ArgumentParser) -> None:
    command.add_argument(
        "--dry-run",
        action="store_true",
        help="Print every mutating Azure/Docker command instead of running it",
    )


def deploy_arguments(arguments: argparse.Namespace) -> list[str]:
    """Translate parsed ``dev.py cloud`` arguments into deploy.sh arguments."""
    result = ["--dry-run"] if getattr(arguments, "dry_run", False) else []
    action = arguments.action
    if action in SIMPLE_ACTIONS:
        result.append(action)
    elif action == "smoke":
        result.append("smoke")
        if arguments.output_dir is not None:
            result += ["--output-dir", str(arguments.output_dir)]
        if arguments.expect_ai:
            result.append("--expect-ai")
    elif action == "ai":
        result += ["ai", arguments.state]
    elif action == "logs":
        if arguments.lines < 1:
            raise RuntimeError("--lines must be a positive number")
        result += ["logs", arguments.service or "", str(arguments.lines)]
    elif action == "validate":
        result.append(f"validate-{arguments.control}")
    else:  # pragma: no cover - argparse restricts the choices
        raise RuntimeError(f"unknown cloud action: {action}")
    return result


def bash_executable(
    *,
    environment: Mapping[str, str] | None = None,
    platform: str = os.name,
    which: Callable[[str], str | None] = shutil.which,
    is_file: Callable[[Path], bool] = Path.is_file,
) -> str:
    """Find a POSIX Bash. On Windows prefer Git Bash; System32\\bash.exe is the WSL launcher."""
    values = os.environ if environment is None else environment
    override = values.get("PROPERTYSCOPE_BASH", "").strip()
    if override:
        return override
    if platform != "nt":
        found = which("bash")
        if found is None:
            raise RuntimeError("bash is required for `dev.py cloud`; install it and retry")
        return found
    candidates: list[Path] = []
    git = which("git")
    if git is not None:
        # <Git>/cmd/git.exe or <Git>/bin/git.exe -> <Git>/bin/bash.exe
        candidates.append(Path(git).resolve().parent.parent / "bin" / "bash.exe")
    for variable in ("ProgramFiles", "ProgramW6432", "LOCALAPPDATA"):
        base = values.get(variable)
        if base:
            suffix = ("Programs", "Git") if variable == "LOCALAPPDATA" else ("Git",)
            candidates.append(Path(base, *suffix, "bin", "bash.exe"))
    for candidate in candidates:
        if is_file(candidate):
            return str(candidate)
    found = which("bash")
    if found is not None and "system32" not in found.lower():
        return found
    raise RuntimeError(
        "Git Bash is required on Windows for `dev.py cloud` (https://git-scm.com/download/win), "
        "or set PROPERTYSCOPE_BASH to a bash.exe"
    )


def build_command(arguments: argparse.Namespace, *, bash: str | None = None) -> tuple[str, ...]:
    """Return the full command line that runs deploy.sh for these arguments."""
    script = DEPLOY_SCRIPT.relative_to(REPOSITORY_ROOT).as_posix()
    return (bash or bash_executable(), script, *deploy_arguments(arguments))


def run(arguments: argparse.Namespace) -> int:
    """Execute one ``dev.py cloud`` action and return deploy.sh's exit status."""
    command = build_command(arguments)
    print(f"> {shlex.join(command)}", flush=True)
    completed = subprocess.run(command, cwd=REPOSITORY_ROOT, check=False)
    return completed.returncode


# --- host-env: the systemd environment for the optional cloud AI tier ------------------------


def host_environment(environment: Mapping[str, str], *, mode: str) -> dict[str, str]:
    """Prepare host AI settings on the VM exactly as the local launcher does, then filter them."""
    from scripts.devtools import host_runtime

    for variable in ("AI_MODE_SERVICE_TOKEN", "MCP_SERVICE_TOKEN", "RAG_SERVICE_TOKEN"):
        if not environment.get(variable):
            raise RuntimeError(f"{variable} must come from Key Vault before rendering host-env")
    values = dict(environment)
    # The AI tier is local to the VM: same process model, loopback MCP/RAG, and AI-mode reached
    # by the containers through the Docker host gateway (ADR-046, ADR-048).
    values["AI_MODE_ENVIRONMENT"] = "local"
    values.setdefault("MULTI_AGENT_PORT", MULTI_AGENT_DEFAULT_PORT)
    prepared = host_runtime.prepare_environment(values, mode=mode)
    return {
        key: value
        for key, value in sorted(prepared.items())
        if key.startswith(HOST_ENV_PREFIXES) and key not in HOST_ENV_EXCLUDED
    }


def render_environment_file(values: Mapping[str, str]) -> str:
    """Render a file that systemd (EnvironmentFile) and Bash (``.``) both read identically.

    Values are double-quoted. Characters the two parsers treat differently are rejected rather
    than escaped; tokens, ports, URLs and paths never contain them.
    """
    lines = ["# Rendered by scripts/devtools/cloud.py host-env; root-only (0600)."]
    for key, value in values.items():
        if any(character in value for character in '\n\r"\\$`'):
            raise RuntimeError(f"{key} contains a character the environment file cannot carry")
        lines.append(f'{key}="{value}"')
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for ``python -m scripts.devtools.cloud host-env`` (runs on the VM)."""
    parser = argparse.ArgumentParser(description="Cloud AI host environment renderer")
    commands = parser.add_subparsers(dest="command", required=True)
    host_env = commands.add_parser("host-env", help="Print the systemd environment file")
    host_env.add_argument("--mode", choices=AI_CAPABILITY_MODES, default="combined")
    arguments = parser.parse_args(argv)
    try:
        values = host_environment(os.environ, mode=arguments.mode)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    sys.stdout.write(render_environment_file(values))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
