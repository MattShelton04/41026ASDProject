"""Release 1 capability, deployment and HTTP scope integration boundaries."""

from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest

from ai_mode import create_app
from ai_mode.adapters.mcp_tools import McpToolExecutor
from ai_mode.adapters.retrieval import RETRIEVAL_TOOL, RetrievalToolExecutor
from ai_mode.configuration import ConfigurationError, Settings
from ai_mode.services import AppServices, build_services
from shared_testkit import ScriptedLLMProvider, assert_problem_detail

FEATURE = "student-1-propertyscope-data-platform"
TOKEN = "local-validation-only-token-1234567890"


@pytest.mark.parametrize("state", ["disabled", "ready", "unavailable", "timeout"])
def test_capabilities_observe_optional_services_without_exposing_targets(
    app_services: AppServices,
    monkeypatch: pytest.MonkeyPatch,
    state: str,
) -> None:
    enabled = state != "disabled"
    settings = Settings(
        mcp_enabled=enabled,
        rag_enabled=enabled,
        mcp_service_token=TOKEN,
        rag_service_token=TOKEN,
        rag_corpora=((FEATURE, "operator-guidance"),),
    )
    probe = Mock(return_value=httpx.Response(200 if state == "ready" else 503))
    if state == "timeout":
        probe.side_effect = httpx.ReadTimeout("secret transport diagnostics")
    monkeypatch.setattr("ai_mode.capabilities.httpx.get", probe)
    client = create_app(settings, services=app_services).test_client()
    response = client.get("/api/v1/capabilities")
    assert response.status_code == 200
    result = response.get_json()
    assert [item["status"] for item in result["services"]] == [
        "unavailable" if state == "timeout" else state
    ] * 2
    assert result["grounding_features"] == ([FEATURE] if enabled else [])
    assert TOKEN not in response.text and "127.0.0.1" not in response.text
    assert "secret transport" not in response.text
    assert probe.call_count == (2 if enabled else 0)
    if enabled:
        assert [call.args[0] for call in probe.call_args_list] == [
            "http://127.0.0.1:5011/health",
            "http://127.0.0.1:5012/health/ready",
        ]
        assert all(call.kwargs["follow_redirects"] is False for call in probe.call_args_list)
    assert client.get("/health/live").status_code == 200


@pytest.mark.parametrize(
    "environment",
    [
        {"AI_MODE_MCP_ENABLED": "true"},
        {"AI_MODE_RAG_ENABLED": "true", "RAG_SERVICE_TOKEN": "short"},
        {"MCP_SERVER_URL": "https://127.0.0.1:5011/mcp"},
        {"RAG_SERVER_URL": "http://external.example:5012"},
        {"RAG_SERVER_URL": "http://user:pass@127.0.0.1:5012"},
        {"MCP_SERVER_URL": "http://127.0.0.1:5011/mcp?token=secret"},
        {"AI_MODE_RAG_CORPORA": "invalid-scope"},
        {"AI_MODE_RAG_CORPORA": "feature:one,feature:two"},
        {"AI_MODE_ENVIRONMENT": "azure", "AI_MODE_MCP_ENABLED": "true", "MCP_SERVICE_TOKEN": TOKEN},
    ],
)
def test_unsafe_local_service_configuration_fails_before_network(
    environment: dict[str, str],
) -> None:
    with pytest.raises(ConfigurationError):
        Settings.from_env(environment)


