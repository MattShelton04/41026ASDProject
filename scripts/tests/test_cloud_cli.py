"""`dev.py cloud` wrapper and the cloud AI host-env renderer; no Azure, Docker or Bash needed."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
from scripts import dev
from scripts.devtools import cloud, host_runtime
from scripts.devtools.cli import build_parser
from scripts.devtools.config import REPOSITORY_ROOT

BASH = "/usr/bin/bash"


def _command(*argv: str) -> tuple[str, ...]:
    return cloud.build_command(build_parser().parse_args(["cloud", *argv]), bash=BASH)


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (("provision",), ["provision"]),
        (("push", "--dry-run"), ["--dry-run", "push"]),
        (("deploy",), ["deploy"]),
        (("secrets",), ["secrets"]),
        (("status",), ["status"]),
        (("outputs",), ["outputs"]),
        (("all", "--dry-run"), ["--dry-run", "all"]),
        (("smoke",), ["smoke"]),
        (
            ("smoke", "--output-dir", "out", "--expect-ai"),
            ["smoke", "--output-dir", "out", "--expect-ai"],
        ),
        (("ai", "on"), ["ai", "on"]),
        (("ai", "off", "--dry-run"), ["--dry-run", "ai", "off"]),
        (("logs",), ["logs", "", "80"]),
        (("logs", "f1-runner", "--lines", "20"), ["logs", "f1-runner", "20"]),
        (("validate", "endpoint"), ["validate-endpoint"]),
        (("validate", "data"), ["validate-data"]),
    ],
)
def test_cloud_actions_map_onto_deploy_script(argv: tuple[str, ...], expected: list[str]) -> None:
    assert _command(*argv) == (BASH, "deployment/azure/deploy.sh", *expected)


def test_logs_rejects_non_positive_line_counts() -> None:
    with pytest.raises(RuntimeError, match="--lines"):
        _command("logs", "--lines", "0")


def test_ai_state_is_restricted_to_on_and_off() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["cloud", "ai", "maybe"])


def test_dev_main_runs_deploy_script_from_the_repository_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_run(command: tuple[str, ...], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append({"command": command, **kwargs})
        return subprocess.CompletedProcess(command, 3)

    monkeypatch.setattr(cloud, "bash_executable", lambda: BASH)
    monkeypatch.setattr(subprocess, "run", fake_run)

    assert dev.main(["cloud", "deploy", "--dry-run"]) == 3
    assert calls == [
        {
            "command": (BASH, "deployment/azure/deploy.sh", "--dry-run", "deploy"),
            "cwd": REPOSITORY_ROOT,
            "check": False,
        }
    ]


def test_deploy_script_exists_and_is_bash() -> None:
    assert cloud.DEPLOY_SCRIPT.read_text(encoding="utf-8").startswith("#!/usr/bin/env bash\n")


def test_bash_override_wins() -> None:
    assert cloud.bash_executable(environment={"PROPERTYSCOPE_BASH": "/opt/bash"}) == "/opt/bash"


def test_posix_uses_bash_on_path() -> None:
    found = cloud.bash_executable(
        environment={}, platform="posix", which=lambda name: f"/usr/bin/{name}"
    )
    assert found == "/usr/bin/bash"


def test_posix_without_bash_fails_clearly() -> None:
    with pytest.raises(RuntimeError, match="bash is required"):
        cloud.bash_executable(environment={}, platform="posix", which=lambda _name: None)


def test_windows_prefers_git_bash_next_to_git() -> None:
    git = Path("C:/Program Files/Git/cmd/git.exe")
    expected = git.resolve().parent.parent / "bin" / "bash.exe"

    found = cloud.bash_executable(
        environment={},
        platform="nt",
        which=lambda name: {"git": str(git), "bash": "C:/Windows/System32/bash.exe"}.get(name),
        is_file=lambda path: path == expected,
    )

    assert found == str(expected)


def test_windows_never_uses_the_wsl_launcher() -> None:
    with pytest.raises(RuntimeError, match="Git Bash is required"):
        cloud.bash_executable(
            environment={},
            platform="nt",
            which=lambda name: "C:/Windows/System32/bash.exe" if name == "bash" else None,
            is_file=lambda _path: False,
        )


def test_windows_falls_back_to_program_files_git() -> None:
    expected = Path("D:/Apps", "Git", "bin", "bash.exe")

    found = cloud.bash_executable(
        environment={"ProgramFiles": "D:/Apps"},
        platform="nt",
        which=lambda _name: None,
        is_file=lambda path: path == expected,
    )

    assert found == str(expected)


TOKENS = {
    "AI_MODE_SERVICE_TOKEN": "a" * 64,
    "MCP_SERVICE_TOKEN": "b" * 64,
    "RAG_SERVICE_TOKEN": "c" * 64,
    "MULTI_AGENT_SERVICE_TOKEN": "d" * 64,
}


def test_host_environment_reuses_the_local_preparation_without_provider_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(host_runtime, "HOST_DIRECTORY", tmp_path)
    environment = {
        **TOKENS,
        "OPENAI_API_KEY": "provider-credential-placeholder",
        "PATH": "/usr/bin",
        "HOME": "/var/lib/propertyscope-ai",
    }

    values = cloud.host_environment(environment, mode="combined")

    assert values["AI_MODE_ENVIRONMENT"] == "local"
    assert values["AI_MODE_MCP_ENABLED"] == "true"
    assert values["AI_MODE_RAG_ENABLED"] == "true"
    assert values["AI_MODE_SERVICE_TOKEN"] == TOKENS["AI_MODE_SERVICE_TOKEN"]
    assert values["MCP_SERVICE_TOKEN"] == TOKENS["MCP_SERVICE_TOKEN"]
    assert values["MULTI_AGENT_PORT"] == "5013"
    assert values["MCP_SERVER_URL"] == "http://127.0.0.1:5011/mcp"
    assert values["AI_MODE_TOOL_CATALOG_PATHS"]
    assert "OPENAI_API_KEY" not in values
    assert "PATH" not in values and "HOME" not in values
    # The token files of a local launcher are not created: Key Vault supplied every token.
    assert not (tmp_path / "ai-mode.token").exists()


def test_host_environment_requires_key_vault_tokens() -> None:
    with pytest.raises(RuntimeError, match="MCP_SERVICE_TOKEN"):
        cloud.host_environment({"AI_MODE_SERVICE_TOKEN": "a" * 64}, mode="combined")


def test_environment_file_is_quoted_and_refuses_ambiguous_characters() -> None:
    rendered = cloud.render_environment_file({"A": "1", "B": "/opt/x,y z"})
    assert rendered.splitlines()[1:] == ['A="1"', 'B="/opt/x,y z"']
    for value in ('a"b', "a$b", "a\\b", "a\nb", "a`b"):
        with pytest.raises(RuntimeError):
            cloud.render_environment_file({"BAD": value})


def test_host_env_entry_point_prints_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(host_runtime, "HOST_DIRECTORY", tmp_path)
    monkeypatch.setattr(
        cloud, "host_environment", lambda environment, mode: {"AI_MODE_ENVIRONMENT": mode}
    )

    assert cloud.main(["host-env", "--mode", "direct"]) == 0
    assert 'AI_MODE_ENVIRONMENT="direct"' in capsys.readouterr().out


def test_host_env_entry_point_reports_missing_tokens(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for variable in TOKENS:
        monkeypatch.delenv(variable, raising=False)

    assert cloud.main(["host-env"]) == 1
    assert "AI_MODE_SERVICE_TOKEN" in capsys.readouterr().err
