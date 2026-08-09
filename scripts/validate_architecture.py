"""Validate the repository's documented Python dependency boundaries."""

from __future__ import annotations

import argparse
import ast
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

SHARED_CONTRACTS = "shared-contracts"
SHARED_TESTKIT = "shared-testkit"
AGENT_CORE = "agent-core"
AI_MODE = "ai-mode"
INTEGRATION_FIXTURE = "integration-test-feature"

ALLOWED_WORKSPACE_DEPENDENCIES: Mapping[str, frozenset[str]] = {
    SHARED_CONTRACTS: frozenset(),
    SHARED_TESTKIT: frozenset({SHARED_CONTRACTS, AGENT_CORE}),
    AGENT_CORE: frozenset({SHARED_CONTRACTS}),
    AI_MODE: frozenset({SHARED_CONTRACTS, AGENT_CORE}),
    INTEGRATION_FIXTURE: frozenset({SHARED_CONTRACTS}),
}

PRODUCTION_IMPORT_DENYLISTS: Mapping[str, frozenset[str]] = {
    SHARED_CONTRACTS: frozenset(
        {"shared_testkit", "agent_core", "ai_mode", "integration_test_feature"}
    ),
    SHARED_TESTKIT: frozenset({"ai_mode", "integration_test_feature"}),
    AGENT_CORE: frozenset({"shared_testkit", "ai_mode", "integration_test_feature"}),
    AI_MODE: frozenset({"shared_testkit", "integration_test_feature"}),
    INTEGRATION_FIXTURE: frozenset({"shared_testkit", "agent_core", "ai_mode"}),
}


@dataclass(frozen=True, slots=True, order=True)
class ArchitectureViolation:
    """One deterministic, source-located architecture violation."""

    path: str
    line: int
    message: str

    def __str__(self) -> str:
        location = f"{self.path}:{self.line}" if self.line else self.path
        return f"{location}: {self.message}"


@dataclass(frozen=True, slots=True)
class WorkspaceProject:
    """Workspace project metadata needed for dependency validation."""

    name: str
    path: Path
    import_names: frozenset[str]
    student_owner: str | None


def validate_repository(root: Path = REPOSITORY_ROOT) -> tuple[ArchitectureViolation, ...]:
    """Return every dependency/import boundary violation in stable order."""
    projects = _load_workspace_projects(root)
    violations = [
        *_validate_declared_dependencies(root, projects),
        *_validate_python_imports(root, projects),
    ]
    return tuple(sorted(violations))


def _load_workspace_projects(root: Path) -> tuple[WorkspaceProject, ...]:
    workspace = _read_toml(root / "pyproject.toml")
    members = workspace.get("tool", {}).get("uv", {}).get("workspace", {}).get("members", [])
    if not isinstance(members, list) or not all(isinstance(member, str) for member in members):
        raise ValueError("root pyproject.toml must define string uv workspace members")

    projects: list[WorkspaceProject] = []
    for member in members:
        project_path = root / member
        manifest = _read_toml(project_path / "pyproject.toml")
        name = manifest.get("project", {}).get("name")
        if not isinstance(name, str) or not name:
            raise ValueError(f"workspace member {member} has no project name")
        owner = member if member.startswith("student-") else None
        import_names = {_distribution_import_name(name)}
        import_names.update(_discover_import_names(project_path))
        projects.append(
            WorkspaceProject(
                name=_normalize_distribution_name(name),
                path=project_path,
                import_names=frozenset(import_names),
                student_owner=owner,
            )
        )
    return tuple(projects)


def _validate_declared_dependencies(
    root: Path,
    projects: tuple[WorkspaceProject, ...],
) -> Iterable[ArchitectureViolation]:
    workspace_names = {project.name for project in projects}
    for project in projects:
        manifest_path = project.path / "pyproject.toml"
        manifest = _read_toml(manifest_path)
        dependencies = manifest.get("project", {}).get("dependencies", [])
        if not isinstance(dependencies, list):
            yield ArchitectureViolation(
                _relative(root, manifest_path),
                0,
                "project.dependencies must be an array",
            )
            continue
        allowed = _allowed_workspace_dependencies(project, projects)
        for dependency in dependencies:
            if not isinstance(dependency, str):
                yield ArchitectureViolation(
                    _relative(root, manifest_path),
                    0,
                    "project dependency entries must be strings",
                )
                continue
            dependency_name = _dependency_distribution_name(dependency)
            if dependency_name in workspace_names and dependency_name not in allowed:
                yield ArchitectureViolation(
                    _relative(root, manifest_path),
                    0,
                    f"{project.name} must not depend on workspace project {dependency_name}",
                )


