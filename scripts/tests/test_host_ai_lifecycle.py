"""The launcher runs AI-mode, MCP and RAG only as host processes (ADR-043, ADR-046)."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest
import yaml
from scripts import dev
from scripts.devtools import host_runtime


@pytest.fixture(autouse=True)
def isolated_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(host_runtime, "HOST_DIRECTORY", tmp_path / "host")
    monkeypatch.setattr(host_runtime, "RETIRED_PROJECTION_DIRECTORY", tmp_path / "docker-ai")
    monkeypatch.setattr(host_runtime, "RETIRED_PLACEMENT_STATE", tmp_path / "ai-runtime.json")
    monkeypatch.delenv("COMPOSE_PROJECT_NAME", raising=False)
    return tmp_path


@pytest.fixture
def lifecycle(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    calls: list[tuple[str, ...]] = []
    for name in (
        "_validate_deployment_inputs",
        "_ensure_docker",
        "_stop_disabled_feature_services",
    ):
        monkeypatch.setattr(dev, name, lambda: None)
    monkeypatch.setattr(dev, "_openai_credential", lambda **_kwargs: "test")
    monkeypatch.setattr(dev, "_load_development_environment", lambda _path: None)
    monkeypatch.setattr(dev, "_compose_environment", lambda **_kwargs: {})
    monkeypatch.setattr(dev, "_preflight_compose_host_ports", lambda **_kwargs: None)
    monkeypatch.setattr(dev, "_reload_shared_edge", lambda **_kwargs: None)
    monkeypatch.setattr(dev, "_remove_openai_secret", lambda: calls.append(("remove-secret",)))
    monkeypatch.setattr(dev, "ENABLED_FEATURE_KEYS", ())
    monkeypatch.setattr(dev, "APPLICATION_SERVICES", ("shared-frontend",))
    monkeypatch.setattr(
        dev, "_resolved_host_ports", lambda _services: {"shared-frontend": ("port", 5100)}
    )
    monkeypatch.setattr(host_runtime, "stop", lambda *_args: calls.append(("host-stop",)))
    monkeypatch.setattr(
        host_runtime,
        "start",
        lambda _environment, *, mode: calls.append(("host-start", mode)),
    )
    monkeypatch.setattr(
        host_runtime, "retire_container_placement", lambda: calls.append(("retire",))
    )
    monkeypatch.setattr(host_runtime, "migrate_legacy_state", lambda: calls.append(("migrate",)))

    def run(command: Sequence[str], *, environment: Mapping[str, str] | None = None) -> None:
        calls.append(tuple(command))

    monkeypatch.setattr(dev, "_run", run)
    return calls


def _compose_calls(calls: list[tuple[str, ...]]) -> list[tuple[str, ...]]:
    return [call for call in calls if call[:2] == ("docker", "compose")]


@pytest.mark.parametrize(("offline", "mode"), [(False, "combined"), (True, "direct")])
def test_stack_up_starts_host_ai_before_the_feature_containers(
    lifecycle: list[tuple[str, ...]], offline: bool, mode: str
) -> None:
    dev._up(offline=offline)

    compose_up = next(call for call in _compose_calls(lifecycle) if "up" in call)
    assert lifecycle.index(("retire",)) < lifecycle.index(("migrate",))
    assert lifecycle.index(("migrate",)) < lifecycle.index(("host-start", mode))
    assert lifecycle.index(("host-start", mode)) < lifecycle.index(compose_up)
    for call in _compose_calls(lifecycle):
        assert "docker-compose.ai.yml" not in call
        assert "ai-container" not in call
        assert not {"shared-ai-mode", "mcp-server", "rag-server"} & set(call)


def test_retired_placement_flag_rejects_docker_before_any_effect(
    lifecycle: list[tuple[str, ...]], capsys: pytest.CaptureFixture[str]
) -> None:
    assert dev.main(["stack", "up", "--ai-runtime", "docker"]) == 1
    assert "no longer run in Docker" in capsys.readouterr().err
    assert lifecycle == []


def test_retired_placement_flag_still_accepts_host(
    lifecycle: list[tuple[str, ...]], capsys: pytest.CaptureFixture[str]
) -> None:
    assert dev.main(["stack", "up", "--ai-runtime", "host"]) == 0
    assert "no longer needed" in capsys.readouterr().out
    assert ("host-start", "combined") in lifecycle


def test_ai_start_bootstraps_host_services_without_a_prior_stack_up(
    lifecycle: list[tuple[str, ...]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Student 5 CI starts direct AI-mode on a fresh checkout before its own containers."""
    workflow = yaml.safe_load(
        (dev.REPOSITORY_ROOT / ".github/workflows/student-5.yml").read_text(encoding="utf-8")
    )
    assert "PROPERTYSCOPE_AI_RUNTIME" not in workflow["env"]
    for key, value in workflow["env"].items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("CI", "true")
    monkeypatch.setattr(dev, "_ai_status", lambda: lifecycle.append(("status",)))

    assert dev.main(["ai", "start", "--mode", "combined", "--offline"]) == 0
    assert ("host-start", "direct") in lifecycle
    assert _compose_calls(lifecycle) == []
    assert dev.main(["ai", "stop"]) == 0
    assert lifecycle[-1] == ("host-stop",)


