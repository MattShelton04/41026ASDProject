"""Validate the repository's documented Python dependency boundaries."""

from __future__ import annotations

import argparse
import ast
import re
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

SHARED_CONTRACTS = "shared-contracts"
SHARED_TESTKIT = "shared-testkit"
AGENT_CORE = "agent-core"
AI_MODE = "ai-mode"
PROPERTYSCOPE_DATABASE_IMPORT = "propertyscope_data_store"
POSTGRES_CLIENT_IMPORTS = frozenset({"asyncpg", "psycopg", "psycopg2", "sqlalchemy"})
PROPERTYSCOPE_DATABASE_CREDENTIAL = "PROPERTYSCOPE_DATABASE_URL"
PROPERTYSCOPE_POSTGRES_VOLUMES = frozenset({"f1-postgres-data"})
PROPERTYSCOPE_ARTIFACT_VOLUME = "f1-artifacts"
PROPERTYSCOPE_DATABASE_SERVICES = frozenset({"f1-db-api", "f1-db-loader"})
FRONTEND_STATIC_IMPORT_PATTERN = re.compile(
    r"(?ms)^\s*(?:import\s*[\"'](?P<side_effect>[^\"']+)[\"']|"
    r"(?:import|export)\b(?:(?!;).)*?\bfrom\s*[\"'](?P<from_path>[^\"']+)[\"'])"
)
FRONTEND_DYNAMIC_IMPORT_PATTERN = re.compile(
    r"\bimport\(\s*[\"'](?P<path>[^\"']+)[\"']\s*\)", re.MULTILINE
)
FRONTEND_FILE_READ_PATTERN = re.compile(
    r"\breadFile(?:Sync)?\s*\(\s*(?:new\s+URL\s*\(\s*)?[\"'](?P<path>[^\"']+)[\"']",
    re.MULTILINE,
)
FEATURE_FRONTEND_PATHS = {
    "data-platform": "student-1",
    "market-intelligence": "student-2",
    "suburb-analytics": "student-3",
    "due-diligence": "student-4",
    "buyer-workspaces": "student-5",
}
FEATURE_1_BRIDGE = "shared/frontend/feature-1-bridge.js"
FEATURE_1_ADAPTER = "student-1/frontend/integration/shell.js"

ALLOWED_WORKSPACE_DEPENDENCIES: Mapping[str, frozenset[str]] = {
    SHARED_CONTRACTS: frozenset(),
    SHARED_TESTKIT: frozenset({SHARED_CONTRACTS, AGENT_CORE}),
    AGENT_CORE: frozenset({SHARED_CONTRACTS}),
    AI_MODE: frozenset({SHARED_CONTRACTS, AGENT_CORE}),
}

