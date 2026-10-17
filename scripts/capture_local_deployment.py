"""Capture the Release 2 local deployment report and per-terminal logs (R2-41, plan item G1).

Run it from a "system test" terminal against a stack that is already running::

    uv run scripts/dev.py stack up                  # Compose + host AI services (combined mode)
    uv run python scripts/capture_local_deployment.py

It never starts, stops or reconfigures anything. Against the running stack it records:

- the commit, branch and Compose project, and every container of that project with its state;
- every host service (AI-mode 5005, MCP 5011, RAG 5012, Multi-Agent 5013): PID, readiness and
  the facts that show it is a host process and not a container;
- the edge home page, each enabled feature's frontend and health through the edge, and one
  self-cleaning create -> read -> delete -> confirm case per feature (``cloud_smoke`` cases);
- the Feature 1 record counts that decide whether the data is the seeded demonstration baseline;
- the direct MCP, RAG, AI-mode and Multi-Agent probes (``release1_probe``);
- a terminal Multi-Agent run of the Feature 1 template through ``multi-agent-server --server``
  that reaches ``awaiting_human``, a recorded decision, the run's history and its export.

It writes ``docs/release-2/evidence/local/``: ``local-deployment-report.md`` and ``.json``, one
``terminal-N-<name>.log`` per server (the bytes each server wrote during the capture window, ANSI
stripped, secret-shaped values redacted, size capped), ``terminal-6-system-test.log`` (this
script's own transcript) and ``multi-agent-run/`` (the exported run). Failures are reported in
the verdict, never hidden; the exit code is 1 when any check failed.

Run each host service in its own terminal with ``uv run scripts/dev.py ai serve SERVICE`` (stop the
managed one first with ``uv run scripts/dev.py ai stop SERVICE``); its output is also appended to
that service's host log, which this capture reads.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import IO, Any, Protocol

import httpx

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import cloud_smoke
from scripts.collect_ci_evidence import bound_log
from scripts.devtools import host_runtime
from scripts.devtools.config import REPOSITORY_ROOT, compose_project_name
from scripts.devtools.review.cloud import SECRET_PATTERNS

DEFAULT_OUTPUT_DIRECTORY = REPOSITORY_ROOT / "docs" / "release-2" / "evidence" / "local"
REPORT_NAME = "local-deployment-report"
EVIDENCE_PATHSPEC = ":(exclude)docs/release-2/evidence"
EXPORT_DIRECTORY_NAME = "multi-agent-run"
REQUEST_PREFIX = "local-deploy"
F1_TEMPLATE = "f1-release-readiness-review"
CAPTURE_ACTOR = "local-deployment-capture"
DECISION_NOTE = (
    "Scripted decision by scripts/capture_local_deployment.py to exercise the human-decision "
    "path of the local deployment check. The workflow publishes nothing."
)
SEEDED_RELEASE_PREFIX = "60000000-0000-0000-0000-"
SYNTHETIC_DATASETS = frozenset({"fixture-property"})
OPEN_RELEASE_STATES = ("candidate", "awaiting_review")
MAX_TERMINAL_LOG_BYTES = 256 * 1024
MAX_COMPOSE_LOG_BYTES = 512 * 1024
CONTEXT_LINES = 15
CONTEXT_BYTES = 32 * 1024
# Names a containerised AI service would have (current or retired, ADR-044/046/047).
AI_CONTAINER_NAMES = frozenset(
    {"ai-mode", "shared-ai-mode", "mcp", "mcp-server", "rag", "rag-server", "multi-agent"}
    | {"multi-agent-server"}
)
# Only these process variables are read, to report the capability mode. Never a credential.
CAPABILITY_VARIABLES: Mapping[str, tuple[str, ...]] = {
    "ai-mode": (
        "AI_MODE_MCP_ENABLED",
        "AI_MODE_RAG_ENABLED",
        "AI_MODE_LLM_PROVIDER",
        "AI_MODE_DEFAULT_MODEL_PROFILE",
    ),
    "mcp": (),
    "rag": (),
    "multi-agent": ("MULTI_AGENT_PROVIDER", "MULTI_AGENT_MCP_ENABLED"),
}
SECRET_VARIABLE = re.compile(r"(?i)(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)")
# Value-level redaction; ``bound_log`` then removes any line still matching SECRET_PATTERNS.
SECRET_VALUES = (
    re.compile(r"(?i)(authorization[\"']?\s*[:=]\s*[\"']?bearer\s+)[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)(x-propertyscope-ai-token[\"']?\s*[:=]\s*[\"']?)[A-Za-z0-9_-]{8,}"),
    re.compile(
        r"(?i)((?:api[_-]?key|service[_-]?token|access[_-]?token|secret|password)[\"']?\s*[:=]"
        r"\s*[\"']?)[A-Za-z0-9._~+/-]{16,}"
    ),
)
REDACTED_VALUE = "[redacted]"
RUN_ID = re.compile(r"Run ([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}) started")


@dataclass(frozen=True, slots=True)
class Terminal:
    """One terminal of the multi-terminal deployment and the log that stands for it."""

    number: int
    slug: str
    title: str
    command: str

    @property
    def filename(self) -> str:
        return f"terminal-{self.number}-{self.slug}.log"


TERMINALS = (
    Terminal(1, "compose", "Docker Compose stack", "uv run scripts/dev.py stack up; stack logs"),
    Terminal(2, "ai-mode", "AI-mode host process", "uv run scripts/dev.py ai serve ai-mode"),
    Terminal(3, "mcp", "MCP host process", "uv run scripts/dev.py ai serve mcp"),
    Terminal(4, "rag", "RAG host process", "uv run scripts/dev.py ai serve rag"),
    Terminal(
        5, "multi-agent", "Multi-Agent host process", "uv run scripts/dev.py ai serve multi-agent"
    ),
    Terminal(
        6,
        "system-test",
        "System test",
        "uv run python scripts/capture_local_deployment.py",
    ),
)
HOST_TERMINALS = {terminal.slug: terminal for terminal in TERMINALS[1:5]}


@dataclass(frozen=True, slots=True)
class CommandResult:
    """The outcome of one subprocess, decoded as UTF-8."""

    returncode: int
    stdout: str
    stderr: str
    duration_ms: int = 0


CommandRunner = Callable[[Sequence[str], float], CommandResult]


@dataclass(frozen=True, slots=True)
class Check:
    """One pass/fail observation in a report section."""

    section: str
    name: str
    passed: bool
    detail: str
    owner: str = "shared"


@dataclass(frozen=True, slots=True)
class Container:
    """One container of the selected Compose project."""

    name: str
    service: str
    state: str
    status: str
    health: str
    ports: str


@dataclass(frozen=True, slots=True)
class HostProcess:
    """What the operating system says about the process serving one host port."""

    service: str
    port: int
    mode: str  # managed | foreground | foreign | stopped
    pid: int | None = None
    listener_pids: tuple[int, ...] = ()
    executable: str = ""
    command: tuple[str, ...] = ()
    capability: Mapping[str, str] = field(default_factory=dict)
    launcher: str = ""


class ProcessInspector(Protocol):
    def describe(self, service: str, port: int) -> HostProcess: ...


def run_command(argv: Sequence[str], timeout: float) -> CommandResult:
    """Run a fixed argv without a shell and decode both streams as UTF-8."""
    started = time.monotonic()
    environment = dict(os.environ, PYTHONIOENCODING="utf-8", NO_COLOR="1")
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv built by this script, no shell
            list(argv),
            cwd=REPOSITORY_ROOT,
            env=environment,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        return CommandResult(127, "", f"{exc}", 0)
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else ""
        return CommandResult(124, output, f"timed out after {timeout:.0f} s", int(timeout * 1000))
    return CommandResult(
        completed.returncode,
        completed.stdout.decode("utf-8", "replace"),
        completed.stderr.decode("utf-8", "replace"),
        int((time.monotonic() - started) * 1000),
    )


class PsutilInspector:
    """Read host process facts from the launcher's state files and the OS (psutil)."""

    def __init__(self, host_directory: Path) -> None:
        self.host_directory = host_directory

    def describe(self, service: str, port: int) -> HostProcess:
        import psutil

        listeners: list[int] = []
        try:
            for connection in psutil.net_connections(kind="tcp"):
                if (
                    connection.status == psutil.CONN_LISTEN
                    and connection.laddr
                    and connection.laddr.port == port
                    and connection.pid
                    and connection.pid not in listeners
                ):
                    listeners.append(connection.pid)
        except (OSError, psutil.Error):
            listeners = []
        managed_pid: int | None = None
        launcher = ""
        tree: set[int] = set()
        try:
            state = json.loads((self.host_directory / f"{service}.json").read_text("utf-8"))
            process = psutil.Process(int(state["pid"]))
            if process.is_running() and process.create_time() == state["created_at"]:
                managed_pid = process.pid
                launcher = process.exe()
                tree = {process.pid, *(child.pid for child in process.children(recursive=True))}
        except (OSError, ValueError, KeyError, TypeError, psutil.Error):
            managed_pid = None
        if not listeners:
            return HostProcess(service, port, "stopped", managed_pid)
        listener = listeners[0]
        try:
            owner = psutil.Process(listener)
            command = tuple(owner.cmdline())
            executable = owner.exe()
            try:
                variables = owner.environ()
                capability = {
                    key: variables[key]
                    for key in CAPABILITY_VARIABLES.get(service, ())
                    if key in variables
                }
            except (OSError, psutil.Error):
                capability = {}
        except (OSError, psutil.Error):
            command, executable, capability = (), "", {}
        serves = "serve" in command and service in command
        if managed_pid is not None and listener in tree:
            mode = "managed"
        elif serves and any("host_runtime" in part or "dev.py" in part for part in command):
            mode = "foreground"
        else:
            mode = "foreign"
        return HostProcess(
            service,
            port,
            mode,
            managed_pid if mode == "managed" else listener,
            tuple(listeners),
            executable,
            command,
            capability,
            launcher if mode == "managed" else "",
        )