def test_stack_down_stops_host_ai_first_and_removes_orphaned_ai_containers(
    lifecycle: list[tuple[str, ...]],
) -> None:
    dev._down(remove_volumes=False)

    down = next(call for call in _compose_calls(lifecycle) if "down" in call)
    assert lifecycle.index(("host-stop",)) < lifecycle.index(down)
    assert lifecycle.index(down) < lifecycle.index(("remove-secret",))
    assert "--remove-orphans" in down
    assert "--volumes" not in down
    assert "ai-container" not in down


def test_status_reports_host_processes_then_containers(
    lifecycle: list[tuple[str, ...]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("MCP_PORT", "6011")

    assert dev.main(["stack", "status"]) == 0

    output = capsys.readouterr().out
    assert "host processes (not containerised" in output
    assert "http://127.0.0.1:6011/mcp" in output
    assert _compose_calls(lifecycle)[-1][-1] == "ps"


def test_status_lists_every_host_service_with_its_local_url() -> None:
    urls = {
        entry["service"]: entry["url"]
        for entry in host_runtime.status({"AI_MODE_PORT": "6005", "RAG_PORT": "6012"})
    }
    assert urls == {
        "ai-mode": "http://127.0.0.1:6005",
        "mcp": "http://127.0.0.1:5011/mcp",
        "rag": "http://127.0.0.1:6012",
        "multi-agent": "http://127.0.0.1:5013",
    }


def test_fresh_checkout_retirement_needs_no_docker(
    isolated_runtime: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def docker(*_arguments: str) -> str:
        pytest.fail("a checkout without the old projection must not call Docker")

    monkeypatch.setattr(host_runtime, "_docker", docker)
    (isolated_runtime / "ai-runtime.json").write_text(
        json.dumps({"placement": "host", "mode": "combined"}), encoding="utf-8"
    )

    host_runtime.retire_container_placement()

    assert not (isolated_runtime / "ai-runtime.json").exists()


def test_retirement_removes_only_this_projects_old_ai_containers(
    isolated_runtime: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projection = isolated_runtime / "docker-ai"
    projection.mkdir()
    (projection / "ai-mode.env").write_text("AI_MODE_SERVICE_TOKEN='copy'\n", encoding="utf-8")
    history = isolated_runtime / "host" / "ai-mode" / "agent-state.sqlite3"
    history.parent.mkdir(parents=True)
    history.write_bytes(b"retained")
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "ps-scratch")
    commands: list[tuple[str, ...]] = []
    found = {"shared-ai-mode": "a1", "rag-server": "r1"}

    def docker(*arguments: str) -> str:
        commands.append(arguments)
        if arguments[0] == "ps":
            assert "label=com.docker.compose.project=ps-scratch" in arguments
            service = arguments[-1].removeprefix("label=com.docker.compose.service=")
            return found.get(service, "")
        return ""

    monkeypatch.setattr(host_runtime, "_docker", docker)

    host_runtime.retire_container_placement()

    assert ("stop", "--time", "35", "a1", "r1") in commands
    assert ("rm", "a1", "r1") in commands
    assert not projection.exists()
    assert history.read_bytes() == b"retained"


def test_failed_retirement_keeps_the_projection_so_the_next_start_retries(
    isolated_runtime: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projection = isolated_runtime / "docker-ai"
    projection.mkdir()

    def docker(*_arguments: str) -> str:
        raise RuntimeError("Docker is not running")

    monkeypatch.setattr(host_runtime, "_docker", docker)

    with pytest.raises(RuntimeError, match="not running"):
        host_runtime.retire_container_placement()
    assert projection.exists()
