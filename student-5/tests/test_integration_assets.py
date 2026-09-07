"""Static integration contracts for the Student 5 Release 0 deployment."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_dockerfile_exposes_three_non_root_targets() -> None:
    dockerfile = (ROOT / "student-5" / "Dockerfile").read_text(encoding="utf-8")
    for target in ("database-api", "backend", "frontend"):
        assert f" AS {target}" in dockerfile
    assert "USER propertyscope" in dockerfile
    assert "nginxinc/nginx-unprivileged:1.29.1-alpine3.22-slim" in dockerfile
    assert "ARG UV_VERSION=0.12.1" in dockerfile
    assert "FROM ghcr.io/astral-sh/uv:${UV_VERSION}" in dockerfile
    assert "ARG PYTHON_VERSION=3.12.13" in dockerfile
    assert "FROM python:${PYTHON_VERSION}-slim-bookworm" in dockerfile


def test_compose_keeps_sqlite_volume_at_database_boundary() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    expected = {"f5-db-api", "f5-backend", "f5-frontend"}
    assert expected.issubset(services)
    assert services["f5-db-api"]["volumes"] == ["f5-sqlite-data:/var/lib/propertyscope-buyer"]
    assert "volumes" not in services["f5-backend"]
    assert "volumes" not in services["f5-frontend"]
    assert services["f5-backend"]["environment"]["PROPERTYSCOPE_BUYER_DATABASE_API_URL"] == (
        "http://f5-db-api:5502"
    )


def test_nginx_exposes_only_public_buyer_routes_and_shared_assets() -> None:
    nginx = (ROOT / "student-5" / "frontend" / "nginx.conf").read_text(encoding="utf-8")
    dockerfile = (ROOT / "student-5" / "Dockerfile").read_text(encoding="utf-8")
    assert "location /api/buyer-workspaces/" in nginx
    assert "http://f5-backend:5501" in nginx
    assert "X-Request-ID" in nginx
    assert "/internal/buyer-workspaces" not in nginx
    assert "shared/frontend/design-system" in dockerfile


def test_generated_projection_enables_student_five_and_registers_host_catalogue() -> None:
    projection = yaml.safe_load(
        (ROOT / "deployment" / "enabled-features.compose.yml").read_text(encoding="utf-8")
    )
    services = projection["services"]
    for service in ("f5-db-api", "f5-backend", "f5-frontend"):
        assert services[service]["profiles"] == ["release-0"]
    assert "shared-ai-mode" not in services
    runtime = json.loads((ROOT / "deployment/enabled-features.v1.json").read_text("utf-8"))
    feature = next(
        item for item in runtime["features"] if item["frontend"]["service"] == "f5-frontend"
    )
    assert feature["ai"]["tool_catalog"] == "student-5/tool-catalog.yaml"
    base = yaml.safe_load((ROOT / "docker-compose.yml").read_text("utf-8"))["services"]
    assert (
        base["f5-backend"]["environment"]["AI_MODE_BASE_URL"]
        == "http://host.docker.internal:${AI_MODE_PORT:-5005}"
    )
    assert "host.docker.internal:host-gateway" in base["f5-backend"]["extra_hosts"]
