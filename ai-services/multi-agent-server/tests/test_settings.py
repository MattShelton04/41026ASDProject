"""Environment settings, provider selection and gateway composition."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from agent_core import ModelMessage, ModelProviderError, ModelRole, StructuredModelRequest
from multi_agent_server.providers import DeterministicProvider, describe_result, select_provider
from multi_agent_server.settings import (
    MultiAgentSettings,
    SettingsError,
    build_gateway,
    build_registry,
)
from multi_agent_server.tools import CatalogToolGateway, FixtureToolGateway, UnavailableToolGateway

FIXTURES = Path(__file__).parent / "fixtures"
TOKEN = "test-multi-agent-token-0123456789abcdef"
MCP_TOKEN = "mcp-token-0123456789abcdefghijklmnop"


def catalog_file(directory: Path) -> Path:
    tools = json.loads((FIXTURES / "tools.json").read_text(encoding="utf-8"))["tools"]
    path = directory / "catalog.json"
    path.write_text(
        json.dumps(
            {
                "services": [{"service": "svc", "base_url": "http://127.0.0.1:1"}],
                "tools": [
                    {
                        "definition": entry["definition"],
                        "service": "svc",
                        "method": "POST",
                        "path": f"/tools/{index}",
                    }
                    for index, entry in enumerate(tools)
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_from_environment_reads_every_variable(tmp_path: Path) -> None:
    settings = MultiAgentSettings.from_environment(
        {
            "MULTI_AGENT_SERVICE_TOKEN": TOKEN,
            "MULTI_AGENT_STATE_DIR": str(tmp_path / "state"),
            "MULTI_AGENT_REPOSITORY_ROOT": str(tmp_path),
            "MULTI_AGENT_TEMPLATE_PATHS": f"{FIXTURES / 'workflow.yaml'}, ",
            "MULTI_AGENT_PROVIDER": "deterministic",
            "MULTI_AGENT_MODEL_ATTEMPTS": "3",
            "MULTI_AGENT_MODEL_TIMEOUT_SECONDS": "30",
            "MULTI_AGENT_MODEL_FALLBACK": "fail",
            "MULTI_AGENT_TOOL_TRANSPORT": "none",
            "MCP_TOOL_CATALOG_PATHS": "a.json,b.json",
            "MULTI_AGENT_TOOL_FIXTURES": str(FIXTURES / "tools.json"),
            "AI_MODE_MCP_ENABLED": "true",
            "MCP_SERVER_URL": "http://127.0.0.1:6011/mcp",
            "MCP_SERVICE_TOKEN": MCP_TOKEN,
            "MULTI_AGENT_WORKERS": "3",
            "MULTI_AGENT_QUEUE_CAPACITY": "9",
        }
    )

    assert settings.token == TOKEN
    assert settings.template_paths == (FIXTURES / "workflow.yaml",)
    assert settings.tool_catalog_paths == (Path("a.json"), Path("b.json"))
    assert (settings.model_attempts, settings.model_fallback) == (3, "fail")
    assert settings.mcp_enabled is True
    assert (settings.workers, settings.queue_capacity) == (3, 9)
    assert TOKEN not in repr(settings)


@pytest.mark.parametrize(
    ("environment", "message"),
    [
        ({}, "is required"),
        ({"MULTI_AGENT_SERVICE_TOKEN": "short"}, "32-128 URL-safe"),
        ({"MULTI_AGENT_SERVICE_TOKEN": TOKEN, "MULTI_AGENT_PROVIDER": "x"}, "MULTI_AGENT_PROVIDER"),
        (
            {"MULTI_AGENT_SERVICE_TOKEN": TOKEN, "MULTI_AGENT_TOOL_TRANSPORT": "x"},
            "TOOL_TRANSPORT",
        ),
        (
            {"MULTI_AGENT_SERVICE_TOKEN": TOKEN, "MULTI_AGENT_MODEL_FALLBACK": "x"},
            "MODEL_FALLBACK",
        ),
        ({"MULTI_AGENT_SERVICE_TOKEN": TOKEN, "MULTI_AGENT_MODEL_ATTEMPTS": "9"}, "ATTEMPTS"),
        (
            {"MULTI_AGENT_SERVICE_TOKEN": TOKEN, "MULTI_AGENT_MODEL_TIMEOUT_SECONDS": "0"},
            "TIMEOUT",
        ),
        ({"MULTI_AGENT_SERVICE_TOKEN": TOKEN, "MULTI_AGENT_WORKERS": "0"}, "WORKERS"),
        ({"MULTI_AGENT_SERVICE_TOKEN": TOKEN, "MULTI_AGENT_WORKERS": "two"}, "Invalid"),
    ],
)
def test_invalid_settings_fail_fast(environment: dict[str, str], message: str) -> None:
    with pytest.raises(SettingsError, match=message):
        MultiAgentSettings.from_environment(environment)


def test_gateway_selection(tmp_path: Path) -> None:
    catalog = catalog_file(tmp_path)
    base = MultiAgentSettings(repository_root=tmp_path)

    fixture = build_gateway(
        MultiAgentSettings(tool_fixture_path=FIXTURES / "tools.json", repository_root=tmp_path)
    )
    assert isinstance(fixture, FixtureToolGateway)

    none = build_gateway(base)
    assert isinstance(none, UnavailableToolGateway)
    assert none.health()[0] is False

    http = build_gateway(
        MultiAgentSettings(repository_root=tmp_path, tool_catalog_paths=(catalog,))
    )
    assert isinstance(http, CatalogToolGateway) and http.transport == "http"

    mcp = build_gateway(
        MultiAgentSettings(
            repository_root=tmp_path,
            tool_catalog_paths=(catalog,),
            mcp_enabled=True,
            mcp_service_token=MCP_TOKEN,
        )
    )
    assert isinstance(mcp, CatalogToolGateway) and mcp.transport == "mcp"

    with pytest.raises(SettingsError, match="MCP_SERVICE_TOKEN"):
        build_gateway(MultiAgentSettings(repository_root=tmp_path, tool_transport="mcp"))


def test_definitions_are_discovered_from_enabled_feature_catalogues(tmp_path: Path) -> None:
    catalog = catalog_file(tmp_path)
    projection = tmp_path / "deployment" / "enabled-features.v1.json"
    projection.parent.mkdir()
    projection.write_text(
        json.dumps({"features": [{"ai": {"tool_catalog": catalog.name}}, {"ai": None}, "x"]}),
        encoding="utf-8",
    )

    gateway = build_gateway(MultiAgentSettings(repository_root=tmp_path))

    assert isinstance(gateway, UnavailableToolGateway)
    assert gateway.definition("example.record.v1") is not None

    catalog.write_text("{not json", encoding="utf-8")
    assert (
        build_gateway(MultiAgentSettings(repository_root=tmp_path)).definition("example.record.v1")
        is None
    )


def test_registry_discovers_enabled_feature_manifests(tmp_path: Path) -> None:
    projection = tmp_path / "deployment" / "enabled-features.v1.json"
    projection.parent.mkdir()
    projection.write_text(
        json.dumps(
            {
                "features": [
                    {"owner": "student-9", "feature_key": "example-feature"},
                    {"owner": "student-8", "feature_key": "other-feature"},
                ]
            }
        ),
        encoding="utf-8",
    )
    for owner in ("student-9", "student-8"):
        manifest = tmp_path / owner / "config" / "multi-agent" / "workflow.yaml"
        manifest.parent.mkdir(parents=True)
        manifest.write_text((FIXTURES / "workflow.yaml").read_text(encoding="utf-8"))

    registry = build_registry(MultiAgentSettings(repository_root=tmp_path))

    assert [entry.source for entry in registry.all()] == [
        "student-9/config/multi-agent/workflow.yaml"
    ]
    assert len(registry.invalid) == 1
    assert "does not match the owning feature other-feature" in registry.invalid[0]


def request(prompt_id: str, content: str) -> StructuredModelRequest:
    return StructuredModelRequest(
        run_id=uuid4(),
        role=ModelRole.PLANNER,
        model_profile="deterministic",
        prompt_id=prompt_id,
        prompt_version="v1",
        prompt_hash="0" * 64,
        rendered_input_hash="0" * 64,
        output_schema={"type": "object"},
        messages=(ModelMessage(role="user", content=content),),
    )


def test_deterministic_provider_rejects_unusable_requests() -> None:
    provider = DeterministicProvider()
    with pytest.raises(ModelProviderError) as invalid:
        provider.generate_structured(request("planner", "not json"))
    assert invalid.value.code == "deterministic_context_invalid"
    with pytest.raises(ModelProviderError) as unsupported:
        provider.generate_structured(request("other", "{}"))
    assert unsupported.value.code == "deterministic_role_unsupported"
    assert provider.health().reachable is True


def test_describe_result_is_short_and_factual() -> None:
    assert describe_result({}) == ["The tool returned an empty result."]
    described = describe_result({"items": [1, 2], "meta": {"a": 1}, "text": "x" * 300, "n": 1})
    assert described[:2] == ["items: 2 item(s).", "meta: object with 1 field(s)."]
    assert described[2].endswith("....")
    assert described[3] == "n = 1."


def test_provider_selection() -> None:
    explicit = select_provider({}, requested="deterministic")
    assert (explicit.mode, explicit.model_profile) == ("deterministic", "deterministic")

    offline = select_provider(
        {"OPENAI_API_KEY": "offline-local-development-only"}, requested="auto"
    )
    assert offline.mode == "deterministic"
    broken = select_provider({"AI_MODE_LLM_PROVIDER": "nope"}, requested="auto")
    assert broken.mode == "deterministic"

    model = select_provider({"OPENAI_API_KEY": "sk-test-key"}, requested="auto")
    assert model.mode == "model"
    assert model.detail.endswith("via AI-mode model registry")

    with pytest.raises(ValueError, match="MULTI_AGENT_MODEL_PROFILE"):
        select_provider(
            {"OPENAI_API_KEY": "sk-test-key", "MULTI_AGENT_MODEL_PROFILE": "missing"},
            requested="model",
        )