PRODUCTION_IMPORT_DENYLISTS: Mapping[str, frozenset[str]] = {
    SHARED_CONTRACTS: frozenset({"shared_testkit", "agent_core", "ai_mode"}),
    SHARED_TESTKIT: frozenset({"ai_mode"}),
    AGENT_CORE: frozenset({"shared_testkit", "ai_mode"}),
    AI_MODE: frozenset({"shared_testkit"}),
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


class _ModuleScriptParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.scripts: list[tuple[str, int]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        script_type = values.get("type")
        if (
            tag.lower() == "script"
            and isinstance(script_type, str)
            and script_type.lower() == "module"
            and values.get("src")
        ):
            self.scripts.append((values["src"] or "", self.getpos()[0]))


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
        for path in sorted(
            (*source_root.rglob("*.js"), *source_root.rglob("*.mjs"), *source_root.rglob("*.html"))
        ):
            if "vendor" in path.relative_to(source_root).parts:
                continue
            try:
                source = path.read_text(encoding="utf-8")
            except OSError as exc:
                yield ArchitectureViolation(
                    _relative(root, path), 0, f"could not inspect frontend imports: {exc}"
                )
                continue
            dependencies: list[tuple[str, int, str]] = []
            if path.suffix == ".html":
                parser = _ModuleScriptParser()
                parser.feed(source)
                dependencies.extend(
                    (specifier, line, "module-script") for specifier, line in parser.scripts
                )
            for kind, pattern in (
                ("static-import", FRONTEND_STATIC_IMPORT_PATTERN),
                ("dynamic-import", FRONTEND_DYNAMIC_IMPORT_PATTERN),
                ("file-read", FRONTEND_FILE_READ_PATTERN),
            ):
                dependencies.extend(
                    (
                        match.groupdict().get("path")
                        or match.groupdict().get("side_effect")
                        or match.groupdict().get("from_path")
                        or "",
                        source.count("\n", 0, match.start()) + 1,
                        kind,
                    )
                    for match in pattern.finditer(source)
                )
            for specifier, line, kind in dependencies:
                yield from _validate_frontend_specifier(root, path, owner, specifier, line, kind)


def _validate_frontend_specifier(
    root: Path,
    path: Path,
    owner: str,
    specifier: str,
    line: int,
    kind: str,
) -> Iterable[ArchitectureViolation]:
    normalized = specifier.replace("\\", "/").split("?", 1)[0].split("#", 1)[0]
    target, target_owner, copied_package = _resolve_frontend_target(root, path, normalized)
    if target_owner is None:
        return
    source_relative = _relative(root, path)
    if target_owner == "network":
        yield ArchitectureViolation(
            source_relative,
            line,
            f"frontend modules must use reviewed same-origin paths instead of {specifier}",
        )
        return
    target_relative = _relative(root, target)
    allowed_feature_ingress = (
        owner == "shared"
        and source_relative == FEATURE_1_BRIDGE
        and target_relative == FEATURE_1_ADAPTER
        and kind == "dynamic-import"
        and normalized == "/features/data-platform/integration/shell.js"
    )
    if owner == "shared" and target_owner.startswith("student-") and not allowed_feature_ingress:
        yield ArchitectureViolation(
            source_relative,
            line,
            f"Shared frontend must not import feature-owned module {specifier}",
        )
        return
    if (
        owner.startswith("student-")
        and target_owner.startswith("student-")
        and target_owner != owner
    ):
        yield ArchitectureViolation(
            source_relative,
            line,
            f"{owner} frontend must not import another student's module {specifier}",
        )
        return
    if owner.startswith("student-") and target_owner == "shared" and copied_package:
        expected = f"shared/frontend/{copied_package}/index.js"
        if target_relative != expected:
            yield ArchitectureViolation(
                source_relative,
                line,
                f"{owner} must import Shared {copied_package} through {copied_package}/index.js "
                f"instead of {specifier}",
            )


def _resolve_frontend_target(
    root: Path, source: Path, specifier: str
) -> tuple[Path, str | None, str | None]:
    folded_specifier = specifier.casefold()
    if folded_specifier.startswith(("http:", "https:", "//")):
        return source, "network", None
    if folded_specifier.startswith(("data:", "blob:", "node:")):
        return source, None, None
    if specifier.startswith("/features/"):
        canonical_parts = specifier.strip("/").split("/")
        owner = FEATURE_FRONTEND_PATHS.get(canonical_parts[1]) if len(canonical_parts) > 1 else None
        target = root / owner / "frontend" / Path(*canonical_parts[2:]) if owner else source
        return target.resolve(), owner, None
    if specifier.startswith("/operations/ai-mode/"):
        operation_relative = specifier.removeprefix("/operations/ai-mode/")
        if operation_relative.startswith("assets/"):
            operation_relative = operation_relative.removeprefix("assets/")
        return (
            (
                root / "shared" / "frontend" / "operations" / "ai-mode" / operation_relative
            ).resolve(),
            "shared",
            None,
        )
    if not specifier.startswith((".", "/")):
        return source, None, None
    target = (
        (source.parent / specifier).resolve()
        if specifier.startswith(".")
        else (root / specifier.lstrip("/")).resolve()
    )
    try:
        relative = target.relative_to(root.resolve())
    except ValueError:
        return target, None, None
    target_parts = relative.parts
    if target_parts[:2] == ("shared", "frontend"):
        package = (
            target_parts[2]
            if len(target_parts) > 2 and target_parts[2] in {"browser", "mapping"}
            else None
        )
        return target, "shared", package
    if target_parts and target_parts[0].startswith("student-"):
        target_owner = target_parts[0]
        # Feature images copy Shared packages into these roots. An existing feature-local
        # file wins; only an absent copied-root target is resolved back to Shared.
        if (
            len(target_parts) > 3
            and target_parts[1] == "frontend"
            and target_parts[2] in {"browser", "mapping"}
            and not target.exists()
        ):
            package = target_parts[2]
            shared_target = (
                root / "shared" / "frontend" / package / Path(*target_parts[3:])
            ).resolve()
            return shared_target, "shared", package
        return target, target_owner, None
    return target, None, None


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
            if service_name != "f1-postgres":
                yield ArchitectureViolation(
                    _relative(root, compose_path),
                    0,
                    f"Compose service {service_name} must not mount PostgreSQL volume {volume}",
                )
        artifact_mode = mounts.get(PROPERTYSCOPE_ARTIFACT_VOLUME)
        if service_name == "f1-runner" and artifact_mode != "rw":
            yield ArchitectureViolation(
                _relative(root, compose_path),
                0,
                "Compose service f1-runner must mount f1-artifacts read/write",
            )
        if service_name == "f1-db-loader" and artifact_mode != "ro":
            yield ArchitectureViolation(
                _relative(root, compose_path),
                0,
                "Compose service f1-db-loader must mount f1-artifacts read-only",
            )
        if artifact_mode == "rw" and service_name not in {"f1-runner"}:
            yield ArchitectureViolation(
                _relative(root, compose_path),
                0,
                f"Compose service {service_name} must not write f1-artifacts",
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


def _allowed_workspace_dependencies(
    project: WorkspaceProject,
    projects: tuple[WorkspaceProject, ...],
) -> frozenset[str]:
    if project.student_owner is not None:
        return frozenset({SHARED_CONTRACTS})
    return ALLOWED_WORKSPACE_DEPENDENCIES.get(project.name, frozenset())


def _production_import_denylist(project: WorkspaceProject) -> frozenset[str]:
    if project.student_owner is not None:
        return frozenset({"shared_testkit", "agent_core", "ai_mode"})
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
