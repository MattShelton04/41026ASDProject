"""Tests for executable repository architecture boundaries."""

from __future__ import annotations

from pathlib import Path

from scripts.validate_architecture import validate_repository


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        """
[tool.uv.workspace]
members = [
    "shared/contracts",
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
        "shared/testkit": ("shared-testkit", ["agent-core", "shared-contracts"]),
        "ai-services/agent-core": ("agent-core", ["shared-contracts"]),
        "ai-services/ai-mode": ("ai-mode", ["agent-core", "shared-contracts"]),
        "student-1": ("student-1-feature", ["shared-contracts"]),
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
    assert "Only Feature 1 database/ may import PostgreSQL client psycopg" in violations[0].message
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
    assert "Only Feature 1 database/ may import PostgreSQL client psycopg" in violations[0].message


def test_propertyscope_compose_trust_boundary_passes(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    (root / "docker-compose.yml").write_text(_valid_propertyscope_compose(), encoding="utf-8")

    assert validate_repository(root) == ()


def test_propertyscope_compose_rejects_credential_and_volume_leaks(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    compose = (
        _valid_propertyscope_compose()
        .replace(
            "propertyscope-runner:\n    volumes:",
            "propertyscope-runner:\n    environment:\n"
            "      PROPERTYSCOPE_DATABASE_URL: leaked\n    volumes:",
        )
        .replace(
            "propertyscope_artifacts:/artifacts:rw",
            "propertyscope_postgres_data:/postgres:rw",
        )
    )
    (root / "docker-compose.yml").write_text(compose, encoding="utf-8")

    messages = [violation.message for violation in validate_repository(root)]

    assert any("runner must not receive PROPERTYSCOPE_DATABASE_URL" in item for item in messages)
    assert any("runner must not mount PostgreSQL volume" in item for item in messages)
    assert any("runner must mount propertyscope_artifacts read/write" in item for item in messages)


def test_propertyscope_compose_requires_full_data_profile(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    compose = _valid_propertyscope_compose().replace(
        "propertyscope-runner:\n    volumes:",
        "propertyscope-runner:\n    environment:\n"
        "      PROPERTYSCOPE_FULL_DATA_ENABLED: 'true'\n    volumes:",
    )
    (root / "docker-compose.yml").write_text(compose, encoding="utf-8")

    violations = validate_repository(root)

    assert any(
        "enables full data without the full-data profile" in item.message for item in violations
    )


def test_propertyscope_full_data_overlay_requires_profile(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    (root / "docker-compose.yml").write_text(_valid_propertyscope_compose(), encoding="utf-8")
    (root / "docker-compose.full-data.yml").write_text(
        "services:\n"
        "  propertyscope-runner:\n"
        "    environment:\n"
        "      PROPERTYSCOPE_FULL_DATA_ENABLED: 'true'\n",
        encoding="utf-8",
    )

    violations = validate_repository(root)

    assert any(
        violation.path == "docker-compose.full-data.yml"
        and "without the full-data profile" in violation.message
        for violation in violations
    )


def _valid_propertyscope_compose() -> str:
    return """\
services:
  propertyscope-postgres:
    volumes:
      - propertyscope_postgres_data:/var/lib/postgresql/data
  propertyscope-database-api:
    environment:
      PROPERTYSCOPE_DATABASE_URL: postgresql://database
  propertyscope-database-loader:
    environment:
      PROPERTYSCOPE_DATABASE_URL: postgresql://database
    volumes:
      - propertyscope_artifacts:/artifacts:ro
  propertyscope-backend: {}
  propertyscope-runner:
    volumes:
      - propertyscope_artifacts:/artifacts:rw
volumes:
  propertyscope_postgres_data:
  propertyscope_artifacts:
"""
