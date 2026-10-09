"""Tests for executable repository architecture boundaries."""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.validate_architecture import validate_repository


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        """
[tool.uv.workspace]
members = [
    "shared/contracts",
    "shared/consumer-protocol",
    "shared/testkit",
    "ai-services/agent-core",
    "ai-services/ai-mode",
    "student-1",
    "student-2",
]
""".strip()
        + "\n",
        encoding="utf-8",
    )
    projects = {
        "shared/contracts": ("shared-contracts", []),
        "shared/consumer-protocol": ("shared-consumer-protocol", ["shared-contracts"]),
        "shared/testkit": ("shared-testkit", ["agent-core", "shared-contracts"]),
        "ai-services/agent-core": ("agent-core", ["shared-contracts"]),
        "ai-services/ai-mode": ("ai-mode", ["agent-core", "shared-contracts"]),
        "student-1": (
            "student-1-feature",
            ["shared-contracts", "shared-consumer-protocol"],
        ),
        "student-2": ("student-2-feature", ["shared-contracts"]),
    }
    for member, (name, dependencies) in projects.items():
        path = root / member
        path.mkdir(parents=True)
        quoted = ", ".join(f'"{dependency}"' for dependency in dependencies)
        (path / "pyproject.toml").write_text(
            f'[project]\nname = "{name}"\nversion = "0.1.0"\ndependencies = [{quoted}]\n',
            encoding="utf-8",
        )
    (root / "student-1" / "feature.yaml").write_text(
        """
schema_version: 1
feature_key: student-1-example
display_name: Student 1 example
owner: student-1
frontend_base_path: /features/student-1/
backend_base_path: /api/student-1/v1
health_path: /health/ready
onboarding:
  databases:
    - database_service: f1-postgres
      volumes: [f1-postgres-data]
""".lstrip(),
        encoding="utf-8",
    )
    (root / "student-2" / "feature.yaml").write_text(
        """
schema_version: 1
feature_key: student-2-example
display_name: Student 2 example
owner: student-2
frontend_base_path: /features/student-2/
backend_base_path: /api/student-2/v1
health_path: /health/ready
""".lstrip(),
        encoding="utf-8",
    )
    deployment = root / "deployment" / "features.yaml"
    deployment.parent.mkdir()
    deployment.write_text(
        """
schema_version: 1
features:
  - feature_key: student-1-example
    enabled: true
  - feature_key: student-2-example
    enabled: false
""".lstrip(),
        encoding="utf-8",
    )
    return root


