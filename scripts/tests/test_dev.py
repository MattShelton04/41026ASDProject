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
    return commands


def test_up_prepares_model_and_starts_complete_stack(
    captured_commands: list[tuple[str, ...]],
) -> None:
    assert dev.main(["up"]) == 0

    assert captured_commands[0][:2] == ("docker", "info")
    assert captured_commands[1][-1] == "ollama"
    assert captured_commands[2][-3:] == ("run", "--rm", "ollama-init")
    assert captured_commands[3][-4:] == dev.APPLICATION_SERVICES
    for filename in dev.COMPOSE_FILES:
        assert filename in captured_commands[3]


def test_up_can_skip_already_prepared_model(
    captured_commands: list[tuple[str, ...]],
) -> None:
    assert dev.main(["up", "--skip-model-pull"]) == 0

    assert len(captured_commands) == 3
    assert all("ollama-init" not in command for command in captured_commands)


def test_rebuild_defaults_to_all_application_services(
    captured_commands: list[tuple[str, ...]],
) -> None:
    assert dev.main(["rebuild"]) == 0

    build = captured_commands[1]
    recreate = captured_commands[2]
    assert build[-5:] == ("build", *dev.APPLICATION_SERVICES)
    assert "--force-recreate" in recreate
    assert recreate[-4:] == dev.APPLICATION_SERVICES


def test_down_preserves_named_volumes(captured_commands: list[tuple[str, ...]]) -> None:
    assert dev.main(["down"]) == 0

    command = captured_commands[-1]
    assert command[-2:] == ("down", "--remove-orphans")
    assert "--volumes" not in command
