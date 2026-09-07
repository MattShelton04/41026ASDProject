"""Boundary checks for the optional container process entries."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from flask import Flask
from scripts.devtools import container_entry as entry


@pytest.mark.parametrize("service", ["ai-mode", "mcp", "rag"])
@pytest.mark.parametrize("environment", ["local", "azure", "production", ""])
def test_container_entry_requires_explicit_local_compose(service: str, environment: str) -> None:
    with pytest.raises(RuntimeError, match="compose"):
        entry.validate_environment(service, {"AI_MODE_ENVIRONMENT": environment})


@pytest.mark.parametrize(
    ("service", "flags"),
    [
        ("mcp", {}),
        ("rag", {}),
        ("ai-mode", {"AI_MODE_MCP_ENABLED": "true"}),
        ("ai-mode", {"AI_MODE_RAG_ENABLED": "1"}),
    ],
)
def test_advanced_container_services_remain_disabled_in_ci(
    service: str, flags: dict[str, str]
) -> None:
    with pytest.raises(RuntimeError, match="disabled in CI"):
        entry.validate_environment(
            service, {"AI_MODE_ENVIRONMENT": "compose", "CI": "true", **flags}
        )
    entry.validate_environment("ai-mode", {"AI_MODE_ENVIRONMENT": "compose", "CI": "1"})


def test_container_ai_protects_api_and_history_but_allows_liveness() -> None:
    app = Flask(__name__)
    for path in ("/health/live", "/health/ready", "/operations/ai-mode/", "/api/v1/agent-runs"):
        app.add_url_rule(path, endpoint=path, view_func=lambda: "ok")
    token = "test-container-token-1234567890123456"
    entry.protect_entry(app, token)
    client = app.test_client()
    assert client.get("/health/live").status_code == 200
    for path in ("/health/ready", "/operations/ai-mode/", "/api/v1/agent-runs"):
        assert client.get(path).status_code == 401
        assert client.get(path, headers={"X-PropertyScope-AI-Token": "wrong"}).status_code == 401
        assert client.get(path, headers={"X-PropertyScope-AI-Token": token}).status_code == 200


@pytest.mark.parametrize("token", ["", "short", "bad token" * 10, "x" * 129])
def test_container_ai_requires_a_valid_proxy_credential(token: str) -> None:
    with pytest.raises(RuntimeError, match="AI_MODE_SERVICE_TOKEN"):
        entry.protect_entry(Flask(__name__), token)


@pytest.mark.parametrize("service", ["ai-mode", "rag"])
def test_wsgi_entries_replace_process_with_one_worker(
    service: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AI_MODE_ENVIRONMENT", "compose")
    monkeypatch.delenv("CI", raising=False)
    execute = Mock()
    monkeypatch.setattr(entry.os, "execvp", execute)
    entry.serve(service)
    executable, arguments = execute.call_args.args
    assert executable == "gunicorn"
    assert "--workers=1" in arguments
    assert f"--bind=0.0.0.0:{entry.PORTS[service]}" in arguments
    assert arguments[-1].endswith(f"create_wsgi_app('{service}')")


@pytest.mark.parametrize("service", ["ai-mode", "mcp", "rag"])
def test_container_health_uses_liveness_and_keeps_tokens_out_of_url(
    service: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = "test-probe-token-1234567890123456"
    monkeypatch.setenv(f"{service.upper()}_SERVICE_TOKEN", token)
    response = Mock(status=200)
    request_context = Mock()
    request_context.__enter__ = Mock(return_value=response)
    request_context.__exit__ = Mock(return_value=False)
    open_url = Mock(return_value=request_context)
    monkeypatch.setattr(entry, "urlopen", open_url)
    entry.health(service)
    request = open_url.call_args.args[0]
    assert request.full_url.startswith(f"http://127.0.0.1:{entry.PORTS[service]}/health")
    assert token not in request.full_url
    assert request.get_header("Authorization") == (
        None if service == "ai-mode" else f"Bearer {token}"
    )
