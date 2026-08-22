"""Tests for the cross-platform development command planner."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path

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
    monkeypatch.setattr(dev, "_psi_cache_weeks", lambda: ())
    monkeypatch.setattr(
        dev, "_write_openai_secret", lambda _value, *, full_data: dev.Path("secret")
    )
    monkeypatch.setattr(dev, "_remove_openai_secret", lambda *, full_data: None)
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
    assert "--build" in captured_commands[1]
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
    monkeypatch.setattr(
        dev, "_write_openai_secret", lambda _value, *, full_data: dev.Path("secret")
    )
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    assert dev.main(["up", "--full-data"]) == 0

    assert all(
        isinstance(environment, dict)
        and environment["PROPERTYSCOPE_PSI_TRANSPORT_ENABLED"] == "true"
        and environment["PROPERTYSCOPE_PSI_CACHED_YEARS"] == "2024,2025"
        and environment["PROPERTYSCOPE_PSI_CACHED_WEEKS"] == "2026-08-03,2026-08-10"
        for environment in environments[1:]
    )


def test_offline_up_needs_no_credential_and_disables_provider_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environments: list[object] = []
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        dev,
        "_run",
        lambda command, *, environment=None: environments.append(environment),
    )
    monkeypatch.setattr(
        dev, "_write_openai_secret", lambda _value, *, full_data: dev.Path("secret")
    )

    assert dev.main(["up", "--offline"]) == 0

    environment = environments[-1]
    assert isinstance(environment, dict)
    assert environment["AI_MODE_REQUIRE_PROVIDER_READY"] == "false"
    assert "OPENAI_API_KEY" not in environment


def test_reset_removes_only_selected_project_volumes(
    captured_commands: list[tuple[str, ...]],
) -> None:
    assert dev.main(["reset", "--full-data"]) == 0

    down, prune = captured_commands[-2:]
    assert down[-3:] == ("down", "--remove-orphans", "--volumes")
    assert prune == (
        "docker",
        "volume",
        "prune",
        "--all",
        "--force",
        "--filter",
        f"label=com.docker.compose.project={dev.FULL_DATA_PROJECT_NAME}",
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


def test_collection_command_runs_registered_pipeline_to_candidate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    profile_directory = tmp_path / "job-profiles"
    profile_directory.mkdir()
    (profile_directory / "fixture-property.yaml").write_text(
        """key: fixture-property-full
scope_profiles:
  test: {maximum_records: 20}
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(dev, "JOB_PROFILE_DIRECTORY", profile_directory)
    run_responses = iter(
        (
            {"run": {"id": "run-1", "status": "queued"}},
            {"run": {"id": "run-1", "status": "succeeded", "error_json": None}},
        )
    )

    def propertyscope(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/jobs"):
            return httpx.Response(
                200,
                json={"items": [{"id": "job-1", "profile_key": "fixture-property-full"}]},
            )
        if path.endswith("/plans"):
            assert json.loads(request.content)["scope"]["profile"] == "test"
            return httpx.Response(200, json={"network_required": False})
        if path.endswith("/runs") and request.method == "POST":
            return httpx.Response(201, json=next(run_responses))
        if path.endswith("/ingestion-runs/run-1"):
            return httpx.Response(200, json=next(run_responses))
        if path.endswith("/dataset-releases"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "release-1",
                            "ingestion_run_id": "run-1",
                            "status": "candidate",
                            "record_count": 20,
                        }
                    ]
                },
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    with httpx.Client(
        base_url="https://propertyscope.test/api/data-platform/v1/",
        transport=httpx.MockTransport(propertyscope),
    ) as client:
        result = dev._collect_with_client(
            client,
            job_profile="fixture-property",
            profile="test",
            wait=True,
            timeout_seconds=5,
            poll_seconds=0,
        )

    assert result["run"]["status"] == "succeeded"
    assert result["release"]["status"] == "candidate"


def test_collection_rejects_unregistered_scope_profile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(dev, "JOB_PROFILE_DIRECTORY", tmp_path)
    (tmp_path / "fixture-property.yaml").write_text(
        "key: fixture-property-full\nscope_profiles: {test: {maximum_records: 20}}\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="does not define"):
        dev._collection_definition("fixture-property", "full-data")
