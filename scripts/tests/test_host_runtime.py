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


@pytest.mark.parametrize("mode", ["", "Combined", "unknown"])
def test_unknown_mode_cannot_create_state(isolated: Path, mode: str) -> None:
    with pytest.raises(RuntimeError, match="capability mode"):
        runtime.prepare_environment({}, mode=mode)
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
    assert result["RAG_MODEL_CACHE_PATH"] == str(runtime.HOST_DIRECTORY / "rag" / "models")


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


def test_legacy_migration_only_reads_the_selected_projects_volume(
    isolated: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    def docker(*arguments: str) -> str:
        calls.append(arguments)
        return ""

    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "ps-isolated")
    monkeypatch.setattr(runtime, "_docker", docker)
    runtime.migrate_legacy_state()

    assert calls == [
        (
            "volume",
            "ls",
            "--filter",
            "label=com.docker.compose.project=ps-isolated",
            "--filter",
            "label=com.docker.compose.volume=shared-ai-mode-state",
            "--format",
            "{{.Name}}",
        )
    ]


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
        # Renaming an AI service must not bypass the non-containerised boundary.
        for name, service in model["services"].items():
            build = service.get("build", {})
            build_text = str(build).lower().replace("\\", "/")
            command_text = str(service.get("command", "")).lower()
            image_text = str(service.get("image", "")).lower()
            for component in ("ai-mode", "mcp-server", "rag-server", "agent-core"):
                assert f"ai-services/{component}" not in build_text, (filename, name)
                assert component not in image_text, (filename, name)
            for module in ("ai_mode", "mcp_server", "rag_server", "agent_core"):
                assert module not in command_text, (filename, name)
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


def test_host_entry_requires_credential_for_runs_reviews_and_history() -> None:
    from flask import Flask

    application = Flask(__name__)
    for path in (
        "/api/v1/agent-runs",
        "/api/v1/agent-runs/run/reviews",
        "/operations/ai-mode/",
        "/health/ready",
        "/health/live",
    ):
        application.add_url_rule(
            path, endpoint=path, view_func=lambda: "permitted", methods=["GET", "POST"]
        )
    runtime.protect_host_entry(application, "a" * 43)
    client = application.test_client()
    assert client.get("/health/live").status_code == 200
    for path in (
        "/api/v1/agent-runs",
        "/api/v1/agent-runs/run/reviews",
        "/operations/ai-mode/",
        "/health/ready",
    ):
        assert client.post(path).status_code == 401
        assert client.post(path, headers={"X-PropertyScope-AI-Token": "invalid"}).status_code == 401
        assert client.post(path, headers={"X-PropertyScope-AI-Token": "é"}).status_code == 401
        assert client.post(path, headers={"X-PropertyScope-AI-Token": "a" * 43}).status_code == 200
    with pytest.raises(RuntimeError, match="AI_MODE_SERVICE_TOKEN"):
        runtime.protect_host_entry(Flask("unconfigured"), "")


def test_host_entry_token_is_persisted_and_safe_for_proxy_config(isolated: Path) -> None:
    token = runtime.ai_service_token({})
    assert len(token) >= 32
    assert runtime.ai_service_token({}) == token
    assert runtime.prepare_environment({}, mode="direct")["AI_MODE_SERVICE_TOKEN"] == token
    for invalid in ("short", "a" * 32 + '"; injection', "a" * 129):
        with pytest.raises(RuntimeError, match="URL-safe"):
            runtime.ai_service_token({"AI_MODE_SERVICE_TOKEN": invalid})


def test_compose_and_edge_keep_host_credential_on_server_side() -> None:
    compose = yaml.safe_load((runtime.REPOSITORY_ROOT / "docker-compose.yml").read_text())
    for service in (
        "shared-frontend",
        "f1-backend",
        "f2-backend",
        "f3-backend",
        "f4-backend",
        "f5-backend",
    ):
        assert (
            compose["services"][service]["environment"]["AI_MODE_SERVICE_TOKEN"]
            == "${AI_MODE_SERVICE_TOKEN:-}"
        )
    nginx = (runtime.REPOSITORY_ROOT / "shared/frontend/nginx.conf").read_text()
    assert nginx.count('proxy_set_header X-PropertyScope-AI-Token "${AI_MODE_SERVICE_TOKEN}";') == 4
    assert (
        "AI_MODE_(HOST|PORT|SERVICE_TOKEN)"
        in compose["services"]["shared-frontend"]["environment"]["NGINX_ENVSUBST_FILTER"]
    )


def test_named_validation_loads_its_explicit_environment_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from scripts import dev, release1_validation

    environment_file = tmp_path / "validation.env"
    environment_file.write_text("RAG_PORT=6502\n", encoding="utf-8")
    monkeypatch.delenv("RAG_PORT", raising=False)
    observed: list[str] = []

    def validate(*args: object, **kwargs: object) -> dict[str, object]:
        observed.append(os.environ["RAG_PORT"])
        return {"passed": True}

    monkeypatch.setattr(release1_validation, "validate", validate)
    assert dev.main(["ai", "validate", "rag", "--env-file", str(environment_file)]) == 0
    assert observed == ["6502"]


