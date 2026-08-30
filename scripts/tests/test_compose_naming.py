"""Tests for ownership-oriented Compose project and resource names."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SERVICE_NAME = re.compile(r"^(?:shared|f[1-5]|poc-f6)-[a-z0-9]+(?:-[a-z0-9]+)*$")


def _compose(filename: str) -> dict[str, Any]:
    document = yaml.safe_load((REPOSITORY_ROOT / filename).read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def test_compose_projects_have_short_purpose_specific_names() -> None:
    assert _compose("docker-compose.yml")["name"] == "ps"
    assert _compose("docker-compose.dev.yml")["name"] == "ps-dev"


def test_services_use_ownership_prefixes_and_compose_generated_container_names() -> None:
    base = _compose("docker-compose.yml")
    services = base["services"]

    assert all(SERVICE_NAME.fullmatch(name) for name in services)
    assert all("container_name" not in service for service in services.values())
    for name, service in services.items():
        if "build" in service:
            assert service["image"].startswith(f"propertyscope/{name}:")


def test_overlays_and_resources_reuse_the_same_ownership_vocabulary() -> None:
    base = _compose("docker-compose.yml")
    base_services = set(base["services"])
    for filename in ("docker-compose.dev.yml",):
        assert set(_compose(filename)["services"]) <= base_services

    assert set(base["networks"]) == {"shared-platform"}
    assert all(SERVICE_NAME.fullmatch(name) for name in base["volumes"])


def test_source_scale_resource_defaults_fit_two_cpu_hosts() -> None:
    services = _compose("docker-compose.yml")["services"]

    assert services["f1-db-api"]["cpus"] == "${PROPERTYSCOPE_DATABASE_CPU_LIMIT:-2.0}"
    assert services["f1-db-loader"]["cpus"] == "${PROPERTYSCOPE_LOADER_CPU_LIMIT:-2.0}"
    assert services["f1-runner"]["cpus"] == "${PROPERTYSCOPE_RUNNER_CPU_LIMIT:-2.0}"


def test_local_integration_poc_is_opt_in_and_keeps_database_ownership_exclusive() -> None:
    compose = _compose("docker-compose.yml")
    services = compose["services"]
    poc_names = {"poc-f6-db-api", "poc-f6-backend", "poc-f6-frontend"}

    assert poc_names <= services.keys()
    assert all(services[name]["profiles"] == ["feature-6-poc"] for name in poc_names)
    assert services["poc-f6-db-api"]["volumes"] == ["poc-f6-data:/var/lib/propertyscope-poc"]
    assert "volumes" not in services["poc-f6-backend"]
    assert "volumes" not in services["poc-f6-frontend"]
    assert services["poc-f6-backend"]["environment"]["PROPERTYSCOPE_F1_ORIGIN"] == (
        "http://f1-backend:5201"
    )
    assert services["f1-backend"]["environment"]["PROPERTYSCOPE_FEATURE_2_URL"] == (
        "http://poc-f6-backend:5601"
    )
    assert services["f1-backend"]["environment"]["PROPERTYSCOPE_FEATURE_3_URL"] == (
        "http://poc-f6-backend:5601"
    )
    assert "poc-f6-data" in compose["volumes"]
    for service in services.values():
        mounts = service.get("volumes", [])
        if service is not services["poc-f6-db-api"]:
            assert not any(str(item).startswith("poc-f6-data:") for item in mounts)


def test_local_integration_poc_uses_explicit_build_targets_and_host_port() -> None:
    services = _compose("docker-compose.yml")["services"]

    for suffix, target in (
        ("db-api", "database-api"),
        ("backend", "backend"),
        ("frontend", "frontend"),
    ):
        service = services[f"poc-f6-{suffix}"]
        assert service["build"] == {
            "context": ".",
            "dockerfile": "poc/feature-6/Dockerfile",
            "target": target,
        }
    assert services["poc-f6-frontend"]["ports"] == ["127.0.0.1:${POC_F6_PORT:-5600}:8080"]


def test_ai_mode_composes_feature_one_and_poc_tool_catalogues() -> None:
    services = _compose("docker-compose.yml")["services"]
    ai_mode = services["shared-ai-mode"]

    assert ai_mode["environment"]["AI_MODE_TOOL_CATALOG_PATHS"] == (
        "/etc/ai-mode/propertyscope-tools.yaml,/etc/ai-mode/integration-poc-tools.yaml"
    )
    assert (
        "./poc/feature-6/tool-catalog.yaml:/etc/ai-mode/integration-poc-tools.yaml:ro"
        in ai_mode["volumes"]
    )
    command = _compose("docker-compose.dev.yml")["services"]["shared-ai-mode"]["command"]
    assert "--reload-extra-file=/etc/ai-mode/integration-poc-tools.yaml" in command