def _validate_python_imports(
    root: Path,
    projects: tuple[WorkspaceProject, ...],
) -> Iterable[ArchitectureViolation]:
    student_import_owners = {
        import_name: project.student_owner
        for project in projects
        if project.student_owner is not None
        for import_name in project.import_names
    }
    for project in projects:
        denied = _production_import_denylist(project)
        for path in sorted(project.path.rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (OSError, SyntaxError) as exc:
                yield ArchitectureViolation(
                    _relative(root, path),
                    getattr(exc, "lineno", 0) or 0,
                    f"could not inspect Python imports: {exc}",
                )
                continue
            is_test = _is_test_path(project.path, path)
            for module, line in _imports(tree):
                top_level = module.partition(".")[0]
                imported_student = student_import_owners.get(top_level)
                if imported_student is not None and imported_student != project.student_owner:
                    yield ArchitectureViolation(
                        _relative(root, path),
                        line,
                        f"{project.name} must not import {module} owned by {imported_student}",
                    )
                elif not is_test and top_level in denied:
                    yield ArchitectureViolation(
                        _relative(root, path),
                        line,
                        f"{project.name} production code must not import {module}",
                    )


def _allowed_workspace_dependencies(
    project: WorkspaceProject,
    projects: tuple[WorkspaceProject, ...],
) -> frozenset[str]:
    if project.student_owner is not None:
        return frozenset({SHARED_CONTRACTS})
    return ALLOWED_WORKSPACE_DEPENDENCIES.get(project.name, frozenset())


def _production_import_denylist(project: WorkspaceProject) -> frozenset[str]:
    if project.student_owner is not None:
        return frozenset({"shared_testkit", "agent_core", "ai_mode", "integration_test_feature"})
    return PRODUCTION_IMPORT_DENYLISTS.get(project.name, frozenset())


def _discover_import_names(project_path: Path) -> set[str]:
    names: set[str] = set()
    for source_root in project_path.rglob("src"):
        if not source_root.is_dir():
            continue
        for child in source_root.iterdir():
            if child.is_dir() and (child / "__init__.py").is_file():
                names.add(child.name)
    return names


def _imports(tree: ast.AST) -> Iterable[tuple[str, int]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module is not None:
            yield node.module, node.lineno


def _is_test_path(project_path: Path, path: Path) -> bool:
    relative = path.relative_to(project_path)
    return "tests" in relative.parts or path.name.startswith("test_")


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as stream:
            return tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"could not read {path}: {exc}") from exc


def _distribution_import_name(value: str) -> str:
    return _normalize_distribution_name(value).replace("-", "_")


def _normalize_distribution_name(value: str) -> str:
    return value.strip().lower().replace("_", "-").replace(".", "-")


def _dependency_distribution_name(requirement: str) -> str:
    name = requirement.split(";", maxsplit=1)[0].strip()
    for delimiter in ("[", " ", "<", ">", "=", "!", "~"):
        name = name.split(delimiter, maxsplit=1)[0]
    return _normalize_distribution_name(name)


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate documented workspace dependency and Python import boundaries."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=REPOSITORY_ROOT,
        help="Repository root to inspect (defaults to the current project).",
    )
    return parser


def main() -> int:
    """Validate the repository and print actionable source locations."""
    arguments = _parser().parse_args()
    try:
        violations = validate_repository(arguments.root.resolve())
    except ValueError as exc:
        print(f"Architecture validation failed: {exc}")
        return 1
    if violations:
        print("Architecture boundary violations:")
        for violation in violations:
            print(f"- {violation}")
        return 1
    print("Validated workspace dependency and Python import boundaries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
