"""`dev.py cloud rehearse`: a cloud-like local rehearsal of the Azure deployment (ADR-048).

It runs the real deployment path on this machine, as close to the Azure VM flow as Docker allows,
and needs no Azure account:

1. ``prepare``: a scratch directory under ``.propertyscope-runtime/cloud-rehearsal/``, the VM's
   ``/etc/docker/daemon.json`` taken from ``deployment/azure/cloud-init.yaml``, and throwaway random
   values for every Key Vault secret (a directory standing in for Key Vault; never printed).
2. ``infrastructure``: Compose project ``ps-azure-rehearsal`` (deployment/azure/rehearsal/): a
   ``registry:2`` container (``ps-rehearsal-registry``) in place of ACR and a Docker-in-Docker
   container in place of the VM, publishing only 80/443 on the host loopback.
3. ``push``, ``deploy``, ``smoke``, ``endpoint_security``, ``data_security``, ``status``: the same
   ``deployment/azure/deploy.sh`` subcommands the workflow runs, with ``PROPERTYSCOPE_REHEARSAL``
   set. ``push`` builds under ``propertyscope/<service>:rehearsal`` (the developer's ``:dev`` images
   stay untouched) and pushes ``:<git sha>`` plus the Caddy and PostGIS mirrors. ``deploy`` runs the
   exact run-command payload in the rehearsal VM, so ``propertyscope-vm.sh`` renders the secrets,
   pulls from the registry, starts ``docker-compose.azure.yml`` (AI off) as project ``ps-azure``,
   and reports how many Feature 1 releases are accepted (none: production purges the seeded
   demonstration baseline).
4. ``ai_overlay_config``: ``docker compose config`` of the AI overlay inside the VM, to prove the
   AI-mode and Multi-Agent token wiring renders. No AI service is started.
5. ``report`` and ``review``: ``scripts/cloud_deployment_report.py`` and the deterministic Cloud
   Deployment Report Review over a scratch evidence tree laid out like the workflow artifacts.
6. ``teardown`` (unless ``--keep``): ``down --volumes`` on ``ps-azure-rehearsal`` only, then the
   local registry tags and the generated secrets are removed.

It does NOT prove anything about Azure itself: ACR authentication and the managed-identity token
exchange, Key Vault and IMDS, the NSG, public DNS and the Let's Encrypt certificate, OIDC sign-in,
Bicep deployment, cloud-init, systemd and the VM size. deployment/azure/README.md
("Local rehearsal") lists them.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from scripts.devtools.config import REPOSITORY_ROOT

PROJECT = "ps-azure-rehearsal"
REGISTRY_CONTAINER = "ps-rehearsal-registry"
VM_CONTAINER = "ps-azure-rehearsal-vm"
COMPOSE_FILE = REPOSITORY_ROOT / "deployment" / "azure" / "rehearsal" / "compose.yml"
CLOUD_INIT = REPOSITORY_ROOT / "deployment" / "azure" / "cloud-init.yaml"
DEPLOY_SCRIPT = "deployment/azure/deploy.sh"
DEFAULT_OUTPUT = REPOSITORY_ROOT / ".propertyscope-runtime" / "cloud-rehearsal"
# The rehearsal VM pulls by the registry's container name; the host pushes to its loopback port.
VM_REGISTRY = f"{REGISTRY_CONTAINER}:5000"
REGISTRY_PORT = 5000
PUBLIC_HOST = "localhost"
BUILD_TAG = "rehearsal"
EDGE_PORTS = (80, 443)
VM_COMPOSE_PROJECT = "ps-azure"
# deploy.sh REQUIRED_SECRETS and AI_SECRETS: every name `deploy.sh secrets` creates.
KEY_VAULT_SECRETS = (
    "internal-token",
    "runner-token",
    "f1-postgres-password",
    "f4-postgres-password",
    "edge-basic-auth-password",
    "edge-site-password",
    "ai-mode-service-token",
    "mcp-service-token",
    "rag-service-token",
    "multi-agent-service-token",
)
# A Key Vault secret name and a Compose secret mapping, never values.
EDGE_PASSWORD_SECRET = "edge-basic-auth-password"  # pragma: allowlist secret  # noqa: S105 - name
SITE_PASSWORD_SECRET = "edge-site-password"  # pragma: allowlist secret  # noqa: S105 - name
MULTI_AGENT_SECRET_ENV = "=".join(("MULTI_AGENT_SERVICE_TOKEN", "multi_agent_service_token"))
# Backends the AI overlay hands the Multi-Agent token (docker-compose.azure-ai.yml).
MULTI_AGENT_BACKENDS = (
    "f1-backend",
    "f2-backend",
    "f3-backend",
    "f4-backend",
    "f5-backend",
)
NOTICE = (
    "LOCAL REHEARSAL - this is NOT the Azure deployment. It ran on a developer machine with a "
    "local registry and a Docker-in-Docker VM (`dev.py cloud rehearse`); nothing here proves "
    "ACR, Key Vault, IMDS, the NSG, public DNS, Let's Encrypt or OIDC."
)
# Results a local rehearsal cannot produce: they are reported, not counted as failures.
REACHABLE_PORT = re.compile(r"^port ([0-9]+) is reachable from the internet")
ENDPOINT_SCRIPT = REPOSITORY_ROOT / "deployment" / "azure" / "validate-endpoint-security.sh"
VM_IMAGE = "propertyscope-rehearsal/vm:28.5.1"
REHEARSAL_NETWORK = f"{PROJECT}_rehearsal"
EDGE_CONTAINER = f"{VM_COMPOSE_PROJECT}-shared-edge-proxy-1"
CADDY_CA = "/data/caddy/pki/authorities/local"
EXPECTED_ENDPOINT_FAILURES = (
    # Caddy's internal CA for localhost is not publicly trusted (Azure uses Let's Encrypt).
    re.compile(r"^HTTPS certificate is not trusted"),
)
EXPECTED_REVIEW_GAPS = {
    "cloud.release-gate": "the CI release gate record (it needs the commit's GitHub Actions runs)",
    "cloud.build": "the workflow's build-validate job record (image-build.json)",
}
# Everything not secret that the stages pass to deploy.sh. AZURE_* and ARM_* settings from the
# caller's environment are dropped so nothing can point the rehearsal at a subscription.
DROPPED_PREFIXES = ("AZURE_", "ARM_", "ACR_", "PROPERTYSCOPE_PUBLIC_")
VALIDATION_LINE = re.compile(r"^(PASS|FAIL|SKIP|INFO) (.+)$", re.MULTILINE)

Runner = Callable[[Sequence[str], Mapping[str, str], Path], int]


@dataclass(slots=True)
class Stage:
    """One rehearsal step and what it showed."""

    name: str
    outcome: str = "not run"  # success | failure | skipped | not run
    detail: str = ""
    log: str | None = None
    seconds: float = 0.0


@dataclass(slots=True)
class Rehearsal:
    """Settings and the results of one rehearsal run."""

    output: Path
    keep: bool = False
    keep_images: bool = False
    reuse_images: bool = False
    commit: str = ""
    image_tag: str = ""
    started_at: str = ""
    finished_at: str = ""
    stages: dict[str, Stage] = field(default_factory=dict)
    results: dict[str, Any] = field(default_factory=dict)

    @property
    def cloud_dir(self) -> Path:
        """deploy.sh's log directory (the workflow's .propertyscope-runtime/cloud/)."""
        return self.output / "cloud"

    @property
    def logs_dir(self) -> Path:
        return self.cloud_dir / "logs"

    @property
    def key_vault(self) -> Path:
        return self.output / "key-vault"

    @property
    def evidence_dir(self) -> Path:
        """A scratch evidence root, laid out like docs/release-2/evidence/ (cloud/ below it)."""
        return self.output / "evidence"

    def stage(self, name: str) -> Stage:
        return self.stages.setdefault(name, Stage(name))


# --- pure helpers (unit tested) -------------------------------------------------------------


def daemon_configuration(cloud_init: str, *, insecure_registry: str) -> dict[str, Any]:
    """The VM's /etc/docker/daemon.json from cloud-init, plus the plain-HTTP rehearsal registry."""
    document = yaml.safe_load(cloud_init)
    files = document.get("write_files", []) if isinstance(document, dict) else []
    for entry in files:
        if isinstance(entry, dict) and entry.get("path") == "/etc/docker/daemon.json":
            configuration = json.loads(entry["content"])
            if not isinstance(configuration, dict):
                break
            configuration["insecure-registries"] = [insecure_registry]
            return configuration
    raise ValueError("cloud-init.yaml writes no /etc/docker/daemon.json")


