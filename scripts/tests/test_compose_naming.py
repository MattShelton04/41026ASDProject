"""Tests for ownership-oriented Compose project and resource names."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SERVICE_NAME = re.compile(r"^(?:shared|f[1-5])-[a-z0-9]+(?:-[a-z0-9]+)*$")


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


def test_enabled_build_services_have_a_live_development_source_policy() -> None:
    enabled = json.loads(
        (REPOSITORY_ROOT / "deployment/enabled-services.v1.json").read_text(encoding="utf-8")
    )
    expected = {"shared-frontend", "shared-ai-mode", *enabled["build_services"]}
    development = _compose("docker-compose.dev.yml")["services"]

    assert expected <= set(development)
    assert all(development[service].get("volumes") for service in expected)

    python_http_services = {
        service
        for service in expected
        if service == "shared-ai-mode" or service.endswith(("-backend", "-db-api"))
    }
    for service in python_http_services:
        assert "--reload" in development[service].get("command", [])

    frontend_services = {service for service in expected if service.endswith("-frontend")}
    for service in frontend_services:
        volumes = development[service]["volumes"]
        assert any("/usr/share/nginx/html" in mount for mount in volumes)


def test_source_scale_resource_defaults_fit_two_cpu_hosts() -> None:
    services = _compose("docker-compose.yml")["services"]

    assert services["f1-db-api"]["cpus"] == "${PROPERTYSCOPE_DATABASE_CPU_LIMIT:-2.0}"
    assert services["f1-db-loader"]["cpus"] == "${PROPERTYSCOPE_LOADER_CPU_LIMIT:-2.0}"
    assert services["f1-runner"]["cpus"] == "${PROPERTYSCOPE_RUNNER_CPU_LIMIT:-2.0}"


def test_fixture_stack_uses_an_explicit_small_import_budget() -> None:
    workflow = yaml.safe_load(
        (REPOSITORY_ROOT / ".github/workflows/student-1.yml").read_text(encoding="utf-8")
    )
    environment = workflow["jobs"]["containers"]["env"]

    assert environment["PROPERTYSCOPE_LOADER_TEMP_FILE_LIMIT_KIB"] == "65536"
    assert environment["PROPERTYSCOPE_LOADER_DISK_RESERVE_BYTES"] == "1073741824"
    commands = "\n".join(
        str(step.get("run", "")) for step in workflow["jobs"]["containers"]["steps"]
    )
    assert commands.count("--file deployment/enabled-features.compose.yml") == 5


def test_canonical_ci_validates_the_enabled_feature_projection() -> None:
    workflow = yaml.safe_load(
        (REPOSITORY_ROOT / ".github/workflows/integration-ci.yml").read_text(encoding="utf-8")
    )
    commands = "\n".join(str(step.get("run", "")) for step in workflow["jobs"]["quality"]["steps"])

    assert commands.count("--file deployment/enabled-features.compose.yml") == 2