class Transcript:
    """The system-test terminal: everything it prints, kept for terminal-6-system-test.log."""

    def __init__(self, clock: Callable[[], datetime], echo: IO[str] | None = sys.stdout) -> None:
        self.clock = clock
        self.echo = echo
        self.lines: list[str] = []

    def say(self, line: str = "") -> None:
        for part in line.splitlines() or [""]:
            self.lines.append(part)
            if self.echo is not None:
                print(part, file=self.echo, flush=True)

    def command(
        self,
        display: str,
        result: CommandResult,
        *,
        started: datetime | None = None,
        summary: str | None = None,
    ) -> None:
        self.say(f"[{(started or self.clock()).strftime('%H:%M:%S')}] $ {display}")
        if summary is not None:
            self.say(summary)
        elif result.stdout.strip():
            self.say(result.stdout.rstrip())
        if result.stderr.strip():
            self.say(result.stderr.rstrip())
        self.say(f"(exit {result.returncode}, {result.duration_ms} ms)")
        self.say()

    def text(self) -> str:
        return "\n".join(self.lines) + "\n"


class Redactor:
    """Remove known secret values and secret-shaped values from evidence text."""

    def __init__(self, literals: Iterable[str]) -> None:
        self.literals = sorted({value for value in literals if len(value) >= 12}, key=len)[::-1]

    @classmethod
    def from_environment(cls, environment: Mapping[str, str], host_directory: Path) -> Redactor:
        literals = [
            value.strip()
            for name, value in environment.items()
            if SECRET_VARIABLE.search(name) and not name.endswith(("_FILE", "_PATH"))
        ]
        for path in sorted(host_directory.glob("*.token")):
            try:
                literals.append(path.read_text(encoding="utf-8").strip())
            except OSError:
                continue
        return cls(literals)

    def values(self, text: str) -> tuple[str, int]:
        count = 0
        for literal in self.literals:
            if literal in text:
                count += text.count(literal)
                text = text.replace(literal, "[redacted secret]")
        for pattern in SECRET_VALUES:
            text, replaced = pattern.subn(lambda match: match.group(1) + REDACTED_VALUE, text)
            count += replaced
        return text, count

    def bounded(self, text: str, max_bytes: int) -> tuple[str, int, int]:
        """Return redacted, ANSI-free text capped at ``max_bytes``, with drop and redact counts."""
        cleaned, values = self.values(text)
        bounded, dropped, lines = bound_log(cleaned, max_bytes=max_bytes)
        return bounded, dropped, values + lines

    def leaks(self, text: str) -> int:
        hits = sum(text.count(literal) for literal in self.literals)
        return hits + sum(
            1 for line in text.splitlines() if any(p.search(line) for p in SECRET_PATTERNS)
        )


class LocalSmoke(cloud_smoke.Smoke):
    """The cloud smoke cases against the local edge, logged into the system-test transcript."""

    def __init__(self, client: httpx.Client, *, base_url: str, transcript: Transcript) -> None:
        super().__init__(client, base_url=base_url)
        self.transcript = transcript
        self.request_ids: list[str] = []

    def record(self, result: cloud_smoke.CheckResult) -> cloud_smoke.CheckResult:
        self.results.append(result)
        request = f" ({result.method} {result.path})" if result.path else ""
        self.transcript.say(
            f"{'PASS' if result.passed else 'FAIL'} [{result.owner}] {result.name}{request}: "
            f"{result.detail}"
        )
        return result

    def request(
        self, method: str, path: str, *, timeout: float | None = None, **kwargs: Any
    ) -> httpx.Response:
        request_id = f"{REQUEST_PREFIX}-{uuid.uuid4().hex[:16]}"
        self.request_ids.append(request_id)
        headers = {"X-Request-ID": request_id, **kwargs.pop("headers", {})}
        return self.client.request(
            method,
            self.base_url + path,
            headers=headers,
            timeout=timeout if timeout is not None else httpx.USE_CLIENT_DEFAULT,
            **kwargs,
        )