def write_key_vault(directory: Path, names: Iterable[str] = KEY_VAULT_SECRETS) -> None:
    """Throwaway values for every Key Vault secret (64 hex characters, like `deploy.sh secrets`)."""
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        path = directory / name
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="ascii", newline="") as handle:
            handle.write(secrets.token_hex(32))


def deploy_environment(
    rehearsal: Rehearsal, base: Mapping[str, str], **extra: str
) -> dict[str, str]:
    """The environment deploy.sh runs with: rehearsal stand-ins, never an Azure setting."""
    environment = {
        key: value
        for key, value in base.items()
        if not key.startswith(DROPPED_PREFIXES) and key not in {"IMAGE_TAG", "GITHUB_ACTIONS"}
    }
    environment.update(
        {
            "PROPERTYSCOPE_REHEARSAL": "true",
            "PROPERTYSCOPE_REHEARSAL_VM": VM_CONTAINER,
            "PROPERTYSCOPE_PUSH_REGISTRY": f"127.0.0.1:{REGISTRY_PORT}",
            "PROPERTYSCOPE_BUILD_TAG": BUILD_TAG,
            "PROPERTYSCOPE_CLOUD_LOG_DIR": rehearsal.cloud_dir.as_posix(),
            "PROPERTYSCOPE_CLOUD_AI": "false",
            # The Azure default: the site-wide viewer login is on.
            "PROPERTYSCOPE_SITE_AUTH": "on",
            "PROPERTYSCOPE_SITE_USER": "propertyscope",
            "PROPERTYSCOPE_PUBLIC_HOST": PUBLIC_HOST,
            "PROPERTYSCOPE_ACME_EMAIL": "rehearsal@example.invalid",
            "ACR_LOGIN_SERVER": VM_REGISTRY,
            "ACR_NAME": REGISTRY_CONTAINER,
            "VM_NAME": VM_CONTAINER,
            "KEY_VAULT_NAME": "rehearsal-key-vault-directory",
            "PUBLIC_FQDN": PUBLIC_HOST,
            "COMPOSE_PROGRESS": "plain",
            "BUILDKIT_PROGRESS": "plain",
            "NO_COLOR": "1",
        }
    )
    if rehearsal.image_tag:
        environment["IMAGE_TAG"] = rehearsal.image_tag
    if rehearsal.commit:
        environment["PROPERTYSCOPE_DEPLOY_SHA"] = rehearsal.commit
    environment.update(extra)
    return environment


