"""Tests for ownership-oriented Compose project and resource names."""

from __future__ import annotations

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
    assert _compose("docker-compose.full-data.yml")["name"] == "ps-full"


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
    for filename in ("docker-compose.dev.yml", "docker-compose.full-data.yml"):
        assert set(_compose(filename)["services"]) <= base_services

    assert set(base["networks"]) == {"shared-platform"}
    assert all(SERVICE_NAME.fullmatch(name) for name in base["volumes"])
