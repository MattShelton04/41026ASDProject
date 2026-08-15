"""Tests for the cross-platform development command planner."""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from scripts import dev


@pytest.fixture
def captured_commands(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    commands: list[tuple[str, ...]] = []

    def capture(command: Sequence[str]) -> None:
        commands.append(tuple(command))

    monkeypatch.setattr(dev, "_run", capture)
    monkeypatch.setattr(dev, "_nvidia_runtime_available", lambda: False)
    return commands


def test_up_prepares_model_and_starts_complete_stack(
    captured_commands: list[tuple[str, ...]],
) -> None:
    assert dev.main(["up"]) == 0

    assert captured_commands[0][:2] == ("docker", "info")
    assert captured_commands[1][-1] == "ollama"
    assert captured_commands[2][-3:] == ("run", "--rm", "ollama-init")
    assert captured_commands[3][-len(dev.APPLICATION_SERVICES) :] == dev.APPLICATION_SERVICES
    for filename in dev.COMPOSE_FILES:
        assert filename in captured_commands[3]
    assert "propertyscope-shared-frontend" in captured_commands[3]
    assert "docker-compose.shared-shell.yml" not in dev.COMPOSE_FILES


def test_up_can_skip_already_prepared_model(
    captured_commands: list[tuple[str, ...]],
) -> None:
    assert dev.main(["up", "--skip-model-pull"]) == 0

    assert len(captured_commands) == 3
    assert all("ollama-init" not in command for command in captured_commands)


def test_up_automatically_uses_available_nvidia_runtime(
    captured_commands: list[tuple[str, ...]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dev, "_nvidia_runtime_available", lambda: True)

    assert dev.main(["up", "--skip-model-pull"]) == 0

    assert all(dev.GPU_COMPOSE_FILE in command for command in captured_commands[1:])


def test_up_can_explicitly_keep_portable_cpu_runtime(
    captured_commands: list[tuple[str, ...]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dev, "_nvidia_runtime_available", lambda: True)

    assert dev.main(["up", "--skip-model-pull", "--cpu-only"]) == 0

    assert all(dev.GPU_COMPOSE_FILE not in command for command in captured_commands)


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
    assert dev.main(["up", "--full-data", "--skip-model-pull"]) == 0

    application_up = captured_commands[-1]
    assert dev.FULL_DATA_COMPOSE_FILE in application_up
    assert application_up[2:4] == ("--project-name", dev.FULL_DATA_PROJECT_NAME)
    assert "full-data" in application_up


def test_default_stack_does_not_enable_full_data(
    captured_commands: list[tuple[str, ...]],
) -> None:
    assert dev.main(["config"]) == 0

    command = captured_commands[-1]
    assert dev.FULL_DATA_COMPOSE_FILE not in command
    assert "full-data" not in command
