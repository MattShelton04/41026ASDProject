"""The terminal probe checks each host AI server directly without starting or changing one."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from scripts import dev, release1_probe
from scripts.devtools import host_runtime
from scripts.release1_probe import OFF_TOPIC_QUERY, RegisteredFeature

FEATURE = RegisteredFeature("feature-9-demo", ("demo_lookup", "demo_search"), "demo-guidance")
TOKENS = {"ai-mode": "ai-secret-token", "mcp": "mcp-secret-token", "rag": "rag-secret-token"}
CHUNK = {"title": "Demo guidance", "excerpt": "Demo guidance explains the demo lookup.", "score": 0}


@pytest.fixture(autouse=True)
def resolved_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    def prepare(environment: dict[str, str], *, mode: str) -> dict[str, str]:
        assert mode == "combined"
        return {
            **environment,
            "AI_MODE_SERVICE_TOKEN": TOKENS["ai-mode"],
            "MCP_SERVICE_TOKEN": TOKENS["mcp"],
            "RAG_SERVICE_TOKEN": TOKENS["rag"],
        }

    monkeypatch.setattr(host_runtime, "prepare_environment", prepare)


def _handler(
    *, tools: tuple[str, ...] = FEATURE.tool_names, off_topic_status: str = "no_match"
) -> httpx.MockTransport:
    def respond(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        port = request.url.port
        if port == 5005:
            if path == "/health/live":
                return httpx.Response(200)
            authorised = request.headers.get("X-PropertyScope-AI-Token") == TOKENS["ai-mode"]
            return httpx.Response(200 if authorised else 401)
        if port == 5011:
            if request.headers.get("Authorization") != f"Bearer {TOKENS['mcp']}":
                return httpx.Response(401)
            if path == "/health":
                return httpx.Response(200, json={"status": "ready", "registered_tools": 2})
            assert json.loads(request.content)["method"] == "tools/list"
            listed = [{"name": name} for name in tools]
            return httpx.Response(
                200, json={"jsonrpc": "2.0", "id": 1, "result": {"tools": listed}}
            )
        if request.headers.get("Authorization") != f"Bearer {TOKENS['rag']}":
            return httpx.Response(401)
        if path == "/health/ready":
            return httpx.Response(200, json={"embedding_model": "local-model"})
        if path.endswith("/chunks"):
            version = {"corpus_version": "a" * 64, "document_count": 1, "chunk_count": 1}
            return httpx.Response(200, json={"version": version, "chunks": [CHUNK]})
        body = json.loads(request.content)
        assert body["min_score"] == release1_probe.GROUNDING_MIN_SCORE
        if body["query"] == OFF_TOPIC_QUERY:
            return httpx.Response(200, json={"status": off_topic_status, "citations": []})
        cited = {**CHUNK, "score": 0.91}
        return httpx.Response(200, json={"status": "ready", "citations": [cited]})

    return httpx.MockTransport(respond)


def _run(transport: httpx.BaseTransport, **kwargs: object) -> dict[str, object]:
    with httpx.Client(transport=transport) as client:
        return release1_probe.probe({}, client=client, features=(FEATURE,), **kwargs)


def _failed(evidence: dict[str, object]) -> list[str]:
    checks = evidence["checks"]
    assert isinstance(checks, list)
    return [check["check"] for check in checks if not check["passed"]]


def test_healthy_servers_pass_every_check_and_the_evidence_holds_no_token(
    tmp_path: Path,
) -> None:
    output = tmp_path / "evidence" / "probe.json"

    evidence = _run(_handler(), output=output)

    assert evidence["passed"] is True, _failed(evidence)
    assert evidence["services"] == {
        "ai-mode": "http://127.0.0.1:5005",
        "mcp": "http://127.0.0.1:5011/mcp",
        "rag": "http://127.0.0.1:5012",
    }
    names = {check["check"] for check in evidence["checks"]}  # type: ignore[union-attr]
    assert {
        "feature-9-demo tools",
        "feature-9-demo grounded retrieval",
        "feature-9-demo insufficient context",
    } <= names
    written = output.read_text(encoding="utf-8")
    assert json.loads(written) == evidence
    rendered = release1_probe.render(evidence)
    for token in TOKENS.values():
        assert token not in written
        assert token not in rendered
    assert rendered.endswith("All checks passed.")


def test_a_tool_missing_from_mcp_fails_that_features_check() -> None:
    evidence = _run(_handler(tools=("demo_lookup",)))

    assert _failed(evidence) == ["feature-9-demo tools"]
    checks = evidence["checks"]
    assert isinstance(checks, list)
    assert any("missing demo_search" in check["detail"] for check in checks)


def test_an_off_topic_match_fails_the_insufficient_context_check() -> None:
    evidence = _run(_handler(off_topic_status="ready"))

    assert _failed(evidence) == ["feature-9-demo insufficient context"]


def test_an_unreachable_service_is_reported_without_hiding_the_others() -> None:
    healthy = _handler()

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.port == 5012:
            raise httpx.ConnectError("refused", request=request)
        return healthy.handle_request(request)

    evidence = _run(httpx.MockTransport(respond))

    assert evidence["passed"] is False
    assert _failed(evidence) == ["reachable"]
    assert "Some checks failed." in release1_probe.render(evidence)


def test_probe_refuses_to_run_in_ci() -> None:
    with pytest.raises(RuntimeError, match="local-only"):
        release1_probe.probe({"CI": "true"}, features=(FEATURE,))


def test_registered_features_cover_every_enabled_ai_feature() -> None:
    features = release1_probe.registered_features()

    assert features
    for feature in features:
        assert feature.tool_names, feature.feature_key


def test_ai_probe_command_reports_failure_through_its_exit_code(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    evidence = {"passed": False, "services": {}, "checks": []}
    monkeypatch.setattr(dev, "_load_development_environment", lambda _path: None)
    monkeypatch.setattr(release1_probe, "probe", lambda _environment, *, output: evidence)

    assert dev.main(["ai", "probe"]) == 1
    assert "Some checks failed." in capsys.readouterr().out