@dataclass(slots=True)
class CaptureContext:
    """Everything the capture touches, injectable so the core runs offline in tests."""

    client: httpx.Client
    runner: CommandRunner
    processes: ProcessInspector
    host_status: Callable[[], list[dict[str, str]]]
    ai_probe: Callable[[], Mapping[str, Any]]
    redactor: Redactor
    clock: Callable[[], datetime]
    environment: Mapping[str, str]
    host_directory: Path
    output_directory: Path
    edge_url: str
    multi_agent_command: tuple[str, ...]
    decision: str = "reject"
    existing_run_id: str | None = None
    run_timeout: float = 600.0
    command_timeout: float = 120.0
    crud: bool = True
    echo: IO[str] | None = sys.stdout


class Capture:
    """Runs every observation in order and accumulates checks and report sections."""

    def __init__(self, context: CaptureContext) -> None:
        self.context = context
        self.transcript = Transcript(context.clock, context.echo)
        self.checks: list[Check] = []
        self.request_ids: list[str] = []

    # --- recording -------------------------------------------------------------------------

    def check(
        self, section: str, name: str, passed: bool, detail: str, owner: str = "shared"
    ) -> bool:
        self.checks.append(Check(section, name, passed, detail, owner))
        self.transcript.say(f"{'PASS' if passed else 'FAIL'} [{section}] {name}: {detail}")
        return passed

    def heading(self, title: str) -> None:
        self.transcript.say()
        self.transcript.say(f"== {title} ==")

    def command(
        self,
        display: str,
        argv: Sequence[str],
        timeout: float | None = None,
        summarise: Callable[[CommandResult], str] | None = None,
    ) -> CommandResult:
        """Run one terminal command; ``summarise`` replaces bulky machine output in the log."""
        started = self.context.clock()
        result = self.context.runner(argv, timeout or self.context.command_timeout)
        summary = summarise(result) if summarise is not None and result.returncode == 0 else None
        self.transcript.command(display, result, started=started, summary=summary)
        return result

    # --- sections --------------------------------------------------------------------------

    def source(self) -> dict[str, Any]:
        def git(*arguments: str) -> str:
            result = self.context.runner(("git", *arguments), 30)
            return result.stdout.strip() if result.returncode == 0 else ""

        # The evidence directory is excluded: an evidence refresh rewrites it while it runs.
        dirty = git("status", "--porcelain", "--", ".", EVIDENCE_PATHSPEC)
        return {
            "commit": git("rev-parse", "HEAD") or "unknown",
            "branch": git("rev-parse", "--abbrev-ref", "HEAD") or "unknown",
            "uncommitted_paths": len([line for line in dirty.splitlines() if line.strip()]),
            "compose_project": compose_project_name_from(self.context.environment),
            "edge_url": self.context.edge_url,
            "platform": f"{platform.system()} {platform.release()}",
            "python": platform.python_version(),
        }

    def containers(self, project: str) -> list[Container]:
        self.heading(f"Terminal 1: Compose project {project}")
        result = self.command(
            f"docker ps --all --filter label=com.docker.compose.project={project}",
            (
                "docker",
                "ps",
                "--all",
                "--filter",
                f"label=com.docker.compose.project={project}",
                "--format",
                "{{json .}}",
            ),
            summarise=lambda result: "\n".join(
                f"{c.name:<28} {c.service:<16} {c.state:<8} {c.status}"
                for c in parse_containers(result.stdout)
            ),
        )
        containers = parse_containers(result.stdout) if result.returncode == 0 else []
        self.check(
            "containers",
            "Docker reports the Compose project",
            result.returncode == 0 and bool(containers),
            f"{len(containers)} container(s) in project {project}"
            if result.returncode == 0
            else f"docker ps failed (exit {result.returncode}): {result.stderr.strip()[:160]}",
        )
        for container in containers:
            healthy = container.state == "running" and container.health not in {
                "unhealthy",
                "starting",
            }
            completed = container.state == "exited" and container.status.startswith("Exited (0)")
            self.check(
                "containers",
                f"{container.service} container",
                healthy or completed,
                f"{container.state}, {container.status}"
                + (" (one-shot service completed)" if completed else ""),
            )
        ai_containers = sorted(c.name for c in containers if c.service in AI_CONTAINER_NAMES)
        self.check(
            "containers",
            "No AI service runs in a container",
            not ai_containers,
            "Compose runs no AI-mode, MCP, RAG or Multi-Agent container"
            if not ai_containers
            else f"containerised AI services found: {', '.join(ai_containers)}",
        )
        return containers

    def host_services(self, containers: Sequence[Container]) -> list[dict[str, Any]]:
        self.heading("Terminals 2-5: host AI services")
        try:
            statuses = {entry["service"]: entry for entry in self.context.host_status()}
        except (RuntimeError, OSError, httpx.HTTPError) as exc:
            statuses = {}
            self.transcript.say(f"host status probe failed: {type(exc).__name__}: {exc}")
        published = " ".join(container.ports for container in containers)
        services: list[dict[str, Any]] = []
        for service in host_runtime.SERVICES:
            port = host_runtime.port_for(service, self.context.environment)
            facts = self.context.processes.describe(service, port)
            status = statuses.get(service, {})
            container_port = re.search(rf"[:\]]{port}->", published) is not None
            hosted = facts.mode in {"managed", "foreground"} and bool(facts.listener_pids)
            owner = (
                f"in the process tree of managed PID {facts.pid}"
                if facts.mode == "managed"
                else "a foreground host process"
            )
            proof = (
                f"listener PID {', '.join(map(str, facts.listener_pids))} on port {port} is "
                f"{owner}; executable {display_path(facts.executable)}; no container publishes "
                f"{port}"
                if hosted and not container_port
                else f"mode {facts.mode}; listeners {list(facts.listener_pids) or 'none'}"
                + ("; a container publishes this port" if container_port else "")
            )
            self.check(
                "host-services",
                f"{service} runs as a host process",
                hosted and not container_port,
                proof,
            )
            health = status.get("health", "unknown")
            self.check(
                "host-services",
                f"{service} is ready",
                health == "ready",
                f"{status.get('state', 'unknown')}, {health}"
                + (f" ({status['detail']})" if status.get("detail") else ""),
            )
            services.append(
                {
                    "service": service,
                    "terminal": HOST_TERMINALS[service].filename,
                    "port": port,
                    "url": status.get(
                        "url", host_runtime.local_url(service, self.context.environment)
                    ),
                    "mode": facts.mode,
                    "pid": facts.pid,
                    "listener_pids": list(facts.listener_pids),
                    "executable": display_path(facts.executable),
                    "launcher": display_path(facts.launcher),
                    "command": [display_path(part) for part in facts.command],
                    "state": status.get("state", "unknown"),
                    "health": health,
                    "detail": status.get("detail", ""),
                    "capability": dict(facts.capability),
                    "container_publishes_port": container_port,
                }
            )
        ai_mode = next((item for item in services if item["service"] == "ai-mode"), None)
        flags = ai_mode["capability"] if ai_mode else {}
        if flags:
            mcp_on = flags.get("AI_MODE_MCP_ENABLED") == "true"
            rag_on = flags.get("AI_MODE_RAG_ENABLED") == "true"
            mode = {(True, True): "combined", (True, False): "mcp", (False, True): "rag"}.get(
                (mcp_on, rag_on), "direct"
            )
            self.check(
                "host-services",
                "AI-mode capability mode is combined",
                mode == "combined",
                f"AI-mode process reports AI_MODE_MCP_ENABLED={flags.get('AI_MODE_MCP_ENABLED')}, "
                f"AI_MODE_RAG_ENABLED={flags.get('AI_MODE_RAG_ENABLED')} ({mode} mode)",
            )
        return services

    def edge(self) -> None:
        self.heading(f"System test: edge, features and CRUD through {self.context.edge_url}")
        smoke = LocalSmoke(
            self.context.client, base_url=self.context.edge_url, transcript=self.transcript
        )
        results = smoke.run(cloud_smoke.load_features(), expect_ai=True, crud=self.context.crud)
        self.request_ids.extend(smoke.request_ids)
        sections = {"frontend": "edge", "health": "edge", "ai": "edge", "crud": "crud"}
        for result in results:
            self.checks.append(
                Check(
                    sections.get(result.category, result.category),
                    result.name + (f" ({result.method} {result.path})" if result.path else ""),
                    result.passed,
                    result.detail,
                    result.owner,
                )
            )

    def data(self) -> dict[str, Any]:
        self.heading("System test: Feature 1 data inventory")
        base = f"{self.context.edge_url}/api/data-platform/v1"
        try:
            products = self._get(f"{base}/data-products").get("items", [])
            accepted = self._releases(base, "accepted")
            pending = [
                item for state in OPEN_RELEASE_STATES for item in self._releases(base, state)
            ]
        except (httpx.HTTPError, ValueError) as exc:
            self.check("data", "Feature 1 release inventory", False, f"{type(exc).__name__}: {exc}")
            return {"label": "unknown: the release inventory was unavailable", "datasets": []}
        current: dict[str, dict[str, Any]] = {}
        for item in accepted:
            current.setdefault(str(item.get("dataset_id")), item)
        datasets = []
        for product in products if isinstance(products, list) else []:
            dataset_id = str(product.get("dataset_id"))
            release = current.get(dataset_id)
            datasets.append(
                {
                    "dataset_id": dataset_id,
                    "accepted_release_id": release.get("id") if release else None,
                    "accepted_records": release.get("record_count") if release else None,
                    "kind": dataset_kind(dataset_id, release),
                    "open_releases": [
                        {
                            "id": item.get("id"),
                            "status": item.get("status"),
                            "records": item.get("record_count"),
                        }
                        for item in pending
                        if item.get("dataset_id") == dataset_id
                    ],
                }
            )
        label = data_label(datasets)
        self.check(
            "data",
            "Feature 1 release inventory read through the edge",
            True,
            f"{len(datasets)} registered dataset(s), {len(current)} accepted, "
            f"{len(pending)} awaiting a decision. Data: {label}",
            "student-1",
        )
        open_releases = [
            {key: item.get(key) for key in ("id", "dataset_id", "status", "record_count")}
            for item in pending
        ]
        return {"label": label, "datasets": datasets, "open_releases": open_releases}

    def _get(self, url: str, **params: Any) -> dict[str, Any]:
        response = self.context.client.get(
            url,
            params=params,
            headers={"X-Request-ID": f"{REQUEST_PREFIX}-{uuid.uuid4().hex[:16]}"},
        )
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, dict):
            raise ValueError(f"{url} did not return a JSON object")
        return value

    def _releases(self, base: str, status: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        offset: int | None = 0
        while offset is not None and len(items) < 1000:
            page = self._get(f"{base}/dataset-releases", status=status, limit=100, offset=offset)
            items.extend(item for item in page.get("items", []) if isinstance(item, dict))
            following = page.get("next_offset")
            offset = following if isinstance(following, int) and following > offset else None
        return items

    def ai_probe(self) -> dict[str, Any]:
        self.heading("System test: direct AI-mode, MCP, RAG and Multi-Agent probes")
        try:
            evidence = dict(self.context.ai_probe())
        except (RuntimeError, OSError, httpx.HTTPError) as exc:
            self.check(
                "ai-probe", "Direct host service probe", False, f"{type(exc).__name__}: {exc}"
            )
            return {"passed": False, "checks": []}
        for item in evidence.get("checks", []):
            if isinstance(item, dict):
                self.check(
                    "ai-probe",
                    f"{item.get('service')}: {item.get('check')}",
                    bool(item.get("passed")),
                    str(item.get("detail", "")),
                )
        return evidence

    def multi_agent(self, data: Mapping[str, Any]) -> dict[str, Any]:
        self.heading("System test: terminal Multi-Agent run (Feature 1 template)")
        base = self.context.multi_agent_command
        shown = "uv run multi-agent-server"
        summary: dict[str, Any] = {"template": F1_TEMPLATE, "decision_by": None}
        templates = self.command(f"{shown} templates --server", (*base, "templates", "--server"))
        self.check(
            "multi-agent",
            "Feature 1 template is registered on the running server",
            templates.returncode == 0 and F1_TEMPLATE in templates.stdout,
            f"exit {templates.returncode}; "
            + (
                "f1-release-readiness-review listed"
                if F1_TEMPLATE in templates.stdout
                else "not listed"
            ),
            "student-1",
        )
        run_id = self.context.existing_run_id
        if run_id is None:
            release = choose_release(data)
            if release is None:
                self.check(
                    "multi-agent", "A Feature 1 release to review", False, "no release found"
                )
                return summary
            summary["release"] = release
            payload = json.dumps(
                {
                    "release_id": release["id"],
                    "dataset_id": release["dataset_id"],
                    "reviewer_note": "Local deployment capture (capture_local_deployment.py)",
                },
                separators=(",", ":"),
            )
            started = self.command(
                f"{shown} run --template {F1_TEMPLATE} --input '{payload}' "
                f"--requested-by {CAPTURE_ACTOR} --follow --server",
                (
                    *base,
                    "run",
                    "--template",
                    F1_TEMPLATE,
                    "--input",
                    payload,
                    "--requested-by",
                    CAPTURE_ACTOR,
                    "--follow",
                    "--timeout",
                    str(int(self.context.run_timeout)),
                    "--server",
                ),
                timeout=self.context.run_timeout + 60,
            )
            match = RUN_ID.search(started.stdout)
            run_id = match.group(1) if match else None
            if run_id is None:
                self.check(
                    "multi-agent",
                    "Run started from the terminal",
                    False,
                    f"exit {started.returncode}; no run ID in the output",
                )
                return summary
        summary["run_id"] = run_id
        status = self._run_json(f"{shown} status {run_id} --server --json", ("status", run_id))
        state = str(status.get("state", "unknown"))
        if self.context.existing_run_id is None:
            self.check(
                "multi-agent",
                "Agents reached awaiting_human",
                state == "awaiting_human",
                f"run {run_id} is {state}",
            )
            if state == "awaiting_human":
                decided = self._run_json(
                    f"{shown} decide {run_id} --decision {self.context.decision} "
                    f"--note '{DECISION_NOTE}' --actor {CAPTURE_ACTOR} --server --json",
                    (
                        "decide",
                        run_id,
                        "--decision",
                        self.context.decision,
                        "--note",
                        DECISION_NOTE,
                        "--actor",
                        CAPTURE_ACTOR,
                    ),
                )
                state = str(decided.get("state", state))
                summary["decision_by"] = "scripted (this capture)"
        else:
            summary["decision_by"] = "a person in another terminal (--multi-agent-run-id)"
        history = self._run_json(f"{shown} history {run_id} --server --json", ("history", run_id))
        self.command(f"{shown} history {run_id} --server", (*base, "history", run_id, "--server"))
        transitions = [entry.get("to_state") for entry in history.get("history", [])]
        events = [entry.get("event") for entry in history.get("audit", [])]
        self.check(
            "multi-agent",
            "History records awaiting_human",
            "awaiting_human" in transitions,
            f"{len(transitions)} transition(s): {' -> '.join(map(str, transitions))}",
        )
        self.check(
            "multi-agent",
            "A human decision is recorded",
            "decision.recorded" in events,
            f"final state {state}; {len(events)} coordination event(s)",
        )
        export_directory = self.context.output_directory / EXPORT_DIRECTORY_NAME
        if export_directory.exists():
            shutil.rmtree(export_directory)
        exported = self.command(
            f"{shown} export {run_id} --out {display_path(str(export_directory))} --server",
            (*base, "export", run_id, "--out", str(export_directory), "--server"),
        )
        run_file = export_directory / "run.json"
        self.check(
            "multi-agent",
            "Run exported (run.json, history, audit, summary)",
            exported.returncode == 0 and run_file.is_file(),
            f"exit {exported.returncode}; {display_path(str(export_directory))}",
        )
        run = _json_file(run_file) or status
        summary.update(describe_run(run))
        summary["final_state"] = state if not run else run.get("state", state)
        summary["export_directory"] = display_path(str(export_directory))
        summary["transitions"] = transitions
        summary["audit_events"] = len(events)
        self.check(
            "multi-agent",
            "Agent provider recorded",
            bool(summary.get("provider")),
            f"{summary.get('provider_label', 'unknown')}",
        )
        return summary

    def _run_json(self, display: str, arguments: Sequence[str]) -> dict[str, Any]:
        def summarise(result: CommandResult) -> str:
            try:
                value = json.loads(result.stdout)
            except ValueError:
                return result.stdout.rstrip()
            state = value.get("state") if isinstance(value, dict) else None
            return (
                f"(JSON response, {len(result.stdout.encode('utf-8')):,} bytes; state {state}; "
                "the full document is in the export below)"
            )

        result = self.command(
            display,
            (*self.context.multi_agent_command, *arguments, "--server", "--json"),
            summarise=summarise,
        )
        try:
            value = json.loads(result.stdout) if result.returncode == 0 else {}
        except ValueError:
            value = {}
        return value if isinstance(value, dict) else {}

    # --- logs ------------------------------------------------------------------------------

    def log_offsets(self) -> dict[str, int]:
        offsets = {}
        for service in host_runtime.SERVICES:
            path = self.context.host_directory / f"{service}.log"
            offsets[service] = path.stat().st_size if path.exists() else 0
        return offsets

    def host_log(self, service: str, offset: int, window: str) -> tuple[str, str]:
        """Return a host service's terminal text for the window and its source path."""
        path = self.context.host_directory / f"{service}.log"
        terminal = HOST_TERMINALS[service]
        before: list[str] = []
        during = ""
        if path.exists():
            with path.open("rb") as stream:
                stream.seek(max(0, offset - CONTEXT_BYTES))
                before = (
                    stream.read(offset - max(0, offset - CONTEXT_BYTES))
                    .decode("utf-8", "replace")
                    .splitlines()[-CONTEXT_LINES:]
                )
                stream.seek(offset)
                during = stream.read().decode("utf-8", "replace")
        source = display_path(str(path))
        if not during:
            answered = [
                check
                for check in self.checks
                if check.section == "ai-probe" and check.name.startswith(f"{service}:")
            ]
            during = (
                f"({service} wrote no log lines during the capture window. It answered "
                f"{len(answered)} direct probe(s) from terminal 6 in this window, "
                f"{sum(check.passed for check in answered)} passed; see "
                "terminal-6-system-test.log.)\n"
            )
        text = (
            f"# Terminal {terminal.number}: {terminal.title}\n"
            f"# Equivalent foreground command: {terminal.command}\n"
            f"# Source: {source} from byte {offset}\n"
            f"--- last {len(before)} line(s) before the capture window ---\n"
            + "".join(f"{line}\n" for line in before)
            + f"--- capture window {window} ---\n"
            + during
        )
        return text, source

    def compose_log(self, containers: Sequence[Container], since: datetime) -> str:
        stamp = since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        lines: list[tuple[str, str]] = []
        for container in containers:
            result = self.context.runner(
                ("docker", "logs", "--since", stamp, "--timestamps", container.name), 60
            )
            for line in (result.stdout + "\n" + result.stderr).splitlines():
                if not line.strip():
                    continue
                stamp_part, _, message = line.partition(" ")
                lines.append((stamp_part, f"{container.service:<16} | {stamp_part} {message}"))
        lines.sort(key=lambda item: item[0])
        return "\n".join(text for _, text in lines) + ("\n" if lines else "")


def compose_project_name_from(environment: Mapping[str, str]) -> str:
    return environment.get("COMPOSE_PROJECT_NAME", "").strip() or compose_project_name()


def parse_containers(text: str) -> list[Container]:
    containers = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except ValueError:
            continue
        labels = dict(
            part.split("=", 1) for part in str(item.get("Labels", "")).split(",") if "=" in part
        )
        status = str(item.get("Status", ""))
        health = str(item.get("HealthStatus", "") or "")
        if not health:
            found = re.search(r"\((healthy|unhealthy|health: starting)\)", status)
            health = found.group(1).replace("health: ", "") if found else "none"
        containers.append(
            Container(
                name=str(item.get("Names", "")),
                service=labels.get("com.docker.compose.service", str(item.get("Names", ""))),
                state=str(item.get("State", "")),
                status=status,
                health=health,
                ports=str(item.get("Ports", "")),
            )
        )
    return sorted(containers, key=lambda container: container.service)


def dataset_kind(dataset_id: str, release: Mapping[str, Any] | None) -> str:
    if release is None:
        return "not loaded"
    if str(release.get("id", "")).startswith(SEEDED_RELEASE_PREFIX):
        return "seeded demonstration baseline"
    if dataset_id in SYNTHETIC_DATASETS:
        return "synthetic fixture"
    return "published official release"


def data_label(datasets: Sequence[Mapping[str, Any]]) -> str:
    """The labelling rule: seeded demonstration baseline unless record counts show otherwise."""
    real = [item for item in datasets if item["kind"] == "published official release"]
    if not real:
        return "seeded demonstration baseline (no published official release is accepted)"
    total = sum(int(item.get("accepted_records") or 0) for item in real)
    names = ", ".join(
        f"{item['dataset_id']} ({int(item.get('accepted_records') or 0):,})" for item in real
    )
    label = f"includes published official releases: {total:,} records in {names}"
    seeded = [
        item["dataset_id"]
        for item in datasets
        if item["kind"] in {"seeded demonstration baseline", "synthetic fixture"}
    ]
    if seeded:
        label += f"; still seeded or synthetic: {', '.join(seeded)}"
    return label


def choose_release(data: Mapping[str, Any]) -> dict[str, Any] | None:
    """A release still awaiting a decision when one exists, else an accepted release."""
    for item in data.get("open_releases", []) or []:
        if item.get("id") and item.get("dataset_id"):
            return {
                "id": item["id"],
                "dataset_id": item["dataset_id"],
                "status": item.get("status"),
                "records": item.get("record_count"),
            }
    for dataset in data.get("datasets", []) or []:
        if dataset.get("accepted_release_id"):
            return {
                "id": dataset["accepted_release_id"],
                "dataset_id": dataset["dataset_id"],
                "status": "accepted",
                "records": dataset.get("accepted_records"),
            }
    return None


def describe_run(run: Mapping[str, Any]) -> dict[str, Any]:
    """Provider, models, recommendation and decisions from a WorkflowRun document."""
    if not run:
        return {}
    produced = []
    for key in ("plan", "worker_output", "review"):
        section = run.get(key)
        if isinstance(section, dict) and isinstance(section.get("produced_by"), dict):
            produced.append(section["produced_by"])
    providers = sorted({str(item.get("provider")) for item in produced if item.get("provider")})
    models = sorted({str(item.get("model")) for item in produced if item.get("model")})
    fallback = any(item.get("fallback") for item in produced)
    review = run.get("review") if isinstance(run.get("review"), dict) else {}
    decisions = [
        {
            key: item.get(key)
            for key in ("decision", "actor", "decided_at", "resulting_state", "round")
        }
        for item in run.get("decisions", []) or []
        if isinstance(item, dict)
    ]
    provider = "/".join(providers)
    label = (
        "deterministic (rule-based, no model calls)"
        if providers == ["deterministic"]
        else (f"real model provider {provider} ({', '.join(models)})" if provider else "unknown")
    )
    if fallback:
        label += "; at least one stage fell back to the deterministic provider"
    return {
        "run_id": run.get("id"),
        "provider": provider,
        "provider_mode": run.get("provider_mode"),
        "models": models,
        "provider_label": label,
        "recommendation": (review or {}).get("recommendation"),
        "decisions": decisions,
        "rounds": run.get("round"),
        "input": run.get("input"),
    }


def display_path(value: str) -> str:
    """Show checkout paths relative to the repository so reports carry no home directory."""
    if not value:
        return value
    try:
        return Path(value).resolve().relative_to(REPOSITORY_ROOT.resolve()).as_posix()
    except (ValueError, OSError):
        home = str(Path.home())
        return value.replace(home, "~") if home and home in value else value


def _json_file(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def correlated(text: str, needles: Sequence[str]) -> int:
    return sum(1 for line in text.splitlines() if any(needle in line for needle in needles))


def capture(context: CaptureContext) -> dict[str, Any]:
    """Run the whole capture and write every evidence file; return the JSON report."""
    output = context.output_directory
    output.mkdir(parents=True, exist_ok=True)
    started = context.clock()
    job = Capture(context)
    job.transcript.say(f"# Terminal 6: {TERMINALS[5].title}")
    job.transcript.say(f"# Command: {TERMINALS[5].command}")
    job.transcript.say(f"# Started {started.isoformat(timespec='seconds')}")
    offsets = job.log_offsets()
    source = job.source()
    job.transcript.say(
        f"Commit {source['commit'][:12]} on {source['branch']}, Compose project "
        f"{source['compose_project']}, edge {context.edge_url}"
    )
    containers = job.containers(source["compose_project"])
    hosts = job.host_services(containers)
    job.edge()
    data = job.data()
    probe = job.ai_probe()
    multi_agent = job.multi_agent(data)
    finished = context.clock()
    window = f"{started.isoformat(timespec='seconds')} to {finished.isoformat(timespec='seconds')}"
    needles = [REQUEST_PREFIX, *([multi_agent["run_id"]] if multi_agent.get("run_id") else [])]

    terminals: list[dict[str, Any]] = []
    compose_text = (
        f"# Terminal 1: {TERMINALS[0].title} (project {source['compose_project']})\n"
        f"# Command: {TERMINALS[0].command}\n"
        f"# Source: docker logs --since {started.isoformat(timespec='seconds')} --timestamps for "
        f"{len(containers)} container(s), merged by timestamp\n"
        "--- containers at capture start ---\n"
        + "\n".join(f"{c.service:<16} {c.state:<8} {c.status}" for c in containers)
        + f"\n--- capture window {window} ---\n"
        + (job.compose_log(containers, started - timedelta(seconds=1)) or "(no container output)\n")
    )
    terminals.append(
        write_terminal(
            context, TERMINALS[0], compose_text, MAX_COMPOSE_LOG_BYTES, needles, "docker logs"
        )
    )
    for service in host_runtime.SERVICES:
        text, log_source = job.host_log(service, offsets[service], window)
        terminals.append(
            write_terminal(
                context,
                HOST_TERMINALS[service],
                text,
                MAX_TERMINAL_LOG_BYTES,
                needles,
                log_source,
            )
        )

    report: dict[str, Any] = {
        "schema_version": 1,
        "tool": "scripts/capture_local_deployment.py",
        "requirement": "R2-41 local deployment report with multi-terminal system-test logs",
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": finished.isoformat(timespec="seconds"),
        "source": source,
        "containers": [asdict(container) for container in containers],
        "host_services": hosts,
        "data": data,
        "ai_probe": {"passed": probe.get("passed"), "services": probe.get("services")},
        "multi_agent": multi_agent,
        "terminals": terminals,
        "log_observations": log_observations(
            {
                terminal["file"]: (output / terminal["file"]).read_text(encoding="utf-8")
                for terminal in terminals
            }
        ),
    }
    for terminal in terminals:
        job.check(
            "evidence",
            f"{terminal['file']} written",
            terminal["bytes"] > 0,
            f"{terminal['bytes']:,} bytes, {terminal['correlated_lines']} line(s) carry this "
            f"capture's request or run IDs, {terminal['redactions']} redaction(s)",
        )
    job.transcript.say()
    job.transcript.say(f"Finished {finished.isoformat(timespec='seconds')}")
    system = write_terminal(
        context, TERMINALS[5], job.transcript.text(), MAX_TERMINAL_LOG_BYTES, needles, "this script"
    )
    terminals.append(system)
    export_hits = sanitise_tree(context.redactor, output / EXPORT_DIRECTORY_NAME)
    leaks = scan_tree(context.redactor, output)
    job.checks.append(
        Check(
            "evidence",
            "No secret values in the evidence folder",
            leaks == 0,
            f"{export_hits} value(s) redacted in the export; {leaks} secret-shaped value(s) remain",
        )
    )
    report["checks"] = [asdict(check) for check in job.checks]
    report["summary"] = summarise(job.checks)
    report["passed"] = report["summary"]["failed"] == 0
    report["verdict"] = "PASSED" if report["passed"] else "FAILED"
    (output / f"{REPORT_NAME}.json").write_text(json.dumps(report, indent=2) + "\n", "utf-8")
    (output / f"{REPORT_NAME}.md").write_text(render_markdown(report), "utf-8")
    return report


EXCEPTION_LINE = re.compile(r"^(?:[A-Za-z_][\w.]*\.)?[A-Z]\w*(?:Error|Exception):")
ERROR_LEVEL = re.compile(r"\"level\"\s*:\s*\"(?:error|critical)\"", re.IGNORECASE)


def log_observations(texts: Mapping[str, str]) -> list[dict[str, Any]]:
    """Tracebacks and error-level lines each server logged in the window (not pass/fail)."""
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for filename, text in texts.items():
        window = text.split("--- capture window", 1)[-1]
        default = filename.removesuffix(".log").split("-", 2)[-1]
        for line in window.splitlines()[1:]:
            source, separator, rest = line.partition(" | ")
            name, message = (
                (source.strip(), rest.partition(" ")[2]) if separator else (default, line)
            )
            message = message.strip()
            traceback = message.startswith("Traceback (most recent call last)")
            error = ERROR_LEVEL.search(message) is not None
            exception = EXCEPTION_LINE.match(message) is not None
            if not (traceback or error or exception):
                continue
            entry = found.setdefault(
                (filename, name),
                {"file": filename, "source": name, "tracebacks": 0, "error_lines": 0, "last": ""},
            )
            entry["tracebacks"] += traceback
            entry["error_lines"] += error
            if exception or error:
                entry["last"] = message[:240]
    return list(found.values())


def write_terminal(
    context: CaptureContext,
    terminal: Terminal,
    text: str,
    max_bytes: int,
    needles: Sequence[str],
    source: str,
) -> dict[str, Any]:
    bounded, dropped, redactions = context.redactor.bounded(text, max_bytes)
    if dropped:
        bounded = (
            f"[{dropped:,} earlier bytes dropped to keep this log under {max_bytes:,} bytes]\n"
            + bounded
        )
    (context.output_directory / terminal.filename).write_text(bounded, encoding="utf-8")
    return {
        "number": terminal.number,
        "title": terminal.title,
        "command": terminal.command,
        "file": terminal.filename,
        "source": source,
        "bytes": len(bounded.encode("utf-8")),
        "dropped_bytes": dropped,
        "redactions": redactions,
        "correlated_lines": correlated(bounded, needles),
    }


def sanitise_tree(redactor: Redactor, directory: Path) -> int:
    """Redact secret values in exported files in place; return how many were replaced."""
    replaced = 0
    for path in sorted(directory.rglob("*")) if directory.is_dir() else []:
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            cleaned, count = redactor.values(text)
            if count:
                path.write_text(cleaned, encoding="utf-8")
                replaced += count
    return replaced


def scan_tree(redactor: Redactor, directory: Path) -> int:
    hits = 0
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.suffix in {".log", ".md", ".json", ".jsonl"}:
            hits += redactor.leaks(path.read_text(encoding="utf-8", errors="replace"))
    return hits


def summarise(checks: Sequence[Check]) -> dict[str, Any]:
    sections: dict[str, dict[str, int]] = {}
    for check in checks:
        counts = sections.setdefault(check.section, {"passed": 0, "failed": 0})
        counts["passed" if check.passed else "failed"] += 1
    return {
        "total": len(checks),
        "passed": sum(check.passed for check in checks),
        "failed": sum(not check.passed for check in checks),
        "by_section": sections,
    }


def _cell(value: object) -> str:
    return str(value if value is not None else "-").replace("|", "\\|").replace("\n", " ")


SECTION_TITLES = {
    "containers": "Compose containers",
    "host-services": "Host AI services",
    "edge": "Edge, frontends and health",
    "crud": "CRUD round trips",
    "data": "Data",
    "ai-probe": "Direct AI probes",
    "multi-agent": "Multi-Agent terminal run",
    "evidence": "Evidence files",
}


def render_markdown(report: Mapping[str, Any]) -> str:
    source = report["source"]
    summary = report["summary"]
    multi = report["multi_agent"]
    lines = [
        "# Local deployment report",
        "",
        f"**Verdict: {report['verdict']}**, {summary['passed']} of {summary['total']} checks "
        "passed. Generated by `scripts/capture_local_deployment.py` against the running local "
        "stack; nothing in this file is written by hand.",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Captured | {report['started_at']} to {report['finished_at']} |",
        f"| Commit | `{source['commit']}` on `{source['branch']}` "
        f"({source['uncommitted_paths']} uncommitted path(s) outside `docs/release-2/evidence` "
        "at capture) |",
        f"| Compose project | `{source['compose_project']}` |",
        f"| Edge | {source['edge_url']} |",
        f"| Host | {source['platform']}, Python {source['python']} |",
        f"| Data | {report['data'].get('label')} |",
        f"| Multi-Agent agents | {multi.get('provider_label', 'not run')} |",
        "",
    ]
    failures = [check for check in report["checks"] if not check["passed"]]
    lines += ["## Failures", ""]
    if failures:
        lines += [
            f"- **{_cell(check['section'])}** {_cell(check['name'])}: {_cell(check['detail'])}"
            for check in failures
        ]
    else:
        lines.append("None. Every check passed.")
    lines += [
        "",
        "## Terminals",
        "",
        "Each server ran as its own process and wrote its own log; each log below is what that "
        "server wrote during the capture window (plus a few lines of context before it). "
        "*managed* means `ai start` ran it in the background; *foreground* means it ran in its "
        "own terminal with the command shown. See [README.md](README.md) for running each one "
        "in a separate terminal.",
        "",
        "| # | Terminal | Ran as | Foreground command | Log | Bytes "
        "| Lines with this capture's IDs |",
        "|---|---|---|---|---|---|---|",
    ]
    # A managed service was started by `ai start` in the background; its foreground command is
    # the equivalent one-terminal way to run it, not what produced this log.
    modes = {host["terminal"]: host["mode"] for host in report["host_services"]}
    for terminal in sorted(report["terminals"], key=lambda item: item["number"]):
        ran_as = modes.get(terminal["file"], "foreground")
        lines.append(
            f"| {terminal['number']} | {terminal['title']} | {ran_as} | "
            f"`{terminal['command']}` | [{terminal['file']}]({terminal['file']}) | "
            f"{terminal['bytes']:,} | {terminal['correlated_lines']} |"
        )
    lines += [
        "",
        "## Compose containers",
        "",
        "| Service | Container | State | Health | Status | Ports |",
        "|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {c['service']} | {c['name']} | {c['state']} | {c['health']} | {_cell(c['status'])} "
        f"| {_cell(c['ports']) or '-'} |"
        for c in report["containers"]
    ]
    lines += [
        "",
        "## Host AI services (not containerised)",
        "",
        "| Service | Port | Mode | Launcher PID | Listener PID | Ready | Interpreter "
        "| Capability |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for host in report["host_services"]:
        capability = ", ".join(f"{k}={v}" for k, v in host["capability"].items()) or "-"
        ready = host["health"] + (f" ({host['detail']})" if host["detail"] else "")
        interpreter = host["executable"] + (
            f" (launched as {host['launcher']})"
            if host.get("launcher") and host["launcher"] != host["executable"]
            else ""
        )
        lines.append(
            f"| {host['service']} | {host['port']} | {host['mode']} | {_cell(host['pid'])} | "
            f"{', '.join(map(str, host['listener_pids'])) or '-'} | {_cell(ready)} "
            f"| `{_cell(interpreter)}` | {_cell(capability)} |"
        )
    lines += [
        "",
        "A service counts as a host process when the operating system reports its listening "
        "socket owned by the launcher's PID or one of its children, the process is a host "
        "Python interpreter (on Windows the checkout's `.venv` launcher runs the base interpreter "
        "as a child), and no container of the Compose project publishes the port. `managed` "
        "means `ai start` launched it; `foreground` means a terminal runs it with `serve`.",
        "",
        "## Multi-Agent terminal run",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Run ID | `{multi.get('run_id', '-')}` |",
        f"| Template | `{multi.get('template')}` |",
        f"| Input | `{_cell(json.dumps(multi.get('input')) if multi.get('input') else '-')}` |",
        f"| Agents | {_cell(multi.get('provider_label', '-'))} |",
        f"| Transitions | {_cell(' -> '.join(map(str, multi.get('transitions', []))) or '-')} |",
        f"| Reviewer recommendation | {_cell(multi.get('recommendation'))} |",
        f"| Decision made by | {_cell(multi.get('decision_by'))} |",
        f"| Final state | {_cell(multi.get('final_state'))} |",
        f"| Export | [{multi.get('export_directory', '-')}/]({EXPORT_DIRECTORY_NAME}/summary.md) |",
        "",
    ]
    for decision in multi.get("decisions", []) or []:
        lines.append(
            f"- Round {decision.get('round')}: `{decision.get('decision')}` by "
            f"{decision.get('actor')} at {decision.get('decided_at')} -> "
            f"{decision.get('resulting_state')}"
        )
    observations = report.get("log_observations") or []
    lines += [
        "",
        "## Log observations",
        "",
        "Tracebacks and error-level lines the servers logged during the window. They are not "
        "checks and do not change the verdict, but they are shown so nothing is hidden.",
        "",
    ]
    if observations:
        lines += [
            "| Log | Source | Tracebacks | Error lines | Last error |",
            "|---|---|---|---|---|",
        ]
        lines += [
            f"| [{item['file']}]({item['file']}) | {item['source']} | {item['tracebacks']} | "
            f"{item['error_lines']} | {_cell(item['last'] or '-')} |"
            for item in observations
        ]
    else:
        lines.append("None.")
    lines += ["", "## Data", "", f"Label: **{report['data'].get('label')}**", ""]
    datasets = report["data"].get("datasets", [])
    if datasets:
        lines += [
            "| Dataset | Accepted records | Kind | Awaiting a decision |",
            "|---|---|---|---|",
        ]
        for item in datasets:
            records = item.get("accepted_records")
            lines.append(
                f"| {item['dataset_id']} | {f'{records:,}' if isinstance(records, int) else '-'} "
                f"| {item['kind']} | {len(item.get('open_releases', []))} |"
            )
    lines += ["", "## All checks", ""]
    for section, title in SECTION_TITLES.items():
        rows = [check for check in report["checks"] if check["section"] == section]
        if not rows:
            continue
        lines += [f"### {title}", "", "| Result | Owner | Check | Detail |", "|---|---|---|---|"]
        lines += [
            f"| {'PASS' if c['passed'] else 'FAIL'} | {c['owner']} | {_cell(c['name'])} | "
            f"{_cell(c['detail'])} |"
            for c in rows
        ]
        lines.append("")
    lines += [
        "Logs are ANSI-free, size-capped and have known service tokens, provider keys and "
        "secret-shaped values redacted. CRUD records are created through each owning feature's "
        "public API through the edge and deleted again.",
        "",
    ]
    return "\n".join(lines)


# --- command line --------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIRECTORY)
    parser.add_argument(
        "--edge-url",
        default=None,
        help="Shared edge (default http://localhost:$PROPERTYSCOPE_SHARED_PORT)",
    )
    parser.add_argument(
        "--decision",
        choices=("approve", "reject"),
        default="reject",
        help="Scripted decision recorded on the Multi-Agent run (it publishes nothing either way)",
    )
    parser.add_argument(
        "--multi-agent-run-id",
        default=None,
        help="Capture a run a person already decided in another terminal instead of starting one",
    )
    parser.add_argument("--run-timeout", type=float, default=600.0, help="Seconds for the agents")
    parser.add_argument("--no-crud", action="store_true", help="Skip the CRUD round trips")
    parser.add_argument("--timeout", type=float, default=30.0, help="Per-request timeout (s)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    from scripts import dev

    dev._load_development_environment(None)
    environment = dict(os.environ)
    shared_port = environment.get("PROPERTYSCOPE_SHARED_PORT", "").strip() or "5100"
    edge_url = (arguments.edge_url or f"http://localhost:{shared_port}").rstrip("/")
    with httpx.Client(
        timeout=arguments.timeout,
        follow_redirects=False,
        headers={"User-Agent": "propertyscope-local-deployment-capture/1"},
    ) as client:
        context = CaptureContext(
            client=client,
            runner=run_command,
            processes=PsutilInspector(host_runtime.HOST_DIRECTORY),
            host_status=lambda: host_runtime.status(environment, probe=True),
            ai_probe=lambda: _probe(environment),
            redactor=Redactor.from_environment(environment, host_runtime.HOST_DIRECTORY),
            clock=lambda: datetime.now(UTC),
            environment=environment,
            host_directory=host_runtime.HOST_DIRECTORY,
            output_directory=arguments.output_dir,
            edge_url=edge_url,
            multi_agent_command=(sys.executable, "-m", "multi_agent_server.cli"),
            decision=arguments.decision,
            existing_run_id=arguments.multi_agent_run_id,
            run_timeout=arguments.run_timeout,
            crud=not arguments.no_crud,
        )
        report = capture(context)
    summary = report["summary"]
    print(
        f"\n{report['verdict']}: {summary['passed']}/{summary['total']} checks passed; "
        f"report in {display_path(str(arguments.output_dir / (REPORT_NAME + '.md')))}",
        flush=True,
    )
    return 0 if report["passed"] else 1


def _probe(environment: Mapping[str, str]) -> Mapping[str, Any]:
    from scripts.release1_probe import probe

    return probe(environment, request_id_prefix=REQUEST_PREFIX)


if __name__ == "__main__":
    raise SystemExit(main())
