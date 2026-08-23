"""Tests for the composable repository quality command."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence

import pytest
from scripts import check


def test_javascript_compile_sources_are_first_party_and_repository_relative() -> None:
    sources = check.javascript_sources()

    assert "shared/frontend/app.js" in sources
    assert "student-1/frontend/app.js" in sources
    assert all(not source.startswith(("/", "C:/", "C:\\")) for source in sources)
    assert all("/vendor/" not in source for source in sources)
    assert sources == tuple(sorted(set(sources)))


def test_named_stages_are_composable_and_check_preserves_order() -> None:
    expected = tuple(
        command
        for stage in (
            "format",
            "lint",
            "architecture",
            "styles",
            "typecheck",
            "compile",
            "test",
        )
        for command in check.commands_for(stage)
    )

    assert check.commands_for("check") == expected
    assert "--check" in check.commands_for("format")[0]
    assert "--check" not in check.commands_for("format", write=True)[0]
    assert all(command[:2] == ("node", "--check") for command in check.compile_commands())


def test_main_forwards_the_first_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, ...]] = []
    commands = (("first",), ("second",), ("third",))
    monkeypatch.setattr(check, "commands_for", lambda _stage, *, write=False: commands)

    def run(command: Sequence[str], **_kwargs: object) -> None:
        calls.append(tuple(command))
        if command[0] == "second":
            raise subprocess.CalledProcessError(7, command)

    monkeypatch.setattr(check.subprocess, "run", run)

    assert check.main(["lint"]) == 7
    assert calls == [("first",), ("second",)]


def test_default_stage_is_the_aggregate_check(monkeypatch: pytest.MonkeyPatch) -> None:
    stages: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        check,
        "commands_for",
        lambda stage, *, write=False: stages.append((stage, write)) or (),
    )

    assert check.main([]) == 0
    assert stages == [("check", False)]
