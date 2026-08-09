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
