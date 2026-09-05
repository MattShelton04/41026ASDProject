"""Tests for the composable repository quality command."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence

import pytest
from scripts import check
from scripts.onboarding import (
    FeatureQualityCheck,
    FeatureQualityInputs,
    OnboardingConfigurationError,
)


def test_javascript_compile_sources_are_first_party_and_repository_relative() -> None:
    sources = check.javascript_sources()

    assert "shared/frontend/app.js" in sources
    for student in range(1, 6):
        assert f"student-{student}/frontend/app.js" in sources
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
    assert "shared/consumer-protocol/tests" in check.CORE_TEST_PATHS
    assert "--cov=shared_consumer_protocol" in check.commands_for("test")[0]
    assert all(command[:2] == ("node", "--check") for command in check.compile_commands())
    assert (check.sys.executable, "scripts/validate_workspace_packaging.py") in (
        check.commands_for("architecture")
    )
    assert (check.sys.executable, "scripts/generate_deployment.py", "--check") in (
        check.commands_for("architecture")
    )


def test_feature_quality_inputs_are_added_from_enabled_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        check,
        "discover_quality_inputs",
        lambda _root: FeatureQualityInputs(
            features=(
                FeatureQualityCheck(
                    feature_key="student-3-example",
                    owner="student-3",
                    python_test_paths=("student-3/tests",),
                    node_test_files=("student-3/tests/frontend.test.mjs",),
                    coverage_packages=("student_3_feature",),
                    coverage_fail_under=72,
                ),
            )
        ),
    )

    commands = check.commands_for("test")

    assert commands[1][-1] == "student-3/tests"
    assert "--cov=student_3_feature" in commands[1]
    assert "--cov-fail-under=72" in commands[1]
    assert "--ignore-glob=*/tests/e2e/*" in commands[1]
    assert commands[2][-1] == "student-3/tests/frontend.test.mjs"
    assert "student-1/tests" not in commands[1]


def test_discovery_failure_is_reported_before_running_commands(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        check,
        "commands_for",
        lambda _stage, *, write=False: (_ for _ in ()).throw(
            OnboardingConfigurationError("invalid selection")
        ),
    )

    assert check.main(["test"]) == 2
    assert "feature quality discovery failed: invalid selection" in capsys.readouterr().err


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
