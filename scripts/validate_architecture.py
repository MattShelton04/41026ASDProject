"""Validate the repository's documented Python dependency boundaries."""

from __future__ import annotations

import argparse
import ast
import re
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

SHARED_CONTRACTS = "shared-contracts"
SHARED_TESTKIT = "shared-testkit"
AGENT_CORE = "agent-core"
AI_MODE = "ai-mode"
INTEGRATION_FIXTURE = "integration-test-feature"
PROPERTYSCOPE_DATABASE_IMPORT = "propertyscope_data_store"
POSTGRES_CLIENT_IMPORTS = frozenset({"asyncpg", "psycopg", "psycopg2", "sqlalchemy"})
PROPERTYSCOPE_DATABASE_CREDENTIAL = "PROPERTYSCOPE_DATABASE_URL"
PROPERTYSCOPE_POSTGRES_VOLUMES = frozenset(
    {"propertyscope_postgres_data", "propertyscope_postgres_full_data"}
)
PROPERTYSCOPE_ARTIFACT_VOLUME = "propertyscope_artifacts"
PROPERTYSCOPE_DATABASE_SERVICES = frozenset(
    {"propertyscope-database-api", "propertyscope-database-loader"}
)
FRONTEND_IMPORT_PATTERN = re.compile(
    r"(?:\bimport\s+(?:[^;\n]*?\s+from\s+)?|\bexport\s+[^;\n]*?\s+from\s+)"
    r"[\"'](?P<static>[^\"']+)[\"']|\bimport\(\s*[\"'](?P<dynamic>[^\"']+)[\"']\s*\)"
)
SHARED_FRONTEND_LITERAL_PATTERN = re.compile(r"[\"'](?P<path>[^\"']*shared/frontend/[^\"']+)[\"']")
PUBLIC_FRONTEND_ENTRYPOINTS = frozenset({"browser/index.js", "mapping/index.js"})

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
        *_validate_frontend_imports(root),
        *_validate_compose_boundaries(root),
    ]
    return tuple(sorted(violations))


def _validate_frontend_imports(root: Path) -> Iterable[ArchitectureViolation]:
    source_roots = [(root / "shared" / "frontend", "shared")]
    for number in range(1, 6):
        owner = f"student-{number}"
        source_roots.extend(
            [
                (root / owner / "frontend", owner),
                (root / owner / "tests" / "frontend", owner),
            ]
        )
    for source_root, owner in source_roots:
        if not source_root.is_dir():
            continue
        for path in sorted((*source_root.rglob("*.js"), *source_root.rglob("*.mjs"))):
            if "vendor" in path.relative_to(source_root).parts:
                continue
            try:
                source = path.read_text(encoding="utf-8")
            except OSError as exc:
                yield ArchitectureViolation(
                    _relative(root, path), 0, f"could not inspect frontend imports: {exc}"
                )
                continue
            import_spans: list[tuple[int, int]] = []
            for match in FRONTEND_IMPORT_PATTERN.finditer(source):
                import_spans.append(match.span())
                specifier = (match.group("static") or match.group("dynamic")).split("?", 1)[0]
                line = source.count("\n", 0, match.start()) + 1
                yield from _validate_frontend_specifier(root, path, owner, specifier, line)
            if owner != "shared":
                for match in SHARED_FRONTEND_LITERAL_PATTERN.finditer(source):
                    if any(start <= match.start() < end for start, end in import_spans):
                        continue
                    specifier = match.group("path").split("?", 1)[0]
                    line = source.count("\n", 0, match.start()) + 1
                    if not any(
                        specifier.endswith(entrypoint) for entrypoint in PUBLIC_FRONTEND_ENTRYPOINTS
                    ):
                        yield ArchitectureViolation(
                            _relative(root, path),
                            line,
                            f"{owner} must use a Shared frontend public index instead of "
                            f"{specifier}",
                        )