def test_derived_corpus_scope_matches_the_literal_it_replaced(isolated: Path) -> None:
    """Pins the behaviour-preservation claim: the original declaration still scopes RAG.

    The scope grows as owners adopt RAG independently, so this asserts the founding pair is
    still present rather than that it is the only one; derivation itself is covered by
    ``test_corpus_scopes_come_from_enabled_declarations``.
    """
    resolved = runtime.prepare_environment({}, mode="combined")

    scope = resolved["RAG_ALLOWED_CORPORA"].split(",")
    assert "student-1-propertyscope-data-platform:operator-guidance" in scope
    assert len(scope) == len(set(scope))
    assert resolved["AI_MODE_RAG_CORPORA"] == resolved["RAG_ALLOWED_CORPORA"]
    assert resolved["RAG_OFFICIAL_EVIDENCE_CORPORA"] == (
        "student-3-suburb-analytics:suburb-analytics-guidance"
    )


def test_corpus_scopes_come_from_enabled_declarations(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projection = json.loads(
        (runtime.REPOSITORY_ROOT / "deployment/enabled-features.v1.json").read_text("utf-8")
    )
    for feature in projection["features"]:
        if feature.get("ai") and feature["feature_key"].startswith("student-2"):
            feature["ai"]["rag_corpus"] = "student-1/config/rag/corpus.json"
            feature["ai"]["rag_corpus_id"] = "second-guidance"
        elif feature.get("ai") and feature["feature_key"].startswith("student-4"):
            feature["ai"]["rag_corpus"] = "student-1/config/rag/corpus.json"
    _write_projection(isolated, monkeypatch, projection)

    expected = tuple(
        f"{feature['feature_key']}:{feature['ai']['rag_corpus_id']}"
        for feature in projection["features"]
        if feature.get("ai") and feature["ai"].get("rag_corpus")
    )
    assert "student-2-market-intelligence:second-guidance" in expected
    assert "student-5-buyer-journey:operator-guidance" in expected
    assert runtime._corpus_scopes() == expected


def test_a_declared_but_missing_corpus_manifest_is_rejected(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projection = json.loads(
        (runtime.REPOSITORY_ROOT / "deployment/enabled-features.v1.json").read_text("utf-8")
    )
    projection["features"][0]["ai"]["rag_corpus"] = "student-1/config/rag/absent.json"
    _write_projection(isolated, monkeypatch, projection)

    with pytest.raises(RuntimeError, match="missing corpus manifest"):
        runtime._corpus_scopes()


def test_rag_without_any_declared_corpus_refuses_to_start(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Silently falling back would scope RAG to a corpus no enabled feature declares."""
    projection = json.loads(
        (runtime.REPOSITORY_ROOT / "deployment/enabled-features.v1.json").read_text("utf-8")
    )
    for feature in projection["features"]:
        if feature.get("ai"):
            feature["ai"]["rag_corpus"] = None
            feature["ai"]["rag_corpus_id"] = None
    _write_projection(isolated, monkeypatch, projection)

    with pytest.raises(RuntimeError, match="No enabled feature declares a RAG corpus"):
        runtime.prepare_environment({}, mode="combined")
    # MCP-only and direct placements remain usable without any corpus.
    assert "RAG_ALLOWED_CORPORA" not in runtime.prepare_environment({}, mode="mcp")


def _write_projection(
    isolated: Path, monkeypatch: pytest.MonkeyPatch, projection: dict[str, object]
) -> None:
    root = isolated / "repository"
    (root / "deployment").mkdir(parents=True, exist_ok=True)
    (root / "deployment/enabled-features.v1.json").write_text(
        json.dumps(projection), encoding="utf-8"
    )
    for source in ("student-1/config/rag", "student-1", "student-2", "student-3"):
        (root / source).mkdir(parents=True, exist_ok=True)
    (root / "student-1/config/rag/corpus.json").write_text("{}", encoding="utf-8")
    # Mirror real declared corpora, but leave deliberately absent paths missing.
    declared = json.loads((root / "deployment/enabled-features.v1.json").read_text("utf-8"))
    for feature in declared["features"]:
        corpus = (feature.get("ai") or {}).get("rag_corpus")
        if corpus and (runtime.REPOSITORY_ROOT / corpus).is_file():
            destination = root / corpus
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(
                (runtime.REPOSITORY_ROOT / corpus).read_text(encoding="utf-8"), encoding="utf-8"
            )
    for number in range(1, 6):
        catalogue = runtime.REPOSITORY_ROOT / f"student-{number}/tool-catalog.yaml"
        if catalogue.is_file():
            (root / f"student-{number}").mkdir(parents=True, exist_ok=True)
            (root / f"student-{number}/tool-catalog.yaml").write_text(
                catalogue.read_text(encoding="utf-8"), encoding="utf-8"
            )
    monkeypatch.setattr(runtime, "REPOSITORY_ROOT", root)
