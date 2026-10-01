"""Feature 3 enablement, host-port and exclusive persistence regression checks."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_suburb_frontend_is_enabled_on_a_unique_host_port() -> None:
    projection = json.loads((ROOT / "deployment/enabled-features.v1.json").read_text("utf-8"))
    frontends = [feature["frontend"] for feature in projection["features"]]
    suburb = next(item for item in frontends if item["service"] == "f3-frontend")
    assert suburb["host_port_default"] == 5600
    assert suburb["host_port_variable"] == "PROPERTYSCOPE_SUBURB_ANALYTICS_PORT"
    ports = [item["host_port_default"] for item in frontends]
    assert len(ports) == len(set(ports))
    overlay = yaml.safe_load((ROOT / "deployment/enabled-features.compose.yml").read_text("utf-8"))
    services = overlay["services"]
    assert services["f3-frontend"]["ports"] == [
        "127.0.0.1:${PROPERTYSCOPE_SUBURB_ANALYTICS_PORT:-5600}:8080"
    ]
    for name in ("f3-frontend", "f3-backend", "f3-database"):
        assert services[name]["profiles"] == ["release-0"]
    assert "shared-ai-mode" not in services
    feature = next(
        item for item in projection["features"] if item["frontend"]["service"] == "f3-frontend"
    )
    assert feature["ai"]["tool_catalog"] == "student-3/tool-catalog.yaml"
    assert feature["ai"]["rag_corpus"] == "student-3/config/rag/corpus.json"
    assert feature["ai"]["rag_corpus_id"] == "suburb-analytics-guidance"
    assert feature["ai"]["rag_evidence_kinds"] == [
        "project_guidance",
        "fixture",
        "official",
    ]


def test_suburb_services_use_http_and_exclusively_owned_storage() -> None:
    base = yaml.safe_load((ROOT / "docker-compose.yml").read_text("utf-8"))["services"]
    assert base["f3-backend"]["environment"] == {
        "SUBURB_STORE_URL": "http://f3-database:5302",
        "SUBURB_IMPORT_WORKER": "1",
        "AI_MODE_URL": "http://host.docker.internal:${AI_MODE_PORT:-5005}",
        "AI_MODE_SERVICE_TOKEN": "${AI_MODE_SERVICE_TOKEN:-}",
        "MCP_SERVER_URL": "http://host.docker.internal:${MCP_PORT:-5011}/mcp",
        "RAG_SERVER_URL": "http://host.docker.internal:${RAG_PORT:-5012}",
        "PROPERTY_DATA_URL": "http://f1-backend:5201",
    }
    assert "host.docker.internal:host-gateway" in base["f3-backend"]["extra_hosts"]
    owners = [
        name
        for name, service in base.items()
        if any(mount.startswith("f3-suburb-data:") for mount in service.get("volumes", []))
    ]
    assert owners == ["f3-database"]
    for name in ("f3-backend", "f3-database"):
        assert not base[name].get("ports")
    dev = yaml.safe_load((ROOT / "docker-compose.dev.yml").read_text("utf-8"))["services"]
    for name in ("f3-backend", "f3-database"):
        assert "--reload" in dev[name]["command"]
    frontend_mounts = dev["f3-frontend"]["volumes"]
    assert "./student-3/frontend:/usr/share/nginx/html:ro" not in frontend_mounts
    for filename in ("index.html", "app.js", "styles.css"):
        assert (
            f"./student-3/frontend/{filename}:/usr/share/nginx/html/{filename}:ro"
            in frontend_mounts
        )
    dockerfile = (ROOT / "student-3/Dockerfile").read_text("utf-8")
    assert 'CMD ["gunicorn"' in dockerfile


def test_shared_routes_assets_and_standalone_port_match_enablement() -> None:
    routes = (ROOT / "shared/frontend/generated/enabled-feature-routes.conf").read_text("utf-8")
    assert "location ^~ /features/suburb-analytics/" in routes
    assert "location ^~ /api/suburb-analytics/v1/" in routes
    assert "location = /api/shared-health/suburb-analytics" in routes
    fragment = (ROOT / "shared/frontend/fragments/research-areas.html").read_text("utf-8")
    assert fragment.count('data-feature-id="suburb-context"') == 1
    assert 'href="/features/suburb-analytics/#suburbs"' in fragment
    server = (ROOT / "student-3/frontend/dev_server.py").read_text("utf-8")
    assert 'os.getenv("PORT", "5600")' in server
    assert 'os.getenv("PORT", "5300")' not in server