def outputs_text() -> str:
    """outputs.txt in the `deploy.sh outputs` format, naming the rehearsal stand-ins."""
    return (
        "resource_group=none-local-rehearsal\n"
        f"acr_name={REGISTRY_CONTAINER}\n"
        f"acr_login_server={VM_REGISTRY}\n"
        f"vm_name={VM_CONTAINER}\n"
        "key_vault_name=none-local-directory\n"
        f"fqdn={PUBLIC_HOST}\n"
        f"public_url=https://{PUBLIC_HOST}\n"
    )


def parse_validation(text: str) -> list[tuple[str, str]]:
    return [(verdict, detail.strip()) for verdict, detail in VALIDATION_LINE.findall(text)]


def split_endpoint_results(
    results: Sequence[tuple[str, str]], *, vm_closed_ports: Iterable[int] = ()
) -> tuple[list[str], list[str]]:
    """(unexpected failures, failures a local rehearsal cannot avoid).

    The endpoint script probes ``localhost``, which on a developer machine is also every service
    the laptop runs. A port it finds open counts against the deployment only when the rehearsal
    VM itself answers on it (``vm_closed_ports`` comes from a probe inside the rehearsal network).
    """
    closed = set(vm_closed_ports)
    unexpected: list[str] = []
    expected: list[str] = []
    for verdict, detail in results:
        if verdict != "FAIL":
            continue
        port = REACHABLE_PORT.match(detail)
        if port is not None and int(port.group(1)) in closed:
            expected.append(
                f"{detail}: a process on this machine, not the rehearsal VM, which keeps the "
                "port closed"
            )
        elif any(pattern.search(detail) for pattern in EXPECTED_ENDPOINT_FAILURES):
            expected.append(detail)
        else:
            unexpected.append(detail)
    return unexpected, expected


def closed_port_list(script: str) -> tuple[int, ...]:
    """The ports validate-endpoint-security.sh expects closed (its `for port in ...` loop)."""
    match = re.search(r"^for port in ([0-9 ]+); do$", script, re.MULTILINE)
    if match is None:
        raise ValueError("validate-endpoint-security.sh has no closed-port loop")
    return tuple(int(port) for port in match.group(1).split())


def parse_port_probe(text: str) -> dict[int, bool]:
    """``OPEN <port>``/``CLOSED <port>`` lines -> port: open."""
    return {
        int(port): state == "OPEN"
        for state, port in re.findall(r"^(OPEN|CLOSED) ([0-9]+)$", text, re.MULTILINE)
    }


def ai_overlay_findings(model: Mapping[str, Any]) -> list[tuple[str, str]]:
    """PASS/FAIL lines: the AI overlay hands the AI-mode and Multi-Agent tokens over as secrets."""
    findings: list[tuple[str, str]] = []

    def check(passed: bool, detail: str) -> None:
        findings.append(("PASS" if passed else "FAIL", detail))

    services = model.get("services") or {}
    top_secrets = model.get("secrets") or {}
    for name, filename in (
        ("multi_agent_service_token", "multi-agent-service-token"),
        ("ai_mode_service_token", "ai-mode-service-token"),
    ):
        source = str((top_secrets.get(name) or {}).get("file", ""))
        check(
            source.replace("\\", "/").endswith(f"/{filename}"),
            f"secret {name} is the file {filename}",
        )
    for backend in MULTI_AGENT_BACKENDS:
        service = services.get(backend) or {}
        mounted = {
            str(item.get("source") if isinstance(item, dict) else item)
            for item in service.get("secrets") or []
        }
        environment = service.get("environment") or {}
        secret_env = str(environment.get("PROPERTYSCOPE_SECRET_ENV", ""))
        wired = "multi_agent_service_token" in mounted and MULTI_AGENT_SECRET_ENV in secret_env
        check(wired, f"{backend} gets multi_agent_service_token as a Compose secret")
        check(
            str(environment.get("MULTI_AGENT_BASE_URL", "")).startswith(
                "http://host.docker.internal:"
            ),
            f"{backend} reaches the Multi-Agent Server through the host gateway",
        )
        check(
            "ai_mode_service_token" in mounted,
            f"{backend} gets ai_mode_service_token as a Compose secret",
        )
        token_value = str(environment.get("MULTI_AGENT_SERVICE_TOKEN", ""))
        check(not token_value, f"{backend} has no Multi-Agent token value in its environment")
    return findings


def review_outcome(checks: Sequence[Mapping[str, Any]]) -> tuple[list[str], list[str]]:
    """(failed required checks that a rehearsal should pass, expected evidence gaps)."""
    unexpected: list[str] = []
    expected: list[str] = []
    for check in checks:
        if check.get("status") == "passed" or not check.get("required", True):
            continue
        identifier = str(check.get("id"))
        (expected if identifier in EXPECTED_REVIEW_GAPS else unexpected).append(identifier)
    return unexpected, expected