def _validate_frontend_specifier(
    root: Path,
    path: Path,
    owner: str,
    specifier: str,
    line: int,
) -> Iterable[ArchitectureViolation]:
    normalized = specifier.replace("\\", "/")
    student_references = set(re.findall(r"student-[1-5]", normalized))
    if owner == "shared" and student_references:
        yield ArchitectureViolation(
            _relative(root, path),
            line,
            f"Shared frontend must not import feature-owned module {specifier}",
        )
        return
    if owner.startswith("student-") and any(item != owner for item in student_references):
        yield ArchitectureViolation(
            _relative(root, path),
            line,
            f"{owner} frontend must not import another student's module {specifier}",
        )
        return
    if owner.startswith("student-"):
        for package in ("browser", "mapping"):
            marker = f"/{package}/"
            if marker in f"/{normalized}" and not normalized.endswith(f"/{package}/index.js"):
                yield ArchitectureViolation(
                    _relative(root, path),
                    line,
                    f"{owner} frontend must import Shared {package} through {package}/index.js",
                )
    if not normalized.startswith("."):
        return
    resolved = (path.parent / normalized).resolve()
    try:
        relative = resolved.relative_to(root.resolve())
    except ValueError:
        return
    if owner == "shared" and relative.parts and relative.parts[0].startswith("student-"):
        yield ArchitectureViolation(
            _relative(root, path),
            line,
            f"Shared frontend must not import feature-owned module {specifier}",
        )


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
                elif not is_test:
                    yield from _validate_propertyscope_import(root, project, path, module, line)


def _validate_propertyscope_import(
    root: Path,
    project: WorkspaceProject,
    path: Path,
    module: str,
    line: int,
) -> Iterable[ArchitectureViolation]:
    if project.student_owner is None:
        return
    relative = path.relative_to(project.path)
    inside_propertyscope_database = bool(
        project.student_owner == "student-1" and relative.parts and relative.parts[0] == "database"
    )
    top_level = module.partition(".")[0]
    if not inside_propertyscope_database and top_level in POSTGRES_CLIENT_IMPORTS:
        yield ArchitectureViolation(
            _relative(root, path),
            line,
            f"Only Feature 1 database/ may import PostgreSQL client {module}",
        )
    if (
        project.student_owner == "student-1"
        and not inside_propertyscope_database
        and top_level == PROPERTYSCOPE_DATABASE_IMPORT
    ):
        yield ArchitectureViolation(
            _relative(root, path),
            line,
            "Feature 1 backend/runner must call its database service over HTTP, not import it",
        )


