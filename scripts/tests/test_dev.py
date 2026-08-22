"""Tests for the cross-platform development command planner."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import httpx
import pytest
from scripts import dev


@pytest.fixture
def captured_commands(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    commands: list[tuple[str, ...]] = []

    def capture(command: Sequence[str], *, environment: object = None) -> None:
        del environment
        commands.append(tuple(command))

    monkeypatch.setattr(dev, "_run", capture)
    monkeypatch.setattr(dev, "_psi_cache_years", lambda: ())
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    return commands


def test_up_fails_before_docker_when_openai_credential_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    commands: list[tuple[str, ...]] = []
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(dev, "_run", lambda command, **_kwargs: commands.append(tuple(command)))

    assert dev.main(["up"]) == 1
    assert commands == []
    assert "OPENAI_API_KEY is required" in capsys.readouterr().err


def test_up_starts_complete_stack(
    captured_commands: list[tuple[str, ...]],
) -> None:
    assert dev.main(["up"]) == 0

    assert captured_commands[0][:2] == ("docker", "info")
    assert captured_commands[1][-len(dev.APPLICATION_SERVICES) :] == dev.APPLICATION_SERVICES
    for filename in dev.COMPOSE_FILES:
        assert filename in captured_commands[1]
    assert "propertyscope-shared-frontend" in captured_commands[1]
    assert "docker-compose.shared-shell.yml" not in dev.COMPOSE_FILES


def test_rebuild_defaults_to_all_application_services(
    captured_commands: list[tuple[str, ...]],
) -> None:
    assert dev.main(["rebuild"]) == 0

    build = captured_commands[1]
    recreate = captured_commands[2]
    assert build[-(len(dev.BUILD_SERVICES) + 1) :] == ("build", *dev.BUILD_SERVICES)
    assert "--force-recreate" in recreate
    assert recreate[-len(dev.BUILD_SERVICES) :] == dev.BUILD_SERVICES


def test_down_preserves_named_volumes(captured_commands: list[tuple[str, ...]]) -> None:
    assert dev.main(["down"]) == 0

    command = captured_commands[-1]
    assert command[-2:] == ("down", "--remove-orphans")
    assert "--volumes" not in command


def test_full_data_is_explicit_and_uses_isolated_project(
    captured_commands: list[tuple[str, ...]],
) -> None:
    assert dev.main(["up", "--full-data"]) == 0

    application_up = captured_commands[-1]
    assert dev.FULL_DATA_COMPOSE_FILE in application_up
    assert application_up[2:4] == ("--project-name", dev.FULL_DATA_PROJECT_NAME)
    assert "full-data" in application_up


def test_full_data_exposes_psi_and_advertises_cached_years(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environments: list[object] = []

    def capture(command: Sequence[str], *, environment: object = None) -> None:
        del command
        environments.append(environment)

    monkeypatch.setattr(dev, "_run", capture)
    monkeypatch.setattr(dev, "_psi_cache_years", lambda: (2024, 2025))
    monkeypatch.setattr(dev, "_psi_cache_weeks", lambda: ("2026-08-03", "2026-08-10"))
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    assert dev.main(["up", "--full-data"]) == 0

    assert all(
        isinstance(environment, dict)
        and environment["PROPERTYSCOPE_PSI_TRANSPORT_ENABLED"] == "true"
        and environment["PROPERTYSCOPE_PSI_CACHED_YEARS"] == "2024,2025"
        and environment["PROPERTYSCOPE_PSI_CACHED_WEEKS"] == "2026-08-03,2026-08-10"
        for environment in environments[1:]
    )


def test_psi_host_sync_handles_publisher_range_only_response() -> None:
    payload = b"PK\x03\x04official-psi"

    def source(request: httpx.Request) -> httpx.Response:
        if "Range" not in request.headers:
            return httpx.Response(403, content=b"publisher policy")
        return httpx.Response(
            206,
            content=payload,
            headers={"Content-Range": f"bytes 0-{len(payload) - 1}/{len(payload)}"},
        )

    with httpx.Client(transport=httpx.MockTransport(source)) as client:
        assert dev._download_psi_archive(client, "https://example.test/2025.zip") == payload


def test_complete_psi_scope_resolves_history_and_current_mondays() -> None:
    weeks = dev._current_psi_weeks(date(2026, 1, 13))

    assert weeks == (date(2026, 1, 5), date(2026, 1, 12))


def test_default_stack_does_not_enable_full_data(
    captured_commands: list[tuple[str, ...]],
) -> None:
    assert dev.main(["config"]) == 0

    command = captured_commands[-1]
    assert dev.FULL_DATA_COMPOSE_FILE not in command
    assert "full-data" not in command