def build_evidence_tree(rehearsal: Rehearsal) -> list[str]:
    """Copy the outputs into <evidence>/cloud/ the way the evidence README says to copy the
    workflow artifacts. The release gate and the image-build record do not exist locally."""
    target = rehearsal.evidence_dir / "cloud"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    source = rehearsal.cloud_dir
    copied: list[str] = []
    copies = {
        "report/cloud-deployment-report.md": "cloud-deployment-report.md",
        "report/cloud-deployment-report.json": "cloud-deployment-report.json",
        "smoke/cloud-smoke.json": "smoke/cloud-smoke.json",
        "smoke/cloud-smoke.md": "smoke/cloud-smoke.md",
        "vm-deploy.log": "vm-deploy.log",
        "vm-status.log": "vm-status.log",
        "image-tag.txt": "image-tag.txt",
        "outputs.txt": "outputs.txt",
        "public-url.txt": "public-url.txt",
        "endpoint-security.txt": "endpoint-security.txt",
        "data-security.txt": "data-security.txt",
    }
    for relative, destination in copies.items():
        path = source / relative
        if path.is_file():
            (target / destination).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target / destination)
            copied.append(f"cloud/{destination}")
    if rehearsal.logs_dir.is_dir():
        for path in sorted(rehearsal.logs_dir.glob("*.log")):
            (target / "logs").mkdir(exist_ok=True)
            shutil.copyfile(path, target / "logs" / path.name)
            copied.append(f"cloud/logs/{path.name}")
    return copied


def render_summary(rehearsal: Rehearsal) -> str:
    """rehearsal-summary.md: the stage table and the headline results."""
    results = rehearsal.results
    lines = [
        "# Local cloud rehearsal",
        "",
        f"**{NOTICE}**",
        "",
        f"- Commit `{rehearsal.commit or 'unknown'}`, "
        f"image tag `{rehearsal.image_tag or 'unknown'}`",
        f"- Started {rehearsal.started_at}, finished {rehearsal.finished_at}",
        f"- Verdict: **{results.get('verdict', 'unknown')}**",
        "",
        "| Stage | Outcome | Detail |",
        "|---|---|---|",
    ]
    for stage in rehearsal.stages.values():
        detail = stage.detail.replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {stage.name} | {stage.outcome} | {detail} |")
    for title, key in (
        ("Expected local gaps", "expected_gaps"),
        ("Unexpected problems", "problems"),
    ):
        items = results.get(key) or []
        lines += ["", f"## {title}", ""]
        lines += [f"- {item}" for item in items] if items else ["- none"]
    lines.append("")
    return "\n".join(lines)


# --- execution --------------------------------------------------------------------------------


def run_logged(command: Sequence[str], environment: Mapping[str, str], log: Path) -> int:
    """Run one command from the repository root, streaming its output to the console and log."""
    log.parent.mkdir(parents=True, exist_ok=True)
    print(f"> {' '.join(command)}", flush=True)
    with log.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"> {' '.join(command)}\n")
        process = subprocess.Popen(  # noqa: S603 - argv built by this module, no shell
            list(command),
            cwd=REPOSITORY_ROOT,
            env=dict(environment),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            errors="replace",
        )
        for line in process.stdout or ():
            sys.stdout.write(line)
            handle.write(line.replace("\r", ""))
        return process.wait()