def _validate_compose_boundaries(root: Path) -> Iterable[ArchitectureViolation]:
    compose_path = root / "docker-compose.yml"
    if not compose_path.is_file():
        return
    try:
        document = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        yield ArchitectureViolation(
            _relative(root, compose_path), 0, f"could not inspect Compose boundaries: {exc}"
        )
        return
    if not isinstance(document, dict):
        yield ArchitectureViolation(_relative(root, compose_path), 0, "Compose root must be a map")
        return
    services = document.get("services", {})
    if not isinstance(services, dict):
        yield ArchitectureViolation(
            _relative(root, compose_path), 0, "Compose services must be a map"
        )
        return
    if not PROPERTYSCOPE_DATABASE_SERVICES.issubset(services):
        # Feature 1 has not been integrated in older/minimal fixture repositories.
        return

    for service_name, raw_service in services.items():
        if not isinstance(service_name, str) or not isinstance(raw_service, dict):
            continue
        environment = _compose_environment(raw_service.get("environment"))
        has_database_url = PROPERTYSCOPE_DATABASE_CREDENTIAL in environment
        if has_database_url != (service_name in PROPERTYSCOPE_DATABASE_SERVICES):
            expectation = (
                "must receive"
                if service_name in PROPERTYSCOPE_DATABASE_SERVICES
                else "must not receive"
            )
            yield ArchitectureViolation(
                _relative(root, compose_path),
                0,
                f"Compose service {service_name} {expectation} {PROPERTYSCOPE_DATABASE_CREDENTIAL}",
            )

        mounts = _compose_mounts(raw_service.get("volumes"))
        for volume in PROPERTYSCOPE_POSTGRES_VOLUMES.intersection(mounts):
            if service_name != "propertyscope-postgres":
                yield ArchitectureViolation(
                    _relative(root, compose_path),
                    0,
                    f"Compose service {service_name} must not mount PostgreSQL volume {volume}",
                )
        artifact_mode = mounts.get(PROPERTYSCOPE_ARTIFACT_VOLUME)
        if service_name == "propertyscope-runner" and artifact_mode != "rw":
            yield ArchitectureViolation(
                _relative(root, compose_path),
                0,
                "Compose service propertyscope-runner must mount "
                "propertyscope_artifacts read/write",
            )
        if service_name == "propertyscope-database-loader" and artifact_mode != "ro":
            yield ArchitectureViolation(
                _relative(root, compose_path),
                0,
                "Compose service propertyscope-database-loader must mount "
                "propertyscope_artifacts read-only",
            )
        if artifact_mode == "rw" and service_name not in {"propertyscope-runner"}:
            yield ArchitectureViolation(
                _relative(root, compose_path),
                0,
                f"Compose service {service_name} must not write propertyscope_artifacts",
            )

        if _enables_full_data(environment):
            profiles = raw_service.get("profiles", [])
            if not isinstance(profiles, list) or "full-data" not in profiles:
                yield ArchitectureViolation(
                    _relative(root, compose_path),
                    0,
                    f"Compose service {service_name} enables full data without "
                    "the full-data profile",
                )

    full_data_path = root / "docker-compose.full-data.yml"
    if full_data_path.is_file():
        yield from _validate_full_data_overlay(root, full_data_path)


def _validate_full_data_overlay(root: Path, path: Path) -> Iterable[ArchitectureViolation]:
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        yield ArchitectureViolation(
            _relative(root, path), 0, f"could not inspect full-data Compose overlay: {exc}"
        )
        return
    services = document.get("services", {}) if isinstance(document, dict) else {}
    if not isinstance(services, dict):
        yield ArchitectureViolation(_relative(root, path), 0, "Compose services must be a map")
        return
    for service_name, raw_service in services.items():
        if not isinstance(service_name, str) or not isinstance(raw_service, dict):
            continue
        environment = _compose_environment(raw_service.get("environment"))
        if not _enables_full_data(environment):
            continue
        profiles = raw_service.get("profiles", [])
        if not isinstance(profiles, list) or "full-data" not in profiles:
            yield ArchitectureViolation(
                _relative(root, path),
                0,
                f"Compose service {service_name} enables full data without the full-data profile",
            )


def _compose_environment(raw: object) -> dict[str, object]:
    if isinstance(raw, dict):
        return {str(key): value for key, value in raw.items()}
    if isinstance(raw, list):
        return {
            entry.partition("=")[0]: entry.partition("=")[2]
            for entry in raw
            if isinstance(entry, str)
        }
    return {}


def _compose_mounts(raw: object) -> dict[str, str]:
    mounts: dict[str, str] = {}
    if not isinstance(raw, list):
        return mounts
    for item in raw:
        if isinstance(item, str):
            parts = item.split(":")
            if len(parts) >= 2:
                mounts[parts[0]] = parts[2] if len(parts) >= 3 else "rw"
        elif isinstance(item, dict) and item.get("type") == "volume":
            source = item.get("source")
            if isinstance(source, str):
                mounts[source] = "ro" if item.get("read_only") is True else "rw"
    return mounts


def _enables_full_data(environment: Mapping[str, object]) -> bool:
    value = environment.get("PROPERTYSCOPE_FULL_DATA_ENABLED")
    return isinstance(value, (str, bool)) and str(value).lower() in {"1", "true", "yes"}


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
        description="Validate documented dependency, import, credential, and volume boundaries."
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
    print("Validated workspace dependency, import, credential, and volume boundaries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
