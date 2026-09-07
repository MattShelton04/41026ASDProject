"""Placement, private projections and exclusive-owner switching regressions."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest
import yaml
from scripts import dev
from scripts.devtools import ai_runtime, host_runtime


@pytest.fixture(autouse=True)
def isolated_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(ai_runtime, "RUNTIME_DIRECTORY", tmp_path)
    monkeypatch.setattr(ai_runtime, "STATE_PATH", tmp_path / "ai-runtime.json")
    monkeypatch.setattr(host_runtime, "HOST_DIRECTORY", tmp_path / "host")
    monkeypatch.delenv("PROPERTYSCOPE_AI_RUNTIME", raising=False)
    return tmp_path


def test_fresh_selection_defaults_to_docker_and_explicit_choice_wins() -> None:
    assert ai_runtime.selection({}) == "docker"
    ai_runtime.remember("host", "rag")
    assert ai_runtime.selection({}) == "host"
    assert ai_runtime.capability_mode() == "rag"
    assert ai_runtime.selection({"PROPERTYSCOPE_AI_RUNTIME": "docker"}) == "docker"


@pytest.mark.parametrize("placement", ["Docker", "HOST", "azure", "docker "])
def test_invalid_runtime_is_rejected_instead_of_selecting_another(placement: str) -> None:
    with pytest.raises(RuntimeError, match="docker or host"):
        ai_runtime.selection({"PROPERTYSCOPE_AI_RUNTIME": placement})


@pytest.mark.parametrize("placement,mode", [("azure", "direct"), ("host", "automatic")])
def test_invalid_selection_does_not_replace_saved_choice(placement: str, mode: str) -> None:
    ai_runtime.remember("host", "mcp")
    before = ai_runtime.STATE_PATH.read_bytes()
    with pytest.raises(RuntimeError, match="Invalid AI runtime selection"):
        ai_runtime.remember(placement, mode)
    assert ai_runtime.STATE_PATH.read_bytes() == before


@pytest.mark.parametrize("mode", ["Combined", "disabled", "", "mcp "])
def test_invalid_capability_cannot_silently_select_direct(mode: str) -> None:
    with pytest.raises(RuntimeError, match="Invalid AI capability mode"):
        ai_runtime.services(mode)
    ai_runtime.STATE_PATH.write_text(
        json.dumps({"placement": "docker", "mode": mode}), encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="Invalid saved AI capability mode"):
        ai_runtime.capability_mode()


def test_placement_guard_accepts_fresh_and_matching_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ai_runtime.require_same_placement()
    ai_runtime.remember("host", "combined")
    monkeypatch.setenv("PROPERTYSCOPE_AI_RUNTIME", "host")
    ai_runtime.require_same_placement()


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("direct", ("shared-ai-mode",)),
        ("mcp", ("shared-ai-mode", "mcp-server")),
        ("rag", ("shared-ai-mode", "rag-server")),
        ("combined", ("shared-ai-mode", "mcp-server", "rag-server")),
    ],
)
def test_selected_services_do_not_start_disabled_capabilities(
    mode: str, expected: tuple[str, ...]
) -> None:
    assert ai_runtime.services(mode) == expected


def _environment_file(path: Path) -> dict[str, str]:
    return {
        key: value[1:-1]
        for line in path.read_text(encoding="utf-8").splitlines()
        for key, value in [line.split("=", 1)]
    }


def test_private_projection_limits_credentials_and_preserves_literal_dollars(
    isolated_runtime: Path,
) -> None:
    ai_runtime.prepare(
        {
            "OPENAI_API_KEY": "openai-private-value",
            "GEMINI_API_KEY": "gemini-private-value",
            "OPENAI_API_KEY_FILE": "C:/private/provider-key",
            "AI_MODE_SERVICE_TOKEN": "a" * 32,
            "MCP_SERVICE_TOKEN": "m" * 32,
            "RAG_SERVICE_TOKEN": "r" * 32,
            "OPENAI_BASE_URL": "http://provider.example/$literal",
            "UNRELATED_PRIVATE_SETTING": "unrelated-private-value",
        },
        mode="combined",
    )
    directory = isolated_runtime / "docker-ai"
    ai = _environment_file(directory / "ai-mode.env")
    mcp = _environment_file(directory / "mcp.env")
    rag = _environment_file(directory / "rag.env")
    assert ai["OPENAI_API_KEY_FILE"] == "/run/secrets/model_provider_key"
    assert ai["GEMINI_API_KEY_FILE"] == "/run/secrets/model_provider_key"
    assert ai["OPENAI_BASE_URL"] == "http://provider.example/$literal"
    for path in directory.glob("*.env"):
        text = path.read_text(encoding="utf-8")
        assert "openai-private-value" not in text
        assert "gemini-private-value" not in text
        assert "unrelated-private-value" not in text
        assert "C:/private" not in text
    assert "RAG_SERVICE_TOKEN" not in mcp
    assert "MCP_SERVICE_TOKEN" not in rag
    for values in (mcp, rag):
        assert "AI_MODE_SERVICE_TOKEN" not in values
        assert not any(key.startswith(("OPENAI_", "GEMINI_")) for key in values)


@pytest.mark.parametrize("value", ["line\nbreak", "line\rbreak", "quote'value"])
def test_runtime_settings_cannot_inject_extra_env_file_entries(
    isolated_runtime: Path, value: str
) -> None:
    path = isolated_runtime / "settings.env"
    with pytest.raises(RuntimeError, match="runtime setting"):
        ai_runtime._write_environment(path, {"AI_MODE_TEST_SETTING": value})
    assert not path.exists()


def test_docker_catalogues_preserve_native_endpoints_and_tools(isolated_runtime: Path) -> None:
    ai_runtime.prepare({"PROPERTYSCOPE_PORT": "6200"}, mode="combined")
    projection = json.loads(
        (ai_runtime.REPOSITORY_ROOT / "deployment/enabled-features.v1.json").read_text(
            encoding="utf-8"
        )
    )
    copied = isolated_runtime / "docker-ai/catalogues"
    expected_names = set()
    for feature in projection["features"]:
        if not feature.get("ai"):
            continue
        name = f"{feature['feature_key']}.yaml"
        expected_names.add(name)
        actual = yaml.safe_load((copied / name).read_text(encoding="utf-8"))
        source = yaml.safe_load(
            (ai_runtime.REPOSITORY_ROOT / feature["ai"]["tool_catalog"]).read_text(encoding="utf-8")
        )
        assert actual == source
        assert all("127.0.0.1" not in service["base_url"] for service in actual["services"])
    assert {path.name for path in copied.glob("*.yaml")} == expected_names
    ai = _environment_file(isolated_runtime / "docker-ai/ai-mode.env")
    assert ai["MCP_SERVER_URL"] == "http://mcp-server:5011/mcp"
    assert ai["RAG_SERVER_URL"] == "http://rag-server:5012"
    assert all(
        path.startswith("/etc/propertyscope/catalogues/")
        for path in ai["AI_MODE_TOOL_CATALOG_PATHS"].split(",")
    )


def test_ci_rejects_advanced_services_before_writing_runtime_files(
    isolated_runtime: Path,
) -> None:
    with pytest.raises(RuntimeError, match="disabled in CI"):
        ai_runtime.prepare({"CI": "true"}, mode="combined")
    assert not (isolated_runtime / "docker-ai").exists()
    ai_runtime.prepare({"CI": "true"}, mode="direct")
    values = _environment_file(isolated_runtime / "docker-ai/ai-mode.env")
    assert values["AI_MODE_MCP_ENABLED"] == values["AI_MODE_RAG_ENABLED"] == "false"
    assert values["CI"] == "true"


def test_overlay_preserves_exclusive_store_ownership_and_loopback_publication() -> None:
    model = yaml.safe_load(
        (ai_runtime.REPOSITORY_ROOT / ai_runtime.OVERLAY).read_text(encoding="utf-8")
    )
    services = model["services"]
    expected_owners = {"ai-mode": "shared-ai-mode", "rag": "rag-server"}
    for owner, expected_service in expected_owners.items():
        mounts = [
            (name, mount)
            for name, service in services.items()
            for mount in service.get("volumes", [])
            if f"/.propertyscope-runtime/host/{owner}:" in mount
        ]
        assert mounts == [
            (
                expected_service,
                f"./.propertyscope-runtime/host/{owner}:/var/lib/{owner}",
            )
        ]
    for name in ai_runtime.DOCKER_SERVICES:
        service = services[name]
        assert all(port.startswith("127.0.0.1:") for port in service["ports"])
        assert service["profiles"] == ["ai-container"]
        assert not any("student-" in mount for mount in service.get("volumes", []))
        # A fresh checkout can inspect/build Compose before runtime secrets exist.
        assert all(entry["required"] is False for entry in service["env_file"])
    assert services["shared-ai-mode"]["secrets"] == ["model_provider_key"]
    assert not services["mcp-server"].get("secrets")
    assert not services["rag-server"].get("secrets")


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
    monkeypatch.setattr(dev, "ENABLED_FEATURE_KEYS", ())
    monkeypatch.setattr(dev, "APPLICATION_SERVICES", ("shared-frontend",))
    monkeypatch.setattr(
        dev, "_resolved_host_ports", lambda _services: {"shared-frontend": ("port", 5100)}
    )
    monkeypatch.setattr(host_runtime, "stop", lambda: calls.append(("host-stop",)))
    monkeypatch.setattr(
        host_runtime, "start", lambda *_args, **_kwargs: calls.append(("host-start",))
    )
    monkeypatch.setattr(host_runtime, "migrate_legacy_state", lambda: calls.append(("migrate",)))

    def run(command: Sequence[str], *, environment: Mapping[str, str] | None = None) -> None:
        calls.append(tuple(command))

    monkeypatch.setattr(dev, "_run", run)
    return calls


def test_switch_to_docker_stops_host_before_starting_new_owner(
    lifecycle: list[tuple[str, ...]],
) -> None:
    ai_runtime.remember("host", "combined")
    dev._up(offline=False, placement="docker")
    start = next(index for index, call in enumerate(lifecycle) if "up" in call)
    assert lifecycle.index(("host-stop",)) < start
    assert ("host-start",) not in lifecycle
    assert ai_runtime.OVERLAY in lifecycle[start]
    assert "--force-recreate" in lifecycle[start]
    assert all(service in lifecycle[start] for service in ai_runtime.DOCKER_SERVICES)
    assert ai_runtime.selection({}) == "docker"


@pytest.mark.parametrize("setting", ["RAG_DATABASE_PATH", "RAG_MODEL_CACHE_PATH"])
def test_custom_rag_paths_fail_before_stopping_active_host(
    lifecycle: list[tuple[str, ...]],
    monkeypatch: pytest.MonkeyPatch,
    setting: str,
) -> None:
    ai_runtime.remember("host", "combined")
    monkeypatch.setattr(dev, "_compose_environment", lambda **_kwargs: {setting: "/custom/rag"})
    with pytest.raises(RuntimeError, match="canonical"):
        dev._up(offline=False, placement="docker")
    assert ("host-stop",) not in lifecycle
    assert ai_runtime.selection({}) == "host"


def test_switch_to_host_stops_docker_before_opening_shared_store(
    lifecycle: list[tuple[str, ...]], isolated_runtime: Path
) -> None:
    ai_runtime.prepare({}, mode="combined")
    ai_runtime.remember("docker", "combined")
    dev._up(offline=False, placement="host")
    stop = next(index for index, call in enumerate(lifecycle) if "stop" in call)
    assert ai_runtime.OVERLAY in lifecycle[stop]
    assert all(service in lifecycle[stop] for service in ai_runtime.DOCKER_SERVICES)
    assert stop < lifecycle.index(("migrate",)) < lifecycle.index(("host-start",))
    start = next(call for call in lifecycle if "up" in call)
    assert ai_runtime.OVERLAY not in start
    assert not any(service in start for service in ai_runtime.DOCKER_SERVICES)
    assert ai_runtime.selection({}) == "host"


def test_offline_docker_stops_advanced_services_and_starts_only_ai_mode(
    lifecycle: list[tuple[str, ...]],
) -> None:
    dev._up(offline=True, placement="docker")
    stop = next(call for call in lifecycle if "stop" in call)
    assert stop[-2:] == ("mcp-server", "rag-server")
    start = next(call for call in lifecycle if "up" in call)
    assert "shared-ai-mode" in start
    assert "mcp-server" not in start
    assert "rag-server" not in start
    assert ai_runtime.capability_mode() == "direct"


def test_failed_docker_stop_prevents_host_start_and_preserves_selection(
    lifecycle: list[tuple[str, ...]], monkeypatch: pytest.MonkeyPatch
) -> None:
    ai_runtime.prepare({}, mode="combined")
    ai_runtime.remember("docker", "combined")

    def fail_stop(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("Docker failed to stop its owner")

    monkeypatch.setattr(dev, "_run", fail_stop)
    with pytest.raises(RuntimeError, match="failed to stop"):
        dev._up(offline=False, placement="host")
    assert ("host-start",) not in lifecycle
    assert ai_runtime.selection({}) == "docker"


@pytest.mark.parametrize(
    "arguments",
    [["ai", "start"], ["ai", "stop"], ["stack", "restart"], ["stack", "down"]],
)
def test_environment_placement_override_cannot_bypass_integrated_switch(
    lifecycle: list[tuple[str, ...]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
) -> None:
    ai_runtime.remember("docker", "combined")
    monkeypatch.setenv("PROPERTYSCOPE_AI_RUNTIME", "host")
    assert dev.main(arguments) == 1
    assert "stack up --ai-runtime" in capsys.readouterr().err
    assert lifecycle == []
    assert ai_runtime.selection({}) == "docker"


def test_ai_start_requires_established_backend_routing(
    lifecycle: list[tuple[str, ...]], capsys: pytest.CaptureFixture[str]
) -> None:
    assert dev.main(["ai", "start", "--offline"]) == 1
    assert "Run stack up first" in capsys.readouterr().err
    assert lifecycle == []
    assert not ai_runtime.STATE_PATH.exists()


def test_ai_start_offline_forces_direct_and_preserves_legacy_migration(
    lifecycle: list[tuple[str, ...]], monkeypatch: pytest.MonkeyPatch
) -> None:
    ai_runtime.remember("docker", "combined")
    monkeypatch.setattr(
        dev,
        "_preflight_compose_host_ports",
        lambda **_kwargs: lifecycle.append(("preflight",)),
    )
    assert dev.main(["ai", "start", "--offline", "--mode", "combined"]) == 0
    start_index = next(index for index, call in enumerate(lifecycle) if "up" in call)
    start = lifecycle[start_index]
    assert "shared-ai-mode" in start
    assert "mcp-server" not in start
    assert "rag-server" not in start
    assert lifecycle.index(("host-stop",)) < lifecycle.index(("preflight",))
    assert lifecycle.index(("preflight",)) < lifecycle.index(("migrate",)) < start_index
    stop = next(call for call in lifecycle if "stop" in call)
    assert stop[-2:] == ("mcp-server", "rag-server")
    assert ai_runtime.capability_mode() == "direct"
