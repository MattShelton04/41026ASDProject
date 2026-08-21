"""Deterministic tests for the real-provider diagnostic contract."""

import json

import pytest

from agent_core import ModelMetrics, ModelRole, ProviderHealth, StructuredModelResult
from ai_mode import provider_diagnostics
from ai_mode.provider_diagnostics import run_smoke
from shared_testkit import ScriptedLLMProvider


def _result(*, message: str = "provider-ready") -> StructuredModelResult:
    return StructuredModelResult(
        content={
            "ready": True,
            "message": message,
            "items": [{"sequence": 1, "arguments": {}}],
        },
        provider="scripted",
        model="test-model",
        metrics=ModelMetrics(total_duration_ms=1),
    )


def test_smoke_uses_provider_port_and_returns_machine_readable_evidence() -> None:
    provider = ScriptedLLMProvider([_result()])

    report = run_smoke(provider)

    assert report["status"] == "ready"
    assert report["model"] == "test-model"
    assert len(provider.requests) == 1
    assert provider.requests[0].role is ModelRole.PLANNER
    assert provider.requests[0].temperature == 0
    assert provider.requests[0].output_schema["additionalProperties"] is False


def test_smoke_stops_before_generation_when_provider_is_not_ready() -> None:
    provider = ScriptedLLMProvider(
        [_result()],
        health=ProviderHealth(reachable=False, detail="credentials are not configured"),
    )

    with pytest.raises(RuntimeError, match="credentials are not configured"):
        run_smoke(provider)

    assert provider.requests == []


def test_smoke_rejects_semantically_unexpected_output() -> None:
    provider = ScriptedLLMProvider([_result(message="something-else")])

    with pytest.raises(RuntimeError, match="unexpected diagnostic content"):
        run_smoke(provider)


class CloseableScriptedProvider(ScriptedLLMProvider):
    def __init__(
        self,
        outcomes: list[StructuredModelResult],
        *,
        health: ProviderHealth | None = None,
    ) -> None:
        super().__init__(outcomes, health=health)
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_console_entrypoint_reports_success_and_closes_provider(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    provider = CloseableScriptedProvider([_result()])
    monkeypatch.setattr(provider_diagnostics, "build_provider", lambda *_args, **_kwargs: provider)
    monkeypatch.setattr("sys.argv", ["ai-mode-provider-smoke"])

    exit_code = provider_diagnostics.main()

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ready"
    assert provider.closed is True


def test_console_entrypoint_selects_a_role_declared_by_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = CloseableScriptedProvider([_result()])
    monkeypatch.setattr(provider_diagnostics, "build_provider", lambda *_args, **_kwargs: provider)
    monkeypatch.setattr("sys.argv", ["ai-mode-provider-smoke", "--profile", "remote-standard.v1"])

    assert provider_diagnostics.main() == 0
    assert provider.requests[0].role is ModelRole.PLANNER


def test_console_entrypoint_returns_nonzero_with_safe_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    provider = CloseableScriptedProvider(
        [],
        health=ProviderHealth(reachable=False, detail="credentials are not configured"),
    )
    monkeypatch.setattr(provider_diagnostics, "build_provider", lambda *_args, **_kwargs: provider)
    monkeypatch.setattr("sys.argv", ["ai-mode-provider-smoke"])

    exit_code = provider_diagnostics.main()

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "credentials are not configured" in captured.err
    assert provider.closed is True