@pytest.mark.parametrize(
    "mcp,rag,catalog",
    [(True, False, True), (False, True, True), (True, True, True), (True, True, False)],
)
def test_service_composition_selects_real_adapters_without_contacting_services(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mcp: bool,
    rag: bool,
    catalog: bool,
) -> None:
    monkeypatch.setattr(
        "ai_mode.services.build_provider", lambda *args, **kwargs: ScriptedLLMProvider([])
    )
    root = Path(__file__).resolve().parents[3]
    settings = Settings(
        database_path=tmp_path / "runs.sqlite3",
        mcp_enabled=mcp,
        rag_enabled=rag,
        mcp_service_token=TOKEN,
        rag_service_token=TOKEN,
        tool_catalog_paths=(root / "student-1/tool-catalog.yaml",) if catalog else (),
        rag_corpora=((FEATURE, "operator-guidance"),),
        queue_reconcile_interval_seconds=0.05,
    )
    services = build_services(settings)
    try:
        assert services.store.health().ready
        assert services.mcp_enabled is mcp
        assert services.rag_corpora == (((FEATURE, "operator-guidance"),) if rag else ())
        executor = services.closeables[1]
        if rag:
            assert isinstance(executor, RetrievalToolExecutor)
            if mcp:
                assert isinstance(executor.delegate, McpToolExecutor)
        else:
            assert isinstance(executor, McpToolExecutor)
    finally:
        services.close()


def test_backend_run_scope_automatically_adds_retrieval_without_widening_tools(
    app_services: AppServices,
) -> None:
    app_services.rag_corpora = ((FEATURE, "operator-guidance"),)
    client = create_app(services=app_services).test_client()
    response = client.post(
        "/api/v1/agent-runs",
        json={
            "feature_key": FEATURE,
            "objective": "Explain publication checks",
            "tool_allowlist": ["data.sources.v1"],
            "prompt_set": "default.v1",
        },
    )
    assert response.status_code == 202
    result = response.get_json()
    assert result["grounding"] == {"corpus_id": "operator-guidance"}
    assert result["prompt_set"] == "default.v8"
    assert result["tool_allowlist"] == ["data.sources.v1", RETRIEVAL_TOOL]


def test_grounded_idempotent_replay_does_not_duplicate_retrieval_permission(
    app_services: AppServices,
) -> None:
    app_services.rag_corpora = ((FEATURE, "operator-guidance"),)
    client = create_app(services=app_services).test_client()
    payload = {
        "feature_key": FEATURE,
        "objective": "Explain publication checks",
        "tool_allowlist": ["data.sources.v1", RETRIEVAL_TOOL],
        "grounding": {"corpus_id": "operator-guidance"},
    }
    headers = {"Idempotency-Key": "grounded-validation-request-1"}
    original = client.post("/api/v1/agent-runs", json=payload, headers=headers)
    repeated = client.post("/api/v1/agent-runs", json=payload, headers=headers)
    assert original.status_code == 202
    assert repeated.status_code == 202
    assert repeated.get_json()["id"] == original.get_json()["id"]
    assert repeated.get_json()["tool_allowlist"] == ["data.sources.v1", RETRIEVAL_TOOL]


def test_explicit_null_cannot_bypass_configured_grounding(app_services: AppServices) -> None:
    app_services.rag_corpora = ((FEATURE, "operator-guidance"),)
    response = (
        create_app(services=app_services)
        .test_client()
        .post(
            "/api/v1/agent-runs",
            json={"feature_key": FEATURE, "objective": "Explain publication", "grounding": None},
        )
    )
    assert response.status_code == 202
    assert response.get_json()["grounding"] == {"corpus_id": "operator-guidance"}
    assert response.get_json()["prompt_set"] == "default.v8"


@pytest.mark.parametrize(
    "feature,corpus,enabled",
    [
        (FEATURE, "different", True),
        ("other-feature", "operator-guidance", True),
        (FEATURE, "operator-guidance", False),
    ],
)
def test_request_cannot_select_an_unregistered_or_disabled_grounding_scope(
    app_services: AppServices, feature: str, corpus: str, enabled: bool
) -> None:
    app_services.rag_corpora = ((FEATURE, "operator-guidance"),) if enabled else ()
    response = (
        create_app(services=app_services)
        .test_client()
        .post(
            "/api/v1/agent-runs",
            json={
                "feature_key": feature,
                "objective": "Explain guidance",
                "grounding": {"corpus_id": corpus},
            },
        )
    )
    assert_problem_detail(response.get_json(), status=422, code="grounding_scope_unavailable")
