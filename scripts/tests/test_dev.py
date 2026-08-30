"""Tests for the cross-platform development command planner."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import httpx
import pytest
from scripts import dev


@pytest.fixture(autouse=True)
def skip_real_port_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dev, "_host_port_is_available", lambda _port: True)
    monkeypatch.setattr(dev, "_validate_deployment_inputs", lambda: None)


@pytest.fixture
def captured_commands(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    commands: list[tuple[str, ...]] = []

    def capture(command: Sequence[str], *, environment: object = None) -> None:
        del environment
        commands.append(tuple(command))

    monkeypatch.setattr(dev, "_run", capture)
    monkeypatch.setattr(dev, "_psi_cache_years", lambda: ())
    monkeypatch.setattr(dev, "_psi_cache_weeks", lambda: ())
    monkeypatch.setattr(dev, "_write_openai_secret", lambda _value: dev.Path("secret"))
    monkeypatch.setattr(dev, "_remove_openai_secret", lambda: None)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    return commands


def test_up_fails_before_docker_when_openai_credential_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    commands: list[tuple[str, ...]] = []
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(dev, "_run", lambda command, **_kwargs: commands.append(tuple(command)))

    assert dev.main(["stack", "up"]) == 1
    assert commands == []
    assert "OPENAI_API_KEY is required" in capsys.readouterr().err


def test_explicit_env_file_loads_gemini_without_overriding_shell(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.gemini"
    env_file.write_text(
        "AI_MODE_LLM_PROVIDER=gemini\nGEMINI_API_KEY=file-key\n",
        encoding="utf-8",
    )
    original_provider = os.environ.get("AI_MODE_LLM_PROVIDER")
    original_key = os.environ.get("GEMINI_API_KEY")
    os.environ["AI_MODE_LLM_PROVIDER"] = "openai"
    os.environ.pop("GEMINI_API_KEY", None)
    try:
        dev._load_environment_file(env_file)

        assert os.environ["AI_MODE_LLM_PROVIDER"] == "openai"
        assert os.environ["GEMINI_API_KEY"] == "file-key"
    finally:
        if original_provider is None:
            os.environ.pop("AI_MODE_LLM_PROVIDER", None)
        else:
            os.environ["AI_MODE_LLM_PROVIDER"] = original_provider
        if original_key is None:
            os.environ.pop("GEMINI_API_KEY", None)
        else:
            os.environ["GEMINI_API_KEY"] = original_key


def test_gemini_up_materialises_only_file_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    environments: list[object] = []
    monkeypatch.setenv("AI_MODE_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        dev,
        "_run",
        lambda command, *, environment=None: environments.append(environment),
    )
    monkeypatch.setattr(dev, "_write_openai_secret", lambda _value: dev.Path("secret"))

    assert dev.main(["stack", "up"]) == 0

    environment = environments[-1]
    assert isinstance(environment, dict)
    assert "GEMINI_API_KEY" not in environment
    assert environment["GEMINI_API_KEY_FILE"] == "secret"


def test_up_starts_complete_stack(
    captured_commands: list[tuple[str, ...]],
) -> None:
    assert dev.main(["stack", "up"]) == 0

    assert captured_commands[0][:2] == ("docker", "info")
    assert captured_commands[1][-len(dev.APPLICATION_SERVICES) :] == dev.APPLICATION_SERVICES
    assert "--build" in captured_commands[1]
    for filename in dev.COMPOSE_FILES:
        assert filename in captured_commands[1]
    assert "shared-frontend" in captured_commands[1]
    assert "shared-ai-mode" in captured_commands[1]
    assert "f1-backend" in captured_commands[1]
    assert "docker-compose.shared-shell.yml" not in dev.COMPOSE_FILES


def test_up_preflights_before_materialising_secret_or_starting_compose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(dev, "_openai_credential", lambda **_kwargs: "key")
    monkeypatch.setattr(dev, "_ensure_docker", lambda: calls.append("docker"))
    monkeypatch.setattr(
        dev,
        "_preflight_compose_host_ports",
        lambda **_kwargs: calls.append("preflight"),
    )
    monkeypatch.setattr(
        dev,
        "_compose_environment",
        lambda **_kwargs: calls.append("secret") or {},
    )
    monkeypatch.setattr(dev, "_run", lambda *_args, **_kwargs: calls.append("compose"))

    dev._up(offline=False)

    assert calls[:4] == ["docker", "preflight", "secret", "compose"]


def test_rebuild_preflights_only_selected_host_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selections: list[tuple[str, ...]] = []
    monkeypatch.setattr(dev, "_openai_credential", lambda **_kwargs: "key")
    monkeypatch.setattr(dev, "_ensure_docker", lambda: None)
    monkeypatch.setattr(
        dev,
        "_preflight_compose_host_ports",
        lambda *, services: selections.append(tuple(services)),
    )
    monkeypatch.setattr(dev, "_compose_environment", lambda **_kwargs: {})
    monkeypatch.setattr(dev, "_run", lambda *_args, **_kwargs: None)

    dev._rebuild(("f1-frontend",), offline=False)

    assert selections == [("f1-frontend",)]


def test_port_configuration_rejects_invalid_and_self_conflicting_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROPERTYSCOPE_SHARED_PORT", "5301")
    monkeypatch.setenv("PROPERTYSCOPE_PORT", "5301")
    with pytest.raises(RuntimeError, match="configured for both"):
        dev._resolved_host_ports(dev.APPLICATION_SERVICES)

    monkeypatch.setenv("PROPERTYSCOPE_PORT", "not-a-port")
    with pytest.raises(RuntimeError, match="integer between 1 and 65535"):
        dev._resolved_host_ports(dev.APPLICATION_SERVICES)


def test_empty_port_environment_uses_compose_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROPERTYSCOPE_PORT", "")

    assert dev._resolved_host_ports(("f1-frontend",))["f1-frontend"] == (
        "PROPERTYSCOPE_PORT",
        5200,
    )


def test_port_preflight_allows_only_the_exact_selected_compose_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dev, "_host_port_is_available", lambda _port: False)
    monkeypatch.setattr(
        dev,
        "_published_port_owners",
        lambda _port: ((dev.DEFAULT_PROJECT_NAME, "f1-frontend"),),
    )

    dev._preflight_compose_host_ports(
        services=("f1-frontend",),
    )

    monkeypatch.setattr(
        dev,
        "_published_port_owners",
        lambda _port: ((dev.DEFAULT_PROJECT_NAME, "shared-frontend"),),
    )
    with pytest.raises(RuntimeError, match="service 'shared-frontend'"):
        dev._preflight_compose_host_ports(
            services=("f1-frontend",),
        )


def test_up_prints_configured_urls(
    captured_commands: list[tuple[str, ...]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del captured_commands
    monkeypatch.setenv("PROPERTYSCOPE_SHARED_PORT", "5310")
    monkeypatch.setenv("AI_MODE_PORT", "5311")
    monkeypatch.setenv("PROPERTYSCOPE_PORT", "5313")

    assert dev.main(["stack", "up"]) == 0

    output = capsys.readouterr().out
    assert "http://localhost:5310" in output
    assert "http://localhost:5311/health/ready" in output
    assert "http://localhost:5313" in output


def test_rebuild_defaults_to_all_application_services(
    captured_commands: list[tuple[str, ...]],
) -> None:
    assert dev.main(["stack", "rebuild"]) == 0

    build = captured_commands[1]
    recreate = captured_commands[2]
    assert build[-(len(dev.BUILD_SERVICES) + 1) :] == ("build", *dev.BUILD_SERVICES)
    assert "--force-recreate" in recreate
    assert recreate[-len(dev.BUILD_SERVICES) :] == dev.BUILD_SERVICES


def test_production_build_uses_only_the_release_compose_model(
    captured_commands: list[tuple[str, ...]],
) -> None:
    assert dev.main(["stack", "build", "shared-frontend", "f1-frontend"]) == 0

    assert captured_commands[0] == (
        "docker",
        "info",
        "--format",
        "Docker Engine {{.ServerVersion}} is ready",
    )
    assert captured_commands[1][:2] == ("docker", "compose")
    for filename in dev.PRODUCTION_COMPOSE_FILES:
        assert filename in captured_commands[1]
    assert captured_commands[1][-3:] == (
        "build",
        "shared-frontend",
        "f1-frontend",
    )
    assert dev.COMPOSE_FILES[-1] not in captured_commands[-1]


def test_cli_groups_stack_ui_and_data_workflows() -> None:
    parser = dev.build_parser()

    assert parser.parse_args(["stack", "status"]).group == "stack"
    assert parser.parse_args(["ui", "serve"]).group == "ui"
    assert parser.parse_args(["data", "collect", "fixture-property"]).group == "data"
    with pytest.raises(SystemExit):
        parser.parse_args(["up"])


def test_audit_command_forwards_filters_and_stable_shard_coordinates(
    captured_commands: list[tuple[str, ...]],
) -> None:
    assert (
        dev.main(
            [
                "ui",
                "audit",
                "full",
                "--port",
                "5342",
                "--workspace",
                "feature-1",
                "--viewport",
                "laptop-compact",
                "--scenario",
                "slow",
                "--shard-index",
                "1",
                "--shard-total",
                "4",
            ]
        )
        == 0
    )

    command = captured_commands[-1]
    assert command[:5] == (
        dev.sys.executable,
        "-m",
        "scripts.ui_audit",
        "full",
        "--port",
    )
    assert command[-10:] == (
        "--workspace",
        "feature-1",
        "--scenario",
        "slow",
        "--viewport",
        "laptop-compact",
        "--shard-index",
        "1",
        "--shard-total",
        "4",
    )


def test_down_preserves_named_volumes(captured_commands: list[tuple[str, ...]]) -> None:
    assert dev.main(["stack", "down"]) == 0

    command = captured_commands[-1]
    assert command[-2:] == ("down", "--remove-orphans")
    assert "--volumes" not in command


def test_ui_command_launches_fixture_server_as_repository_module(
    captured_commands: list[tuple[str, ...]],
) -> None:
    assert dev.main(["ui", "serve", "--port", "5332", "--scenario", "partial"]) == 0

    assert captured_commands == [
        (
            dev.sys.executable,
            "-m",
            "scripts.ui_fixture_server",
            "--port",
            "5332",
            "--scenario",
            "partial",
        )
    ]


def test_default_stack_connects_official_sources_without_a_second_project(
    captured_commands: list[tuple[str, ...]],
) -> None:
    assert dev.main(["stack", "up"]) == 0

    application_up = captured_commands[-1]
    assert all(filename in application_up for filename in dev.COMPOSE_FILES)
    assert "--project-name" not in application_up


def test_compose_project_uses_a_short_scannable_name() -> None:
    assert dev.DEFAULT_PROJECT_NAME == "ps-dev"


def test_default_stack_exposes_psi_and_advertises_cached_years(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environments: list[object] = []

    def capture(command: Sequence[str], *, environment: object = None) -> None:
        del command
        environments.append(environment)

    monkeypatch.setattr(dev, "_run", capture)
    monkeypatch.setattr(dev, "_psi_cache_years", lambda: (2024, 2025))
    monkeypatch.setattr(dev, "_psi_cache_weeks", lambda: ("2026-08-03", "2026-08-10"))
    monkeypatch.setattr(dev, "_write_openai_secret", lambda _value: dev.Path("secret"))
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    assert dev.main(["stack", "up"]) == 0

    assert all(
        isinstance(environment, dict)
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
    monkeypatch.setattr(dev, "_write_openai_secret", lambda _value: dev.Path("secret"))

    assert dev.main(["stack", "up", "--offline"]) == 0

    environment = environments[-1]
    assert isinstance(environment, dict)
    assert environment["AI_MODE_REQUIRE_PROVIDER_READY"] == "false"
    assert "OPENAI_API_KEY" not in environment


def test_reset_removes_only_selected_project_volumes(
    captured_commands: list[tuple[str, ...]],
) -> None:
    assert dev.main(["stack", "reset"]) == 0

    down, prune = captured_commands[-2:]
    assert down[-3:] == ("down", "--remove-orphans", "--volumes")
    assert prune == (
        "docker",
        "volume",
        "prune",
        "--all",
        "--force",
        "--filter",
        f"label=com.docker.compose.project={dev.DEFAULT_PROJECT_NAME}",
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


def test_removed_full_data_stack_flag_is_rejected() -> None:
    with pytest.raises(SystemExit):
        dev.main(["stack", "config", "--full-data"])


def test_collection_parser_does_not_offer_reduced_data_profiles() -> None:
    parser = dev.build_parser()

    parser.parse_args(["data", "collect", "schools-master"])
    with pytest.raises(SystemExit):
        parser.parse_args(["data", "collect", "schools-master", "--profile", "showcase"])


def test_collection_uses_the_registered_complete_scope_for_every_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jobs: list[str] = []
    monkeypatch.setattr(dev, "_collect", lambda **values: jobs.append(values["job_profile"]))

    assert dev.main(["data", "collect", "schools-master"]) == 0
    assert dev.main(["data", "collect", "fixture-property"]) == 0

    assert jobs == ["schools-master", "fixture-property"]


def test_collection_command_runs_registered_pipeline_to_candidate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    profile_directory = tmp_path / "job-profiles"
    profile_directory.mkdir()
    (profile_directory / "fixture-property.yaml").write_text(
        """key: fixture-property-full
scope: {profile: full-data, all_records: true}
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
            assert json.loads(request.content)["scope"] == {
                "profile": "full-data",
                "all_records": True,
            }
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
            wait=True,
            timeout_seconds=5,
            poll_seconds=0,
        )

    assert result["run"]["status"] == "succeeded"
    assert result["release"]["status"] == "candidate"


def test_collection_rejects_a_job_without_complete_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(dev, "JOB_PROFILE_DIRECTORY", tmp_path)
    (tmp_path / "fixture-property.yaml").write_text(
        "key: fixture-property-full\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="does not define"):
        dev._collection_definition("fixture-property")
