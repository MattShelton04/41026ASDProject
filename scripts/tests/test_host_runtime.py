"""Host runtime ownership, transport projection and data migration regression tests."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import psutil
import pytest
import yaml
from scripts.devtools import host_runtime as runtime


@pytest.fixture
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(runtime, "HOST_DIRECTORY", tmp_path / "host")
    return tmp_path


def test_owned_process_rejects_reused_pid(isolated: Path) -> None:
    process = psutil.Process(os.getpid())
    state = {
        "pid": process.pid,
        "created_at": process.create_time() + 1,
        "command": process.cmdline(),
    }
    runtime._write_json(runtime.HOST_DIRECTORY / "ai-mode.json", state)
    assert runtime._owned_process("ai-mode") is None
    runtime.stop(("ai-mode",))
    assert process.is_running()


def test_owned_process_requires_checkout_and_command(
    isolated: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = psutil.Process(os.getpid())
    state = {
        "pid": process.pid,
        "created_at": process.create_time(),
        "command": ["some-other-command"],
        "checkout": str(runtime.REPOSITORY_ROOT.resolve()),
    }
    runtime._write_json(runtime.HOST_DIRECTORY / "ai-mode.json", state)
    assert runtime._owned_process("ai-mode") is None
    state["command"] = process.cmdline()
    runtime._write_json(runtime.HOST_DIRECTORY / "ai-mode.json", state)
    monkeypatch.setattr(runtime, "REPOSITORY_ROOT", isolated)
    assert runtime._owned_process("ai-mode") is None


def test_corrupt_pid_file_is_not_authority_to_signal(isolated: Path) -> None:
    runtime.HOST_DIRECTORY.mkdir()
    (runtime.HOST_DIRECTORY / "mcp.json").write_text("broken", encoding="utf-8")
    runtime.stop(("mcp",))
    assert runtime.status()[1]["state"] == "stopped"


def test_ci_and_cloud_reject_advanced_startup_before_files(isolated: Path) -> None:
    for environment in ({"CI": "true"}, {"AI_MODE_ENVIRONMENT": "azure"}):
        with pytest.raises(RuntimeError):
            runtime.prepare_environment(environment)
    assert not runtime.HOST_DIRECTORY.exists()


def test_host_catalogue_remaps_only_enabled_features_and_preserves_tools(isolated: Path) -> None:
    result = runtime.prepare_environment({"PROPERTYSCOPE_PORT": "6200"}, mode="rag")
    assert result["AI_MODE_MCP_ENABLED"] == "false"
    assert result["AI_MODE_RAG_ENABLED"] == "true"
    paths = result["AI_MODE_TOOL_CATALOG_PATHS"].split(",")
    assert len(paths) == 5
    for path in paths:
        catalogue = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        assert all(
            item["base_url"].startswith("http://127.0.0.1:") for item in catalogue["services"]
        )
        assert catalogue["tools"]
    assert len(result["MCP_SERVICE_TOKEN"]) >= 32
    repeated = runtime.prepare_environment({}, mode="direct")
    assert repeated["MCP_SERVICE_TOKEN"] == result["MCP_SERVICE_TOKEN"]
    assert repeated["AI_MODE_MCP_ENABLED"] == repeated["AI_MODE_RAG_ENABLED"] == "false"
    assert "agent-state.sqlite3" in result["AI_MODE_DATABASE_PATH"]
    assert "RAG_MODEL_CACHE_PATH" in result


def test_legacy_migration_preserves_data_and_never_overwrites(
    isolated: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    def docker(*arguments: str) -> str:
        calls.append(arguments)
        if arguments[:2] == ("volume", "ls"):
            return "ps-dev_shared-ai-mode-state"
        if arguments[0] == "cp":
            with sqlite3.connect(Path(arguments[2]) / "agent-state.sqlite3") as database:
                database.execute("CREATE TABLE retained_runs (id TEXT)")
                database.execute("INSERT INTO retained_runs VALUES ('historical-run')")
            database.close()
        return ""

    monkeypatch.setattr(runtime, "_docker", docker)
    runtime.migrate_legacy_state()
    destination = runtime.HOST_DIRECTORY / "ai-mode" / "agent-state.sqlite3"
    with sqlite3.connect(destination) as database:
        assert database.execute("SELECT id FROM retained_runs").fetchone() == ("historical-run",)
    database.close()
    assert any("readonly" in " ".join(call) for call in calls)
    assert not any(call[0] == "start" for call in calls)
    calls.clear()
    runtime.migrate_legacy_state()
    assert calls == []


def test_legacy_migration_refuses_unrelated_volume_owner(
    isolated: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def docker(*arguments: str) -> str:
        if arguments[0] == "volume":
            return "legacy-volume"
        if arguments[0] == "ps":
            return "container"
        if arguments[0] == "inspect":
            return json.dumps({"com.docker.compose.project": "other-project"})
        pytest.fail("must not stop or copy a different project's state")

    monkeypatch.setattr(runtime, "_docker", docker)
    with pytest.raises(RuntimeError, match="another project"):
        runtime.migrate_legacy_state()


def test_compose_has_no_ai_service_or_provider_secret() -> None:
    for filename in (
        "docker-compose.yml",
        "docker-compose.dev.yml",
        "deployment/enabled-features.compose.yml",
    ):
        model = yaml.safe_load((runtime.REPOSITORY_ROOT / filename).read_text(encoding="utf-8"))
        assert not any(
            name in model["services"] for name in ("shared-ai-mode", "mcp-server", "rag-server")
        )
    base = yaml.safe_load(
        (runtime.REPOSITORY_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    )
    assert "secrets" not in base
    for name in (
        "shared-frontend",
        "f1-backend",
        "f2-backend",
        "f3-backend",
        "f4-backend",
        "f5-backend",
    ):
        assert "host.docker.internal:host-gateway" in base["services"][name]["extra_hosts"]


def test_all_workflows_disable_mcp_and_rag_without_starting_them() -> None:
    for path in (runtime.REPOSITORY_ROOT / ".github/workflows").glob("*.yml"):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert workflow["env"]["AI_MODE_MCP_ENABLED"] == "false", path.name
        assert workflow["env"]["AI_MODE_RAG_ENABLED"] == "false", path.name
        for job in workflow["jobs"].values():
            for scope in (job, *job.get("steps", [])):
                for key in ("AI_MODE_MCP_ENABLED", "AI_MODE_RAG_ENABLED"):
                    assert scope.get("env", {}).get(key, "false") == "false", path.name
            commands = "\n".join(str(step.get("run", "")) for step in job.get("steps", []))
            assert "shared-ai-mode" not in commands, path.name
            assert "rag-server serve" not in commands, path.name
            assert "-m mcp_server" not in commands, path.name
            assert "ai start --mode combined" not in commands, path.name
            if path.name.startswith("student-") and any(
                "uv sync" in str(step.get("run", "")) for step in job.get("steps", [])
            ):
                # Some jobs only sync late for container smoke; the workflow's source job
                # owns the reusable unit gate once per student workflow.
                workflow_text = path.read_text(encoding="utf-8")
                assert "shared/contracts/tests/test_retrieval.py" in workflow_text
                assert "shared/tool-runtime/tests" in workflow_text
                assert "ai-services/rag-server/tests/test_embeddings.py" in workflow_text
