"""Local deployment capture against fakes: no Docker, network, model key or real processes."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from scripts import capture_local_deployment as capture_module
from scripts.capture_local_deployment import (
    CaptureContext,
    CommandResult,
    HostProcess,
    Redactor,
    capture,
    choose_release,
    data_label,
    describe_run,
    parse_containers,
)
from scripts.devtools import host_runtime

TOKEN = "Tk_" + "a" * 40
PROVIDER_KEY = "sk-" + "b" * 32
RUN_ID = "11111111-2222-4333-8444-555555555555"
SEEDED = "60000000-0000-0000-0000-000000000001"
REAL = "a7078066-1bde-4b31-8b4d-4acab03939e6"
CANDIDATE = "cb188a6e-613f-4f4e-b7b0-b827dd573869"
SERVICES = (
    "f1-backend",
    "f1-frontend",
    "f1-runner",
    "shared-frontend",
)


def _container(service: str, *, state: str = "running", health: str = "healthy") -> str:
    labels = f"com.docker.compose.project=ps-dev,com.docker.compose.service={service}"
    ports = "127.0.0.1:5100->8080/tcp" if service == "shared-frontend" else "5201/tcp"
    status = "Up 2 minutes" + (f" ({health})" if health != "none" else "")
    return json.dumps(
        {
            "Names": f"ps-dev-{service}-1",
            "Labels": labels,
            "State": state,
            "Status": status,
            "HealthStatus": "" if health == "none" else health,
            "Ports": ports,
        }
    )


class FakeEdge:
    """Shared edge with feature pages, health, CRUD collections and Feature 1 releases."""

    def __init__(self, *, accepted: Sequence[dict[str, Any]], open_: Sequence[dict[str, Any]]):
        self.accepted = list(accepted)
        self.open = list(open_)
        self.store: dict[str, dict[str, Any]] = {}
        self.request_ids: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.request_ids.append(request.headers.get("X-Request-ID", ""))
        if request.method == "GET" and (path == "/" or path.startswith("/features/")):
            return httpx.Response(
                200, text="<title>PropertyScope</title>", headers={"content-type": "text/html"}
            )
        if path == "/healthz":
            return httpx.Response(200, text="ok")
        if path.startswith("/api/shared-health/"):
            return httpx.Response(200, json={"status": "healthy"})
        if path.endswith("/data-products"):
            return httpx.Response(
                200, json={"items": [{"dataset_id": "gnaf-nsw"}, {"dataset_id": "nsw-psi-sales"}]}
            )
        if path.endswith("/dataset-releases"):
            status = request.url.params["status"]
            items = self.accepted if status == "accepted" else []
            items = items + [item for item in self.open if item["status"] == status]
            return httpx.Response(200, json={"items": items, "next_offset": None})
        if path.endswith("/validate"):
            return httpx.Response(200, json={"state": "verified"})
        if path.endswith("/properties/search"):
            return httpx.Response(200, json={"items": []})
        if request.method == "POST":
            identifier = str(uuid.uuid4())
            body = json.loads(request.content)
            self.store[f"{path}/{identifier}"] = {"id": identifier, **body, "version": 1}
            wrapper = {"sources": "source", "suburb-comparisons": "comparison"}.get(
                path.rsplit("/", 1)[-1]
            )
            item = self.store[f"{path}/{identifier}"]
            return httpx.Response(201, json={wrapper: item} if wrapper else item)
        if path in self.store:
            if request.method == "DELETE":
                del self.store[path]
                return httpx.Response(204)
            if request.method == "PUT":
                body = json.loads(request.content)
                previous = self.store[path]
                self.store[path] = {**body, "id": previous["id"], "version": body["version"] + 1}
            item = self.store[path]
            collection = path.rsplit("/", 2)[-2]
            wrapper = {"sources": "source", "suburb-comparisons": "comparison"}.get(collection)
            return httpx.Response(200, json={wrapper: item} if wrapper else item)
        return httpx.Response(404, json={"code": "not_found"})


class FakeRunner:
    """Answers git, docker and multi-agent-server commands like the real tools would."""

    def __init__(self, *, containers: Sequence[str], reach_human: bool = True) -> None:
        self.containers = containers
        self.reach_human = reach_human
        self.calls: list[tuple[str, ...]] = []
        self.decided: str | None = None

    def __call__(self, argv: Sequence[str], timeout: float) -> CommandResult:
        command = tuple(argv)
        self.calls.append(command)
        if command[0] == "git":
            answers = {
                "HEAD": "0123456789abcdef0123456789abcdef01234567",  # pragma: allowlist secret
                "--abbrev-ref": "release-2/wrap-up",
            }
            if command[1] == "status":
                return CommandResult(0, " M scripts/x.py\n", "")
            return CommandResult(0, answers.get(command[2], answers["HEAD"]) + "\n", "")
        if command[:2] == ("docker", "ps"):
            return CommandResult(0, "\n".join(self.containers) + "\n", "")
        if command[:2] == ("docker", "logs"):
            name = command[-1]
            return CommandResult(
                0,
                f"2026-10-16T08:00:01.000000000Z {name} GET /health 200 "
                f"request_id=local-deploy-abc Authorization: Bearer {TOKEN}\n",
                "2026-10-16T08:00:00.500000000Z \x1b[32mstarted\x1b[0m\n",
            )
        return self._multi_agent(command)

    def _multi_agent(self, command: tuple[str, ...]) -> CommandResult:
        action = command[3]
        if action == "templates":
            return CommandResult(0, "f1-release-readiness-review v1 [student-1] Release\n", "")
        if action == "run":
            assert "--server" in command
            return CommandResult(0, f"Run {RUN_ID} started; following the agents...\n", "")
        if action == "status":
            state = "awaiting_human" if self.reach_human else "failed"
            return CommandResult(0, json.dumps({"id": RUN_ID, "state": state}), "")
        if action == "decide":
            self.decided = command[command.index("--decision") + 1]
            return CommandResult(0, json.dumps({"id": RUN_ID, "state": "rejected"}), "")
        if action == "history":
            if "--json" not in command:
                return CommandResult(0, f"Run {RUN_ID} is rejected: 4 transition(s)\n", "")
            states = ["planning", "working", "reviewing"]
            if self.reach_human:
                states += ["awaiting_human", "rejected"]
            audit = [{"event": "run.created"}]
            if self.decided:
                audit.append({"event": "decision.recorded"})
            return CommandResult(
                0,
                json.dumps(
                    {
                        "history": [{"to_state": state} for state in states],
                        "audit": audit,
                    }
                ),
                "",
            )
        if action == "export":
            out = Path(command[command.index("--out") + 1])
            out.mkdir(parents=True)
            run = _run_document(state="rejected")
            (out / "run.json").write_text(json.dumps(run), encoding="utf-8")
            (out / "summary.md").write_text(f"leaked {PROVIDER_KEY}\n", encoding="utf-8")
            return CommandResult(0, f"{out.as_posix()}/run.json\n", "")
        raise AssertionError(f"unexpected command {command}")


def _run_document(*, state: str, provider: str = "openai") -> dict[str, Any]:
    produced = {"provider": provider, "model": "gpt-test", "fallback": False}
    return {
        "id": RUN_ID,
        "state": state,
        "round": 1,
        "provider_mode": "model",
        "input": {"release_id": CANDIDATE},
        "plan": {"produced_by": produced},
        "worker_output": {"produced_by": produced},
        "review": {"produced_by": produced, "recommendation": "approve"},
        "decisions": [
            {
                "decision": "reject",
                "actor": "local-deployment-capture",
                "decided_at": "2026-10-16T08:01:00Z",
                "resulting_state": "rejected",
                "round": 1,
            }
        ],
    }


class FakeProcesses:
    def __init__(self, modes: dict[str, str] | None = None) -> None:
        self.modes = modes or {}

    def describe(self, service: str, port: int) -> HostProcess:
        mode = self.modes.get(service, "managed")
        if mode == "stopped":
            return HostProcess(service, port, "stopped")
        capability = (
            {"AI_MODE_MCP_ENABLED": "true", "AI_MODE_RAG_ENABLED": "true"}
            if service == "ai-mode"
            else {}
        )
        return HostProcess(
            service,
            port,
            mode,
            pid=1000 + port,
            listener_pids=(2000 + port,),
            executable="C:/Python/python.exe",
            command=("python", "-m", "scripts.devtools.host_runtime", "serve", service),
            capability=capability,
        )


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 16, 8, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


def _host_logs(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for service in host_runtime.SERVICES:
        (directory / f"{service}.log").write_text(f"{service} old line\n", encoding="utf-8")
    (directory / "multi-agent.token").write_text(TOKEN, encoding="utf-8")


def _context(
    tmp_path: Path,
    *,
    runner: FakeRunner,
    edge: FakeEdge,
    processes: FakeProcesses | None = None,
    health: str = "ready",
    run_id: str | None = None,
    crud: bool = True,
) -> CaptureContext:
    host = tmp_path / "host"
    _host_logs(host)

    def append_logs() -> list[dict[str, str]]:
        # Servers write while the capture runs; the window must contain these lines.
        with (host / "multi-agent.log").open("a", encoding="utf-8") as stream:
            stream.write(f'{{"run_id": "{RUN_ID}", "path": "/runs"}}\n')
        with (host / "ai-mode.log").open("a", encoding="utf-8") as stream:
            stream.write(f"x-propertyscope-ai-token: {TOKEN}\n")
        return [
            {"service": service, "state": "running", "health": health, "url": "http://h"}
            for service in host_runtime.SERVICES
        ]

    probe = {
        "passed": True,
        "services": {"mcp": "http://127.0.0.1:5011/mcp"},
        "checks": [{"service": "mcp", "check": "tools listed", "passed": True, "detail": "29"}],
    }
    return CaptureContext(
        client=httpx.Client(transport=httpx.MockTransport(edge)),
        runner=runner,
        processes=processes or FakeProcesses(),
        host_status=append_logs,
        ai_probe=lambda: probe,
        redactor=Redactor.from_environment({"OPENAI_API_KEY": PROVIDER_KEY}, host),
        clock=Clock(),
        environment={},
        host_directory=host,
        output_directory=tmp_path / "out",
        edge_url="http://edge.test",
        multi_agent_command=("python", "-m", "multi_agent_server.cli"),
        existing_run_id=run_id,
        crud=crud,
        echo=None,
    )


def _edge(*, real: bool = False) -> FakeEdge:
    accepted = [
        {"id": SEEDED, "dataset_id": "gnaf-nsw", "status": "accepted", "record_count": 10},
    ]
    if real:
        accepted.append(
            {"id": REAL, "dataset_id": "nsw-psi-sales", "status": "accepted", "record_count": 7}
        )
    candidate = {
        "id": CANDIDATE,
        "dataset_id": "nsw-psi-sales",
        "status": "candidate",
        "record_count": 4,
    }
    return FakeEdge(accepted=accepted, open_=[candidate])


def _containers() -> list[str]:
    return [_container(service) for service in SERVICES[:2]] + [
        _container("f1-runner", health="none"),
        _container("shared-frontend"),
    ]


def test_capture_passes_and_writes_every_terminal_log(tmp_path: Path) -> None:
    runner = FakeRunner(containers=_containers())
    report = capture(_context(tmp_path, runner=runner, edge=_edge()))
    failures = [check for check in report["checks"] if not check["passed"]]
    assert failures == []
    assert report["verdict"] == "PASSED"
    out = tmp_path / "out"
    names = sorted(path.name for path in out.glob("terminal-*.log"))
    assert names == [
        "terminal-1-compose.log",
        "terminal-2-ai-mode.log",
        "terminal-3-mcp.log",
        "terminal-4-rag.log",
        "terminal-5-multi-agent.log",
        "terminal-6-system-test.log",
    ]
    markdown = (out / "local-deployment-report.md").read_text(encoding="utf-8")
    assert "**Verdict: PASSED**" in markdown
    assert RUN_ID in markdown
    assert "seeded demonstration baseline" in markdown
    assert json.loads((out / "local-deployment-report.json").read_text())["passed"] is True
    # The decision was scripted, recorded and labelled as such.
    assert runner.decided == "reject"
    assert report["multi_agent"]["decision_by"] == "scripted (this capture)"
    assert report["multi_agent"]["provider"] == "openai"


def test_logs_cover_only_the_window_and_are_redacted(tmp_path: Path) -> None:
    runner = FakeRunner(containers=_containers())
    capture(_context(tmp_path, runner=runner, edge=_edge()))
    out = tmp_path / "out"
    everything = "".join(path.read_text(encoding="utf-8") for path in out.rglob("*.*"))
    assert TOKEN not in everything
    assert PROVIDER_KEY not in everything
    assert "\x1b[" not in everything
    multi_agent = (out / "terminal-5-multi-agent.log").read_text(encoding="utf-8")
    window = multi_agent.split("--- capture window", 1)[1]
    assert RUN_ID in window and "old line" not in window
    assert "old line" in multi_agent.split("--- capture window", 1)[0]
    compose = (out / "terminal-1-compose.log").read_text(encoding="utf-8")
    lines = [line for line in compose.splitlines() if " | 2026-" in line]
    stamps = [line.split(" | ", 1)[1].split(" ", 1)[0] for line in lines]
    assert stamps == sorted(stamps)
    assert "Bearer [redacted" in compose
    report = json.loads((out / "local-deployment-report.json").read_text())
    by_file = {terminal["file"]: terminal for terminal in report["terminals"]}
    assert by_file["terminal-5-multi-agent.log"]["correlated_lines"] >= 1
    assert "rag wrote no log lines" in (out / "terminal-4-rag.log").read_text(encoding="utf-8")
    # The export's summary had a secret-shaped value; it is redacted in place.
    summary = (out / "multi-agent-run" / "summary.md").read_text(encoding="utf-8")
    assert PROVIDER_KEY not in summary


def test_system_test_requests_carry_the_capture_request_id(tmp_path: Path) -> None:
    edge = _edge()
    capture(_context(tmp_path, runner=FakeRunner(containers=_containers()), edge=edge))
    assert edge.request_ids and all(rid.startswith("local-deploy-") for rid in edge.request_ids)
    assert not edge.store, "every CRUD record is deleted again"


def test_failures_are_reported_never_hidden(tmp_path: Path) -> None:
    containers = [*_containers(), _container("f1-backend", health="unhealthy")]
    containers.append(_container("rag-server"))
    runner = FakeRunner(containers=containers, reach_human=False)
    context = _context(
        tmp_path,
        runner=runner,
        edge=_edge(),
        processes=FakeProcesses({"mcp": "stopped"}),
        health="not ready",
    )
    report = capture(context)
    assert report["verdict"] == "FAILED"
    failed = {check["name"] for check in report["checks"] if not check["passed"]}
    assert "No AI service runs in a container" in failed
    assert "mcp runs as a host process" in failed
    assert "rag is ready" in failed
    assert "Agents reached awaiting_human" in failed
    assert runner.decided is None, "no decision is recorded on a run that never waited"
    markdown = (tmp_path / "out" / "local-deployment-report.md").read_text(encoding="utf-8")
    assert "## Failures" in markdown and "mcp runs as a host process" in markdown


def test_existing_run_is_captured_without_a_scripted_decision(tmp_path: Path) -> None:
    runner = FakeRunner(containers=_containers())
    runner.decided = "approve"  # a person decided in another terminal
    report = capture(_context(tmp_path, runner=runner, edge=_edge(), run_id=RUN_ID, crud=False))
    actions = [call[3] for call in runner.calls if call[0] == "python"]
    assert "run" not in actions and "decide" not in actions
    assert report["multi_agent"]["decision_by"].startswith("a person")
    assert not [check for check in report["checks"] if check["section"] == "crud"]


def test_data_label_follows_record_counts() -> None:
    seeded: list[dict[str, Any]] = [
        {"dataset_id": "gnaf-nsw", "kind": "seeded demonstration baseline"}
    ]
    assert data_label(seeded).startswith("seeded demonstration baseline")
    real = [
        *seeded,
        {
            "dataset_id": "nsw-psi-sales",
            "kind": "published official release",
            "accepted_records": 7402643,
        },
    ]
    assert data_label(real) == (
        "includes published official releases: 7,402,643 records in nsw-psi-sales (7,402,643); "
        "still seeded or synthetic: gnaf-nsw"
    )


def test_real_release_is_labelled_from_the_inventory(tmp_path: Path) -> None:
    report = capture(
        _context(tmp_path, runner=FakeRunner(containers=_containers()), edge=_edge(real=True))
    )
    assert report["data"]["label"].startswith("includes published official releases")
    kinds = {item["dataset_id"]: item["kind"] for item in report["data"]["datasets"]}
    assert kinds == {
        "gnaf-nsw": "seeded demonstration baseline",
        "nsw-psi-sales": "published official release",
    }


def test_choose_release_prefers_a_release_awaiting_a_decision() -> None:
    data = {
        "open_releases": [{"id": CANDIDATE, "dataset_id": "x", "status": "candidate"}],
        "datasets": [{"dataset_id": "y", "accepted_release_id": SEEDED}],
    }
    assert choose_release(data) == {
        "id": CANDIDATE,
        "dataset_id": "x",
        "status": "candidate",
        "records": None,
    }
    assert choose_release({"open_releases": [], **{"datasets": data["datasets"]}}) == {
        "id": SEEDED,
        "dataset_id": "y",
        "status": "accepted",
        "records": None,
    }
    assert choose_release({}) is None


def test_describe_run_labels_the_provider() -> None:
    assert describe_run(_run_document(state="rejected", provider="deterministic"))[
        "provider_label"
    ].startswith("deterministic")
    model = describe_run(_run_document(state="rejected"))
    assert model["provider_label"] == "real model provider openai (gpt-test)"
    assert model["decisions"][0]["decision"] == "reject"


def test_parse_containers_reads_health_and_service() -> None:
    parsed = parse_containers(_container("f1-runner", health="none") + "\nnot json\n")
    assert [(item.service, item.health, item.state) for item in parsed] == [
        ("f1-runner", "none", "running")
    ]


def test_redactor_removes_literals_and_secret_shapes(tmp_path: Path) -> None:
    (tmp_path / "rag.token").write_text(TOKEN, encoding="utf-8")
    redactor = Redactor.from_environment(
        {"OPENAI_API_KEY": PROVIDER_KEY, "OPENAI_API_KEY_FILE": "/run/secret/path/long"}, tmp_path
    )
    text = f"token {TOKEN}\nkey {PROVIDER_KEY}\nAuthorization: Bearer abcdefghijklmnop\nok\n"
    cleaned, dropped, count = redactor.bounded(text, 1024)
    assert TOKEN not in cleaned and PROVIDER_KEY not in cleaned
    assert "Bearer [redacted]" in cleaned and cleaned.endswith("ok\n")
    assert dropped == 0 and count == 3
    assert redactor.leaks(cleaned) == 0
    assert "/run/secret/path/long" not in redactor.literals


def test_redactor_caps_size_at_a_line_boundary() -> None:
    text = "".join(f"line {number}\n" for number in range(1000))
    capped, dropped, _ = Redactor([]).bounded(text, 100)
    assert dropped > 0 and len(capped.encode()) <= 100
    assert capped.startswith("line ") and capped.endswith("line 999\n")


def test_terminal_table_names_one_command_per_server() -> None:
    commands = {terminal.slug: terminal.command for terminal in capture_module.TERMINALS}
    for service in host_runtime.SERVICES:
        assert re.search(rf"ai serve {service}$", commands[service])
    assert len(capture_module.TERMINALS) == 6


def test_log_observations_surface_tracebacks_without_failing() -> None:
    compose = (
        "# header\n--- capture window a to b ---\n"
        "f2-backend       | 2026-10-16T08:41:17Z Traceback (most recent call last):\n"
        'f2-backend       | 2026-10-16T08:41:17Z   File "x.py", line 1\n'
        "f2-backend       | 2026-10-16T08:41:17Z pkg.clients.DependencyUnavailableError: down\n"
        "f1-backend       | 2026-10-16T08:41:18Z GET /health 200\n"
    )
    host = '--- capture window a to b ---\n{"level":"error","message":"boom"}\n'
    observations = capture_module.log_observations(
        {"terminal-1-compose.log": compose, "terminal-5-multi-agent.log": host}
    )
    assert observations == [
        {
            "file": "terminal-1-compose.log",
            "source": "f2-backend",
            "tracebacks": 1,
            "error_lines": 0,
            "last": "pkg.clients.DependencyUnavailableError: down",
        },
        {
            "file": "terminal-5-multi-agent.log",
            "source": "multi-agent",
            "tracebacks": 0,
            "error_lines": 1,
            "last": '{"level":"error","message":"boom"}',
        },
    ]


def test_the_source_check_ignores_the_evidence_being_refreshed(tmp_path: Path) -> None:
    runner = FakeRunner(containers=_containers())
    report = capture(_context(tmp_path, runner=runner, edge=_edge()))

    status = next(call for call in runner.calls if call[:2] == ("git", "status"))
    assert status[-1] == ":(exclude)docs/release-2/evidence"
    assert report["source"]["uncommitted_paths"] == 1
    text = (tmp_path / "out" / "local-deployment-report.md").read_text(encoding="utf-8")
    assert "1 uncommitted path(s) outside `docs/release-2/evidence` at capture" in text