def test_valid_repository_boundaries_pass(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    source = root / "ai-services" / "ai-mode" / "src" / "ai_mode"
    source.mkdir(parents=True)
    (source / "__init__.py").write_text(
        "from agent_core import AgentRunner\nfrom shared_contracts import AgentRun\n",
        encoding="utf-8",
    )
    tests = root / "ai-services" / "ai-mode" / "tests"
    tests.mkdir()
    (tests / "test_integration.py").write_text(
        "from shared_testkit import ScriptedLLMProvider\n",
        encoding="utf-8",
    )

    assert validate_repository(root) == ()


def test_forbidden_production_import_is_source_located(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    source = root / "student-1" / "backend" / "service.py"
    source.parent.mkdir()
    source.write_text("from agent_core import AgentRunner\n", encoding="utf-8")

    violations = validate_repository(root)

    assert len(violations) == 1
    assert str(violations[0]) == (
        "student-1/backend/service.py:1: "
        "student-1-feature production code must not import agent_core"
    )


def test_cross_student_import_is_rejected_even_in_tests(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    owned_package = root / "student-2" / "backend" / "src" / "student_2_feature"
    owned_package.mkdir(parents=True)
    (owned_package / "__init__.py").write_text("", encoding="utf-8")
    test = root / "student-1" / "tests" / "test_feature.py"
    test.parent.mkdir()
    test.write_text("import student_2_feature\n", encoding="utf-8")

    violations = validate_repository(root)

    assert len(violations) == 1
    assert "owned by student-2" in violations[0].message


def test_shared_frontend_cannot_import_feature_implementation(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    source = root / "shared" / "frontend" / "app.js"
    source.parent.mkdir(parents=True)
    source.write_text(
        'import { projectRelease } from "../../student-1/frontend/releases.js";\n',
        encoding="utf-8",
    )

    violations = validate_repository(root)

    assert len(violations) == 1
    assert str(violations[0]) == (
        "shared/frontend/app.js:1: Shared frontend must not import feature-owned module "
        "../../student-1/frontend/releases.js"
    )


def test_shared_frontend_rejects_multiline_and_canonical_feature_imports(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    source = root / "shared" / "frontend" / "app.js"
    source.parent.mkdir(parents=True)
    source.write_text(
        'import {\n  privateThing,\n} from "../../student-1/frontend/private.js";\n'
        'import("/features/data-platform/private.js");\n',
        encoding="utf-8",
    )

    violations = validate_repository(root)

    assert len(violations) == 2
    assert all("feature-owned module" in item.message for item in violations)


def test_shared_html_module_script_cannot_enter_feature(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    source = root / "shared" / "frontend" / "index.html"
    source.parent.mkdir(parents=True)
    source.write_text(
        '<script defer src="/features/data-platform/private.js" type="module"></script>\n'
        '<script type="module">\nimport "../../student-1/frontend/also-private.js";\n</script>\n',
        encoding="utf-8",
    )

    violations = validate_repository(root)

    assert len(violations) == 2
    assert all("feature-owned module" in item.message for item in violations)


def test_network_module_urls_are_rejected_in_shared_and_features(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    shared = root / "shared" / "frontend" / "app.js"
    feature = root / "student-1" / "frontend" / "app.js"
    shared.parent.mkdir(parents=True)
    feature.parent.mkdir(parents=True)
    shared.write_text(
        'import "http://localhost:5100/features/data-platform/private.js";\n'
        'import "HTTP://localhost:5100/features/data-platform/case-private.js";\n'
        'import "//localhost/features/data-platform/also-private.js";\n',
        encoding="utf-8",
    )
    feature.write_text(
        'import "https://example.test/features/suburb-analytics/private.js";\n'
        'import "Https://example.test/features/suburb-analytics/case-private.js";\n',
        encoding="utf-8",
    )

    violations = validate_repository(root)

    assert len(violations) == 5
    assert all("reviewed same-origin paths" in item.message for item in violations)


def test_only_exact_feature_one_bridge_ingress_is_allowed(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    bridge = root / "shared" / "frontend" / "feature-1-bridge.js"
    bridge.parent.mkdir(parents=True)
    bridge.write_text(
        'import("/features/data-platform/integration/shell.js?v=2");\n',
        encoding="utf-8",
    )

    assert validate_repository(root) == ()

    bridge.write_text(
        'import("/features/data-platform/integration/private.js");\n', encoding="utf-8"
    )
    assert len(validate_repository(root)) == 1


def test_student_frontend_must_use_shared_public_entrypoints(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    source = root / "student-1" / "frontend" / "routes" / "properties.js"
    source.parent.mkdir(parents=True)
    source.write_text(
        'import { loadMapLibreRenderer } from "../mapping/renderer.js";\n',
        encoding="utf-8",
    )

    violations = validate_repository(root)

    assert len(violations) == 1
    assert "must import Shared mapping through mapping/index.js" in violations[0].message


def test_student_frontend_public_entrypoints_pass(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    source = root / "student-1" / "frontend" / "routes" / "properties.js"
    source.parent.mkdir(parents=True)
    source.write_text(
        'import { createMap } from "../mapping/index.js";\n'
        'import { el } from "../browser/index.js";\n',
        encoding="utf-8",
    )

    assert validate_repository(root) == ()


def test_student_local_mapping_module_is_not_mistaken_for_shared_copy(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    mapping = root / "student-1" / "frontend" / "mapping"
    mapping.mkdir(parents=True)
    (mapping / "local.js").write_text("export const local = true;\n", encoding="utf-8")
    (mapping / "screen.js").write_text('import { local } from "./local.js";\n', encoding="utf-8")

    assert validate_repository(root) == ()


def test_student_frontend_test_cannot_reach_past_shared_public_barrel(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    source = root / "student-1" / "tests" / "frontend" / "contract.test.mjs"
    source.parent.mkdir(parents=True)
    source.write_text(
        'readFile("../../../shared/frontend/mapping/renderer.js");\n',
        encoding="utf-8",
    )

    violations = validate_repository(root)

    assert len(violations) == 1
    assert "must import Shared mapping through mapping/index.js" in violations[0].message


def test_windows_file_read_cannot_reach_past_shared_public_barrel(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    source = root / "student-1" / "tests" / "frontend" / "contract.test.mjs"
    source.parent.mkdir(parents=True)
    source.write_text(
        'readFileSync("..\\\\..\\\\..\\\\shared\\\\frontend\\\\mapping\\\\renderer.js");\n',
        encoding="utf-8",
    )

    violations = validate_repository(root)

    assert len(violations) == 1
    assert "must import Shared mapping through mapping/index.js" in violations[0].message


def test_forbidden_workspace_dependency_is_rejected(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    manifest = root / "student-1" / "pyproject.toml"
    manifest.write_text(
        '[project]\nname = "student-1-feature"\nversion = "0.1.0"\n'
        'dependencies = ["shared-contracts", "agent-core>=0.1"]\n',
        encoding="utf-8",
    )

    violations = validate_repository(root)

    assert len(violations) == 1
    assert violations[0].line == 0
    assert "must not depend on workspace project agent-core" in violations[0].message


def test_feature_one_backend_cannot_import_postgres_or_database_package(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    source = root / "student-1" / "backend" / "src" / "propertyscope_data_platform" / "app.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "import psycopg\nfrom propertyscope_data_store import repository\n",
        encoding="utf-8",
    )

    violations = validate_repository(root)

    assert len(violations) == 2
    assert "Only an enabled feature's database/ code may import PostgreSQL client psycopg" in (
        violations[0].message
    )
    assert "must call its database service over HTTP" in violations[1].message


def test_feature_one_database_may_import_postgres_client(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    source = root / "student-1" / "database" / "src" / "propertyscope_data_store" / "app.py"
    source.parent.mkdir(parents=True)
    source.write_text("import psycopg\n", encoding="utf-8")

    assert validate_repository(root) == ()


def test_other_student_must_not_import_postgres_client(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    source = root / "student-2" / "database" / "repository.py"
    source.parent.mkdir()
    source.write_text("import psycopg\n", encoding="utf-8")

    violations = validate_repository(root)

    assert len(violations) == 1
    assert "Only an enabled feature's database/ code may import PostgreSQL client psycopg" in (
        violations[0].message
    )


def test_propertyscope_compose_trust_boundary_passes(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    (root / "docker-compose.yml").write_text(_valid_propertyscope_compose(), encoding="utf-8")

    assert validate_repository(root) == ()


def test_propertyscope_compose_rejects_credential_and_volume_leaks(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    compose = (
        _valid_propertyscope_compose()
        .replace(
            "f1-runner:\n    volumes:",
            "f1-runner:\n    environment:\n      PROPERTYSCOPE_DATABASE_URL: leaked\n    volumes:",
        )
        .replace(
            "f1-artifacts:/artifacts:rw",
            "f1-postgres-data:/postgres:rw",
        )
    )
    (root / "docker-compose.yml").write_text(compose, encoding="utf-8")

    messages = [violation.message for violation in validate_repository(root)]

    assert any("runner must not receive PROPERTYSCOPE_DATABASE_URL" in item for item in messages)
    assert any("runner must not mount PostgreSQL volume" in item for item in messages)
    assert any("runner must mount f1-artifacts read/write" in item for item in messages)


def test_enabled_database_volume_has_one_compose_owner(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    compose = _valid_propertyscope_compose().replace(
        "f1-db-api:\n    environment:",
        "f1-db-api:\n    volumes:\n      - f1-postgres-data:/leaked:ro\n    environment:",
    )
    (root / "docker-compose.yml").write_text(compose, encoding="utf-8")

    messages = [violation.message for violation in validate_repository(root)]

    assert any(
        message
        == "Compose service f1-db-api must not mount database volume f1-postgres-data owned by "
        "f1-postgres"
        for message in messages
    )


def test_enabled_database_owner_and_volume_must_exist_and_mount_rw(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    compose = (
        _valid_propertyscope_compose()
        .replace(
            "f1-postgres:\n    volumes:\n      - f1-postgres-data:/var/lib/postgresql/data",
            "f1-postgres:\n    volumes: []",
        )
        .replace("  f1-postgres-data:\n", "")
    )
    (root / "docker-compose.yml").write_text(compose, encoding="utf-8")

    messages = [violation.message for violation in validate_repository(root)]

    assert "Enabled feature student-1-example database volume f1-postgres-data is not declared" in (
        messages
    )
    assert "Database owner service f1-postgres must mount f1-postgres-data read/write" in messages


def test_enabled_feature_database_code_may_use_postgres_client(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    selection = root / "deployment" / "features.yaml"
    selection.write_text(
        """
schema_version: 1
features:
  - feature_key: student-2-example
    enabled: true
""".lstrip(),
        encoding="utf-8",
    )
    manifest = root / "student-2" / "feature.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8") + "onboarding:\n  databases:\n"
        "    - database_service: f2-postgres\n      volumes: [f2-postgres-data]\n",
        encoding="utf-8",
    )
    source = root / "student-2" / "database" / "repository.py"
    source.parent.mkdir()
    source.write_text("import psycopg\n", encoding="utf-8")

    assert validate_repository(root) == ()


def _valid_propertyscope_compose() -> str:
    return """\
services:
  f1-postgres:
    volumes:
      - f1-postgres-data:/var/lib/postgresql/data
  f1-db-api:
    environment:
      PROPERTYSCOPE_DATABASE_URL: postgresql://database
  f1-db-loader:
    environment:
      PROPERTYSCOPE_DATABASE_URL: postgresql://database
    volumes:
      - f1-artifacts:/artifacts:ro
  f1-backend: {}
  f1-runner:
    volumes:
      - f1-artifacts:/artifacts:rw
volumes:
  f1-postgres-data:
  f1-artifacts:
"""


def _declare_corpus(root: Path, *, path: str, corpus_id: str) -> None:
    manifest = root / "student-1" / "feature.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            "onboarding:\n",
            "onboarding:\n"
            "  ai:\n"
            "    tool_catalog: student-1/tool-catalog.yaml\n"
            "    runtime_path: /etc/ai-mode/student-1-tools.yaml\n"
            f"    rag_corpus: {path}\n"
            f"    rag_corpus_id: {corpus_id}\n",
            1,
        ),
        encoding="utf-8",
    )
    (root / "student-1" / "tool-catalog.yaml").write_text("tools: []\n", encoding="utf-8")


def _write_corpus(root: Path, path: str, payload: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(payload, encoding="utf-8")


def test_matching_corpus_declaration_passes(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    _declare_corpus(root, path="student-1/config/rag/corpus.json", corpus_id="operator-guidance")
    _write_corpus(
        root,
        "student-1/config/rag/corpus.json",
        '{"feature_key": "student-1-example", "corpus_id": "operator-guidance"}',
    )

    assert not [v for v in validate_repository(root) if "corpus" in v.message]


def test_missing_corpus_manifest_is_reported(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    _declare_corpus(root, path="student-1/config/rag/corpus.json", corpus_id="operator-guidance")

    assert any(
        "declares a missing corpus manifest" in violation.message
        for violation in validate_repository(root)
    )


def test_corpus_identity_must_match_the_declaration(tmp_path: Path) -> None:
    """An identity mismatch would otherwise surface as an opaque scope denial at ingest."""
    root = _workspace(tmp_path)
    _declare_corpus(root, path="student-1/config/rag/corpus.json", corpus_id="operator-guidance")
    _write_corpus(
        root,
        "student-1/config/rag/corpus.json",
        '{"feature_key": "student-2-example", "corpus_id": "other"}',
    )

    messages = [v.message for v in validate_repository(root)]
    assert any("feature_key" in message and "does not match" in message for message in messages)
    assert any("corpus_id" in message and "does not match" in message for message in messages)


def test_a_feature_cannot_declare_another_slices_corpus(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    _declare_corpus(root, path="student-2/config/rag/corpus.json", corpus_id="operator-guidance")
    _write_corpus(
        root,
        "student-2/config/rag/corpus.json",
        '{"feature_key": "student-1-example", "corpus_id": "operator-guidance"}',
    )

    assert any(
        "must own its corpus manifest" in violation.message
        for violation in validate_repository(root)
    )


_HOST_AI_BACKEND = """\
services:
  f1-backend:
    extra_hosts:
      - host.docker.internal:host-gateway
    environment:
      AI_MODE_BASE_URL: http://host.docker.internal:${AI_MODE_PORT:-5005}
      MCP_SERVER_URL: http://host.docker.internal:${MCP_PORT:-5011}/mcp
      RAG_SERVER_URL: http://host.docker.internal:${RAG_PORT:-5012}
      MULTI_AGENT_BASE_URL: http://host.docker.internal:${MULTI_AGENT_PORT:-5013}
      MULTI_AGENT_SERVICE_TOKEN: ${MULTI_AGENT_SERVICE_TOKEN:-}
"""


def _host_ai_messages(root: Path) -> list[str]:
    return [
        violation.message
        for violation in validate_repository(root)
        if "AI" in violation.message or "host" in violation.message
    ]


def test_backend_wired_to_host_ai_services_passes(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    (root / "docker-compose.yml").write_text(_HOST_AI_BACKEND, encoding="utf-8")

    assert _host_ai_messages(root) == []


def test_backend_that_calls_ai_mode_must_reach_mcp_and_rag_through_the_host(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    compose = (
        _HOST_AI_BACKEND.replace("      - host.docker.internal:host-gateway\n", "      - other\n")
        .replace("MCP_SERVER_URL: http://host.docker.internal", "MCP_SERVER_URL: http://mcp-server")
        .replace("      RAG_SERVER_URL: http://host.docker.internal:${RAG_PORT:-5012}\n", "")
    )
    (root / "docker-compose.yml").write_text(compose, encoding="utf-8")

    messages = _host_ai_messages(root)

    assert any("must set MCP_SERVER_URL" in message for message in messages)
    assert any("must set RAG_SERVER_URL" in message for message in messages)
    assert any("must map host.docker.internal:host-gateway" in message for message in messages)


@pytest.mark.parametrize(
    ("filename", "service"),
    [
        ("docker-compose.ai.yml", "shared-ai-mode:\n    image: example/app"),
        (
            "docker-compose.override.yml",
            "helper:\n    build:\n      context: ai-services/rag-server",
        ),
        ("compose.yaml", "helper:\n    image: example/mcp-server:dev"),
        ("deployment/extra.compose.yml", "helper:\n    command: [python, -m, ai_mode]"),
        ("docker-compose.ai.yml", "multi-agent:\n    image: example/app"),
        ("compose.yaml", "helper:\n    command: [multi-agent-server, serve]"),
        (
            "docker-compose.override.yml",
            "helper:\n    build:\n      context: ai-services/multi-agent-server",
        ),
    ],
)
def test_any_compose_file_defining_a_shared_ai_service_is_rejected(
    tmp_path: Path, filename: str, service: str
) -> None:
    root = _workspace(tmp_path)
    (root / filename).write_text(f"services:\n  {service}\n", encoding="utf-8")

    messages = _host_ai_messages(root)

    assert len(messages) == 1
    assert "must run as host processes" in messages[0]


def test_ai_service_dockerfile_is_rejected(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    dockerfile = root / "ai-services" / "ai-mode" / "Dockerfile"
    dockerfile.parent.mkdir(parents=True, exist_ok=True)
    dockerfile.write_text("FROM python:3.12\n", encoding="utf-8")

    violations = validate_repository(root)

    assert [str(violation) for violation in violations] == [
        "ai-services/ai-mode/Dockerfile: Shared AI services must not be built as images"
    ]


_AZURE_BASELINE = """
services:
  shared-edge-proxy:
    image: ${ACR_LOGIN_SERVER}/propertyscope/mirror/caddy:2
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./deployment/azure/Caddyfile:/etc/caddy/Caddyfile:ro
  f1-backend:
    build: !reset null
    ports: !reset []
    extra_hosts: !reset []
    environment:
      AI_MODE_BASE_URL: http://127.0.0.1:9
    networks: !override [f1-data]
"""

_AZURE_AI_OVERLAY = """
services:
  f1-backend:
    extra_hosts:
      - host.docker.internal:host-gateway
    environment:
      AI_MODE_BASE_URL: http://host.docker.internal:5005
  f1-frontend:
    ports:
      - 127.0.0.1:5200:8080
"""


def _azure_messages(root: Path) -> list[str]:
    return [
        violation.message
        for violation in validate_repository(root)
        if "Azure" in violation.message or "Compose" in violation.message
    ]


def test_azure_overrides_with_compose_merge_tags_pass(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    (root / "docker-compose.azure.yml").write_text(_AZURE_BASELINE, encoding="utf-8")
    (root / "docker-compose.azure-ai.yml").write_text(_AZURE_AI_OVERLAY, encoding="utf-8")

    assert _azure_messages(root) == []


def test_azure_baseline_rejects_public_ports_source_mounts_and_host_ai(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    compose = _AZURE_BASELINE + (
        "  f2-backend:\n"
        "    ports: ['5300:8080']\n"
        "    volumes: ['./student-2:/app']\n"
        "    extra_hosts: [host.docker.internal:host-gateway]\n"
        "    environment:\n"
        "      AI_MODE_BASE_URL: http://host.docker.internal:5005\n"
    )
    (root / "docker-compose.azure.yml").write_text(compose, encoding="utf-8")

    messages = _azure_messages(root)

    assert any("f2-backend must not publish a host port" in message for message in messages)
    assert any("must not bind-mount ./student-2" in message for message in messages)
    assert any("must not reach the host AI tier" in message for message in messages)


def test_azure_ai_overlay_must_use_the_host_gateway_and_loopback_ports(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    overlay = _AZURE_AI_OVERLAY.replace("host.docker.internal:5005", "ai-mode:5005").replace(
        "127.0.0.1:5200:8080", "5200:8080"
    )
    (root / "docker-compose.azure-ai.yml").write_text(overlay, encoding="utf-8")

    messages = _azure_messages(root)

    assert any("must reach host AI-mode via host.docker.internal" in m for m in messages)
    assert any("f1-frontend must not publish a host port" in m for m in messages)


def test_multi_agent_connection_uses_the_host_gateway_and_no_literal_token(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    compose = _HOST_AI_BACKEND.replace(
        "MULTI_AGENT_BASE_URL: http://host.docker.internal", "MULTI_AGENT_BASE_URL: http://agents"
    ).replace("${MULTI_AGENT_SERVICE_TOKEN:-}", "literal-token-value-0123456789abcdefghij")
    compose += """\
  f2-backend:
    environment:
      MULTI_AGENT_BASE_URL: http://host.docker.internal:5013
      MULTI_AGENT_SERVICE_TOKEN: ${MULTI_AGENT_SERVICE_TOKEN:-}
"""
    (root / "docker-compose.yml").write_text(compose, encoding="utf-8")

    messages = _host_ai_messages(root)

    assert sorted(messages) == [
        "Compose service f1-backend must pass MULTI_AGENT_SERVICE_TOKEN through from the host "
        "environment (${MULTI_AGENT_SERVICE_TOKEN:-}), never as a literal",
        "Compose service f1-backend must reach the host Multi-Agent Server via "
        "http://host.docker.internal",
        "Compose service f2-backend must map host.docker.internal:host-gateway",
    ]


def test_students_must_not_import_the_multi_agent_server_even_in_tests(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    test = root / "student-1" / "tests" / "test_review.py"
    test.parent.mkdir()
    test.write_text(
        "from multi_agent_server import create_app\n"
        "from shared_testkit import FakeMultiAgentServer\n",
        encoding="utf-8",
    )

    violations = validate_repository(root)

    assert [str(violation) for violation in violations] == [
        "student-1/tests/test_review.py:1: student-1-feature must not import multi_agent_server; "
        "call the Multi-Agent Server over HTTP and test with shared_testkit.FakeMultiAgentServer"
    ]


def test_multi_agent_server_dependencies_and_imports(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    pyproject = root / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace(
            '"student-2",\n', '"student-2",\n    "ai-services/multi-agent-server",\n'
        ),
        encoding="utf-8",
    )
    project = root / "ai-services" / "multi-agent-server"
    source = project / "src" / "multi_agent_server"
    source.mkdir(parents=True)
    (project / "pyproject.toml").write_text(
        '[project]\nname = "multi-agent-server"\nversion = "0.1.0"\n'
        'dependencies = ["shared-contracts", "agent-core", "ai-mode", "shared-testkit"]\n',
        encoding="utf-8",
    )
    (source / "__init__.py").write_text(
        "from ai_mode import providers\nfrom shared_testkit import FakeMultiAgentServer\n",
        encoding="utf-8",
    )
    (project / "tests").mkdir()
    (project / "tests" / "test_app.py").write_text(
        "from shared_testkit import ScriptedLLMProvider\n", encoding="utf-8"
    )
    agent_core = root / "ai-services" / "agent-core" / "src" / "agent_core"
    agent_core.mkdir(parents=True)
    (agent_core / "__init__.py").write_text("import multi_agent_server\n", encoding="utf-8")

    messages = sorted(violation.message for violation in validate_repository(root))

    assert messages == [
        "agent-core production code must not import multi_agent_server",
        "multi-agent-server must not depend on workspace project shared-testkit",
        "multi-agent-server production code must not import shared_testkit",
    ]


_WORKFLOW = """\
id: example-review
version: v1
feature_id: {feature}
title: Example review
objective: Check a record.
planner_guidance: Read the record.
allowed_tools: [example.record.v1]
steps:
  - id: record
    title: Read record
    purpose: Fetch it
    tool: example.record.v1
reviewer_checks:
  - id: record-found
    description: The record exists
    severity: critical
    recommendation: Reject
    rule: {{kind: step_succeeded, step: record}}
"""


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (_WORKFLOW.format(feature="student-1-example"), None),
        (
            _WORKFLOW.format(feature="student-2-example"),
            "workflow manifest feature_id student-2-example must be student-1-example",
        ),
        ("id: [unclosed", "invalid workflow manifest"),
        ("id: Bad Id\n", "invalid workflow manifest"),
    ],
)
def test_enabled_feature_workflow_manifests_are_validated(
    tmp_path: Path, content: str, expected: str | None
) -> None:
    root = _workspace(tmp_path)
    manifest = root / "student-1" / "config" / "multi-agent" / "workflow.yaml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(content, encoding="utf-8")
    # A disabled feature's manifest is not part of the deployment and is not inspected.
    disabled = root / "student-2" / "config" / "multi-agent" / "workflow.yaml"
    disabled.parent.mkdir(parents=True)
    disabled.write_text("not: [valid", encoding="utf-8")

    messages = [
        str(violation) for violation in validate_repository(root) if "workflow" in violation.message
    ]

    if expected is None:
        assert messages == []
    else:
        assert len(messages) == 1
        assert messages[0].startswith("student-1/config/multi-agent/workflow.yaml: ")
        assert expected in messages[0]