def _capture(command: Sequence[str], environment: Mapping[str, str] | None = None) -> str:
    completed = subprocess.run(  # noqa: S603 - argv built by this module, no shell
        list(command),
        cwd=REPOSITORY_ROOT,
        env=None if environment is None else dict(environment),
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        output = (completed.stderr or completed.stdout).strip()[-300:]
        raise RuntimeError(f"{' '.join(command[:4])} failed: {output}")
    return completed.stdout


def port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        return probe.connect_ex((host, port)) == 0


def compose_command(*arguments: str) -> list[str]:
    return ["docker", "compose", "--project-name", PROJECT, "--file", str(COMPOSE_FILE), *arguments]


class Runbook:
    """Runs the rehearsal stages in order; each failure is recorded and later stages that need
    it are skipped, so the summary always shows how far the deployment path got."""

    def __init__(
        self,
        rehearsal: Rehearsal,
        *,
        bash: str,
        environment: Mapping[str, str] | None = None,
        runner: Runner = run_logged,
    ) -> None:
        self.rehearsal = rehearsal
        self.bash = bash
        self.environment = dict(os.environ if environment is None else environment)
        self.runner = runner

    # --- plumbing ---------------------------------------------------------------------------

    def _compose_environment(self) -> dict[str, str]:
        return {
            **self.environment,
            "PROPERTYSCOPE_REHEARSAL_DIR": str(self.rehearsal.output),
            "PROPERTYSCOPE_REHEARSAL_REGISTRY_PORT": str(REGISTRY_PORT),
            "COMPOSE_PROGRESS": "plain",
            "BUILDKIT_PROGRESS": "plain",
        }

    def _deploy(self, stage: str, *arguments: str, **extra: str) -> int:
        environment = deploy_environment(self.rehearsal, self.environment, **extra)
        return self.runner([self.bash, DEPLOY_SCRIPT, *arguments], environment, self._log(stage))

    def _log(self, stage: str) -> Path:
        path = self.rehearsal.logs_dir / f"{stage.replace('_', '-')}.log"
        self.rehearsal.stage(stage).log = path.relative_to(self.rehearsal.output).as_posix()
        return path

    def _record(self, name: str, outcome: str, detail: str, started: float) -> bool:
        stage = self.rehearsal.stage(name)
        stage.outcome, stage.detail = outcome, detail
        stage.seconds = round(time.monotonic() - started, 1)
        print(f"[rehearsal] {name}: {outcome} - {detail}", flush=True)
        return outcome == "success"

    def _skip(self, name: str, reason: str) -> None:
        stage = self.rehearsal.stage(name)
        stage.outcome, stage.detail = "skipped", reason

    # --- stages -----------------------------------------------------------------------------

    def preflight(self) -> bool:
        started = time.monotonic()
        try:
            _capture(["docker", "info", "--format", "{{.ServerVersion}}"])
        except (RuntimeError, OSError) as exc:
            return self._record("preflight", "failure", f"Docker is not reachable: {exc}", started)
        existing = _capture(
            [
                "docker",
                "ps",
                "--all",
                "--quiet",
                "--filter",
                f"label=com.docker.compose.project={PROJECT}",
            ]
        ).split()
        if existing:
            # A previous rehearsal that was kept or interrupted: it is this project, so remove it.
            print("[rehearsal] removing the previous ps-azure-rehearsal project", flush=True)
            self.runner(
                compose_command("down", "--volumes", "--remove-orphans"),
                self._compose_environment(),
                self._log("preflight"),
            )
        busy = [port for port in (*EDGE_PORTS, REGISTRY_PORT) if port_in_use(port)]
        if busy:
            return self._record(
                "preflight",
                "failure",
                f"127.0.0.1 port(s) {', '.join(map(str, busy))} are in use; "
                "stop what listens there",
                started,
            )
        head = _capture(["git", "rev-parse", "HEAD"]).strip()
        dirty = bool(_capture(["git", "status", "--porcelain", "--untracked-files=no"]).strip())
        self.rehearsal.commit = head
        detail = f"Docker reachable; ports 80, 443 and {REGISTRY_PORT} free; commit {head[:12]}"
        return self._record(
            "preflight", "success", detail + (" with uncommitted changes" if dirty else ""), started
        )

    def prepare(self) -> bool:
        started = time.monotonic()
        output = self.rehearsal.output
        if output.exists():
            shutil.rmtree(output)
        self.rehearsal.logs_dir.mkdir(parents=True)
        configuration = daemon_configuration(
            CLOUD_INIT.read_text(encoding="utf-8"), insecure_registry=VM_REGISTRY
        )
        (output / "daemon.json").write_text(json.dumps(configuration, indent=2) + "\n", "utf-8")
        write_key_vault(self.rehearsal.key_vault)
        (self.rehearsal.cloud_dir / "outputs.txt").write_text(outputs_text(), encoding="utf-8")
        return self._record(
            "prepare",
            "success",
            f"cloud-init daemon.json, {len(KEY_VAULT_SECRETS)} throwaway Key Vault values "
            "(not printed)",
            started,
        )

    def infrastructure(self) -> bool:
        started = time.monotonic()
        status = self.runner(
            compose_command("up", "--detach", "--build", "--wait", "--wait-timeout", "300"),
            self._compose_environment(),
            self._log("infrastructure"),
        )
        detail = f"{REGISTRY_CONTAINER} (registry:2) and {VM_CONTAINER} (Docker-in-Docker VM)"
        return self._record(
            "infrastructure", "success" if status == 0 else "failure", detail, started
        )

    def push(self) -> bool:
        started = time.monotonic()
        arguments = ["push", "--reuse-images"] if self.rehearsal.reuse_images else ["push"]
        status = self._deploy("push", *arguments)
        tag_file = self.rehearsal.cloud_dir / "image-tag.txt"
        if status == 0 and tag_file.is_file():
            self.rehearsal.image_tag = tag_file.read_text(encoding="utf-8").strip()
            return self._record(
                "push",
                "success",
                f"built under :{BUILD_TAG}, pushed :{self.rehearsal.image_tag} and the mirrors",
                started,
            )
        return self._record("push", "failure", f"deploy.sh push exited {status}", started)

    def deploy(self) -> bool:
        started = time.monotonic()
        status = self._deploy("deploy", "deploy")
        log = self.rehearsal.cloud_dir / "vm-deploy.log"
        text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
        result = re.findall(r"^PROPERTYSCOPE_RESULT=(\{.*\})\s*$", text, re.M)
        vm = json.loads(result[-1]) if result else {}
        self.rehearsal.results["vm"] = vm
        accepted = re.findall(r"Feature 1 data: (\d+) accepted releases", text)
        self.rehearsal.results["accepted_releases"] = int(accepted[-1]) if accepted else 0
        detail = (
            f"{vm.get('containers_running', '?')}/{vm.get('containers_total', '?')} containers "
            f"running, cloud AI {vm.get('cloud_ai', '?')}, "
            f"{self.rehearsal.results['accepted_releases']} accepted releases"
        )
        if "trusted certificate for" not in text:
            detail += "; the VM's own HTTPS check did not pass"
        ok = status == 0 and vm.get("containers_running") == vm.get("containers_total")
        return self._record("deploy", "success" if ok else "failure", detail, started)

    def smoke(self) -> bool:
        started = time.monotonic()
        status = self._deploy("smoke", "smoke", "--insecure", **self._site_login())
        document = self._json(self.rehearsal.cloud_dir / "smoke" / "cloud-smoke.json")
        summary = document.get("summary") or {}
        self.rehearsal.results["smoke"] = {
            "passed": document.get("passed"),
            "summary": summary,
            "ai_state": document.get("ai_state"),
            "site_login": document.get("site_login"),
            "images_source": document.get("images_source"),
            "failed": [c.get("name") for c in document.get("checks", []) if not c.get("passed")],
            "crud_operations": sorted(
                {
                    f"{c.get('owner')}:{c.get('operation')}"
                    for c in document.get("checks", [])
                    if c.get("category") == "crud" and c.get("passed")
                }
            ),
        }
        detail = (
            f"{summary.get('passed', 0)}/{summary.get('total', 0)} checks passed, AI "
            f"{document.get('ai_state', 'not checked')}, site login "
            f"{document.get('site_login', 'not checked')}"
        )
        return self._record(
            "smoke",
            "success" if status == 0 and document.get("passed") else "failure",
            detail,
            started,
        )

    def endpoint_security(self) -> bool:
        started = time.monotonic()
        password = (self.rehearsal.key_vault / EDGE_PASSWORD_SECRET).read_text(encoding="ascii")
        extra = {"EDGE_PASSWORD": password, **self._site_login()}
        ca = self._edge_ca()
        if ca is not None:
            # The HTTP-level checks trust Caddy's internal CA; the public-trust check never does.
            extra["EDGE_CA_FILE"] = ca.as_posix()
        self._deploy("endpoint_security", "validate-endpoint", **extra)
        path = self.rehearsal.cloud_dir / "endpoint-security.txt"
        results = parse_validation(path.read_text(encoding="utf-8")) if path.is_file() else []
        probe = self._vm_port_probe()
        unexpected, expected = split_endpoint_results(
            results, vm_closed_ports=[port for port, is_open in probe.items() if not is_open]
        )
        # From inside the rehearsal network the VM must answer on 80/443 and nothing else.
        unexpected += [
            f"the rehearsal VM {'answers' if is_open else 'does not answer'} on port {port}"
            for port, is_open in sorted(probe.items())
            if is_open != (port in EDGE_PORTS)
        ]
        if not probe:
            unexpected.append("the in-network port probe of the rehearsal VM did not run")
        passed = sum(verdict == "PASS" for verdict, _ in results)
        self.rehearsal.results["endpoint_security"] = {
            "passed": passed,
            "failed_unexpected": unexpected,
            "failed_expected": expected,
            "skipped": [detail for verdict, detail in results if verdict == "SKIP"],
            "edge_ca_trusted_for_http_checks": ca is not None,
            "vm_open_ports": sorted(port for port, is_open in probe.items() if is_open),
        }
        detail = f"{passed} PASS, {len(unexpected)} unexpected FAIL, {len(expected)} expected FAIL"
        ok = bool(results) and not unexpected
        return self._record("endpoint_security", "success" if ok else "failure", detail, started)

    def _site_login(self) -> dict[str, str]:
        """The viewer password, as GitHub Actions passes it to the smoke test and validator."""
        path = self.rehearsal.key_vault / SITE_PASSWORD_SECRET
        return {"PROPERTYSCOPE_SITE_PASSWORD": path.read_text(encoding="ascii")}

    def _edge_ca(self) -> Path | None:
        """Caddy's internal root and intermediate certificates (not secret), or None."""
        script = f"cat {CADDY_CA}/root.crt {CADDY_CA}/intermediate.crt"
        try:
            certificates = _capture(
                [
                    "docker",
                    "exec",
                    VM_CONTAINER,
                    "docker",
                    "exec",
                    EDGE_CONTAINER,
                    "sh",
                    "-c",
                    script,
                ]
            )
        except (RuntimeError, OSError):
            return None
        if certificates.count("BEGIN CERTIFICATE") < 2:
            return None
        path = self.rehearsal.output / "edge-ca.crt"
        path.write_text(certificates, encoding="ascii")
        return path

    def _vm_port_probe(self) -> dict[int, bool]:
        """Which of the endpoint script's ports the rehearsal VM answers on, probed from a
        container on the rehearsal network (an outside client of the VM, not of this machine)."""
        ports = (*EDGE_PORTS, *closed_port_list(ENDPOINT_SCRIPT.read_text(encoding="utf-8")))
        script = (
            f"for port in {' '.join(map(str, ports))}; do "
            f'if timeout 3 bash -c "exec 3<>/dev/tcp/{VM_CONTAINER}/$port" 2>/dev/null; '
            'then echo "OPEN $port"; else echo "CLOSED $port"; fi; done'
        )
        log = self.rehearsal.logs_dir / "vm-port-probe.log"
        try:
            output = _capture(
                [
                    *("docker", "run", "--rm", "--network", REHEARSAL_NETWORK),
                    *("--entrypoint", "bash", VM_IMAGE, "-c", script),
                ]
            )
        except (RuntimeError, OSError) as exc:
            log.write_text(f"probe failed: {exc}\n", encoding="utf-8")
            return {}
        log.write_text(
            f"TCP probe of {VM_CONTAINER} from the rehearsal network\n{output}", encoding="utf-8"
        )
        return parse_port_probe(output)

    def data_security(self) -> bool:
        started = time.monotonic()
        status = self._deploy("data_security", "vm-validate-data")
        log = self.rehearsal.cloud_dir / "vm-validate-data.log"
        text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
        results = parse_validation(text)
        (self.rehearsal.cloud_dir / "data-security.txt").write_text(
            "INFO local rehearsal: only the on-host half (propertyscope-vm.sh validate-data) ran; "
            "the Azure control-plane checks of validate-data-security.sh need Azure\n"
            + "".join(f"{verdict} {detail}\n" for verdict, detail in results),
            encoding="utf-8",
        )
        failed = [detail for verdict, detail in results if verdict == "FAIL"]
        self.rehearsal.results["data_security"] = {
            "passed": sum(verdict == "PASS" for verdict, _ in results),
            "failed": failed,
        }
        ok = status == 0 and bool(results) and not failed
        detail = f"{len(results) - len(failed)} PASS, {len(failed)} FAIL (on-host half only)"
        return self._record("data_security", "success" if ok else "failure", detail, started)

    def status(self) -> bool:
        started = time.monotonic()
        status = self._deploy("status", "status")
        return self._record(
            "status", "success" if status == 0 else "failure", "vm-status.log", started
        )

    def ai_overlay_config(self) -> bool:
        started = time.monotonic()
        files = " ".join(
            f"-f {name}"
            for name in (
                "docker-compose.yml",
                "deployment/enabled-features.compose.yml",
                "docker-compose.azure.yml",
                "docker-compose.azure-ai.yml",
            )
        )
        script = (
            f"cd /opt/propertyscope/app && docker compose --project-name {VM_COMPOSE_PROJECT} "
            f"{files} --profile release-0 config --format json"
        )
        log = self._log("ai_overlay_config")
        try:
            rendered = _capture(["docker", "exec", VM_CONTAINER, "sh", "-c", script])
            findings = ai_overlay_findings(json.loads(rendered))
        except (RuntimeError, OSError, json.JSONDecodeError) as exc:
            log.write_text(f"FAIL docker compose config of the AI overlay: {exc}\n", "utf-8")
            return self._record("ai_overlay_config", "failure", str(exc)[:200], started)
        log.write_text(
            "docker compose config (AI overlay) inside the rehearsal VM; no AI service started\n"
            + "".join(f"{verdict} {detail}\n" for verdict, detail in findings),
            encoding="utf-8",
        )
        failed = [detail for verdict, detail in findings if verdict == "FAIL"]
        self.rehearsal.results["ai_overlay_config"] = {
            "passed": len(findings) - len(failed),
            "failed": failed,
        }
        return self._record(
            "ai_overlay_config",
            "failure" if failed else "success",
            f"{len(findings) - len(failed)}/{len(findings)} wiring checks (config only)",
            started,
        )

    def report(self) -> bool:
        started = time.monotonic()
        stages = self.rehearsal.stages
        arguments = [
            sys.executable,
            "scripts/cloud_deployment_report.py",
            "--log-dir",
            str(self.rehearsal.cloud_dir),
            "--output-dir",
            str(self.rehearsal.cloud_dir / "report"),
            "--notice",
            NOTICE,
            "--stage",
            "provision=skipped",
        ]
        for name in ("push", "deploy", "smoke", "endpoint_security"):
            outcome = stages[name].outcome if name in stages else "skipped"
            arguments += ["--stage", f"{name}={outcome if outcome != 'not run' else 'skipped'}"]
        if "data_security" in stages:
            arguments += ["--stage", f"data_security={stages['data_security'].outcome}"]
        environment = {
            key: value
            for key, value in self.environment.items()
            if not key.startswith(("GITHUB_", "AZURE_"))
        }
        environment.update(
            {
                "GITHUB_WORKFLOW": "dev.py cloud rehearse (local rehearsal, not Azure)",
                "GITHUB_EVENT_NAME": "local-rehearsal",
                "PROPERTYSCOPE_DEPLOY_SHA": self.rehearsal.commit,
            }
        )
        status = self.runner(arguments, environment, self._log("report"))
        report = self._json(self.rehearsal.cloud_dir / "report" / "cloud-deployment-report.json")
        self.rehearsal.results["report_verdict"] = report.get("verdict")
        return self._record(
            "report",
            "success" if status == 0 and report else "failure",
            f"report verdict {report.get('verdict', 'missing')}",
            started,
        )

    def review(self) -> bool:
        started = time.monotonic()
        copied = build_evidence_tree(self.rehearsal)
        from scripts.devtools.review.workflow import run_review

        try:
            result = run_review(
                "cloud",
                evidence_dir=self.rehearsal.evidence_dir,
                out_dir=self.rehearsal.output / "review",
                deterministic=True,
            )
        except Exception as exc:  # recorded in the summary, never hidden
            return self._record("review", "failure", f"review did not run: {exc}", started)
        checks = [check.model_dump(mode="json") for check in result.record.bundle.checks]
        unexpected, expected = review_outcome(checks)
        self.rehearsal.results["review"] = {
            "verdict": result.record.verdict.value,
            "report": result.report_path.relative_to(self.rehearsal.output).as_posix(),
            "evidence_files": copied,
            "checks": {str(check["id"]): str(check["status"]) for check in checks},
            "failed_unexpected": unexpected,
            "failed_expected": expected,
        }
        detail = (
            f"verdict {result.record.verdict.value}; {len(unexpected)} unexpected failed "
            f"check(s); expected gaps: {', '.join(expected) or 'none'}"
        )
        return self._record("review", "failure" if unexpected else "success", detail, started)

    def teardown(self) -> bool:
        started = time.monotonic()
        if self.rehearsal.keep:
            self._skip("teardown", "--keep: the stack stays up; rerun without --keep to remove it")
            return True
        status = self.runner(
            compose_command("down", "--volumes", "--remove-orphans"),
            self._compose_environment(),
            self._log("teardown"),
        )
        removed = self._remove_local_tags()
        shutil.rmtree(self.rehearsal.key_vault, ignore_errors=True)
        detail = (
            f"down --volumes on {PROJECT}; removed {removed} local image tag(s); secrets deleted"
        )
        return self._record("teardown", "success" if status == 0 else "failure", detail, started)

    def _remove_local_tags(self) -> int:
        """Untag what push created on this machine; never a propertyscope/<service>:dev tag."""
        listing = _capture(["docker", "image", "ls", "--format", "{{.Repository}}:{{.Tag}}"])
        prefix = f"127.0.0.1:{REGISTRY_PORT}/propertyscope/"
        tags = [
            line.strip()
            for line in listing.splitlines()
            if line.startswith(prefix)
            or (
                not self.rehearsal.keep_images
                and line.startswith("propertyscope/")
                and line.strip().endswith(f":{BUILD_TAG}")
            )
        ]
        for tag in tags:
            subprocess.run(  # noqa: S603 - fixed docker argv
                ["docker", "image", "rm", "--no-prune", tag],  # noqa: S607 - docker on PATH
                capture_output=True,
                check=False,
            )
        return len(tags)

    @staticmethod
    def _json(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    # --- orchestration ----------------------------------------------------------------------

    def run(self) -> int:
        rehearsal = self.rehearsal
        rehearsal.started_at = datetime.now(UTC).isoformat(timespec="seconds")
        try:
            if self.preflight() and self.prepare() and self.infrastructure():
                if self.push() and self.deploy():
                    self.smoke()
                    self.endpoint_security()
                    self.data_security()
                    self.status()
                    self.ai_overlay_config()
                self.report()
                self.review()
        finally:
            if rehearsal.stage("preflight").outcome == "success":
                self.teardown()
            rehearsal.finished_at = datetime.now(UTC).isoformat(timespec="seconds")
            self._finish()
        return 0 if rehearsal.results.get("verdict") == "PASSED" else 1

    def _finish(self) -> None:
        rehearsal = self.rehearsal
        required = (
            "preflight",
            "prepare",
            "infrastructure",
            "push",
            "deploy",
            "smoke",
            "endpoint_security",
            "data_security",
            "ai_overlay_config",
            "report",
            "review",
        )
        problems = [
            f"{name}: {rehearsal.stage(name).outcome} {rehearsal.stage(name).detail}".strip()
            for name in required
            if rehearsal.stage(name).outcome != "success"
        ]
        if rehearsal.stage("teardown").outcome == "failure":
            problems.append("teardown failed: remove the ps-azure-rehearsal project by hand")
        gaps = [
            f"endpoint security: {detail} (expected locally)"
            for detail in (rehearsal.results.get("endpoint_security") or {}).get(
                "failed_expected", []
            )
        ]
        gaps += [
            f"review {check}: {EXPECTED_REVIEW_GAPS[check]} does not exist locally"
            for check in (rehearsal.results.get("review") or {}).get("failed_expected", [])
        ]
        rehearsal.results.update(
            {
                "verdict": "FAILED" if problems else "PASSED",
                "problems": problems,
                "expected_gaps": gaps,
            }
        )
        rehearsal.output.mkdir(parents=True, exist_ok=True)
        document = {
            "schema_version": 1,
            "tool": "dev.py cloud rehearse",
            "notice": NOTICE,
            "commit": rehearsal.commit,
            "image_tag": rehearsal.image_tag,
            "started_at": rehearsal.started_at,
            "finished_at": rehearsal.finished_at,
            "kept": rehearsal.keep,
            "stages": [asdict(stage) for stage in rehearsal.stages.values()],
            "results": rehearsal.results,
        }
        (rehearsal.output / "rehearsal-summary.json").write_text(
            json.dumps(document, indent=2) + "\n", encoding="utf-8"
        )
        (rehearsal.output / "rehearsal-summary.md").write_text(
            render_summary(rehearsal), encoding="utf-8"
        )
        print(
            f"\n[rehearsal] {rehearsal.results['verdict']}: summary in "
            f"{rehearsal.output / 'rehearsal-summary.md'}",
            flush=True,
        )


def add_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument(
        "--keep",
        action="store_true",
        help="Leave the rehearsal registry and VM running (https://localhost) and the generated "
        "secrets in place; the next run removes them",
    )
    command.add_argument(
        "--keep-images",
        action="store_true",
        help="Keep the propertyscope/<service>:rehearsal build tags for a faster next run",
    )
    command.add_argument(
        "--reuse-images",
        action="store_true",
        help="deploy.sh push --reuse-images: skip the build when this commit's rehearsal images "
        "exist (needs --keep-images on the previous run and a clean tree)",
    )
    command.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Where everything is written (default: .propertyscope-runtime/cloud-rehearsal)",
    )


def run(arguments: argparse.Namespace, *, bash: str) -> int:
    output = Path(arguments.output_dir).resolve()
    runtime = (REPOSITORY_ROOT / ".propertyscope-runtime").resolve()
    if not output.is_relative_to(runtime):
        # Throwaway secrets are written here; keep them inside the Git-ignored runtime store.
        raise RuntimeError("--output-dir must be inside .propertyscope-runtime/")
    rehearsal = Rehearsal(
        output=output,
        keep=arguments.keep,
        keep_images=arguments.keep_images or arguments.reuse_images,
        reuse_images=arguments.reuse_images,
    )
    return Runbook(rehearsal, bash=bash).run()
