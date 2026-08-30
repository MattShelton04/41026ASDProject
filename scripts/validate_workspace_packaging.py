"""Validate uv workspace metadata and Docker build-manifest inputs."""

from __future__ import annotations

import argparse
import re
import shlex
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE_NAME = "Dockerfile"
UV_SYNC_PATTERN = re.compile(r"\buv\s+sync\b")


@dataclass(frozen=True, slots=True, order=True)
class WorkspacePackagingViolation:
    """One deterministic workspace or Docker packaging violation."""

    path: str
    line: int
    message: str

    def __str__(self) -> str:
        location = f"{self.path}:{self.line}" if self.line else self.path
        return f"{location}: {self.message}"


@dataclass(frozen=True, slots=True)
class WorkspaceMember:
    """One uv workspace member and its normalized distribution name."""

    path: str
    name: str

    @property
    def manifest_path(self) -> str:
        return f"{self.path}/pyproject.toml"


def validate_workspace_packaging(
    root: Path = REPOSITORY_ROOT,
) -> tuple[WorkspacePackagingViolation, ...]:
    """Return lock and Docker workspace-manifest drift in stable order."""
    members, root_name = _load_workspace(root)
    violations = [*_validate_lock(root, members, root_name)]
    for dockerfile in sorted(root.rglob(DOCKERFILE_NAME)):
        violations.extend(_validate_dockerfile(root, dockerfile, members))
    return tuple(sorted(violations))


def _load_workspace(root: Path) -> tuple[tuple[WorkspaceMember, ...], str | None]:
    root_manifest = _read_toml(root / "pyproject.toml")
    raw_members = root_manifest.get("tool", {}).get("uv", {}).get("workspace", {}).get("members")
    if not isinstance(raw_members, list) or not all(
        isinstance(member, str) and member for member in raw_members
    ):
        raise ValueError("root pyproject.toml must define non-empty string uv workspace members")
    members: list[WorkspaceMember] = []
    for raw_member in raw_members:
        member_path = _repository_relative_path(raw_member, field="workspace member")
        manifest_path = root / member_path / "pyproject.toml"
        manifest = _read_toml(manifest_path)
        name = manifest.get("project", {}).get("name")
        if not isinstance(name, str) or not name:
            raise ValueError(f"workspace member {member_path} has no project name")
        members.append(WorkspaceMember(path=member_path, name=_normalize_name(name)))
    duplicate_paths = _duplicates(member.path for member in members)
    duplicate_names = _duplicates(member.name for member in members)
    if duplicate_paths:
        raise ValueError(f"duplicate uv workspace member path(s): {', '.join(duplicate_paths)}")
    if duplicate_names:
        raise ValueError(f"duplicate uv workspace project name(s): {', '.join(duplicate_names)}")
    root_name = root_manifest.get("project", {}).get("name")
    return tuple(members), _normalize_name(root_name) if isinstance(root_name, str) else None


def _validate_lock(
    root: Path,
    members: tuple[WorkspaceMember, ...],
    root_name: str | None,
) -> Iterable[WorkspacePackagingViolation]:
    lock_path = root / "uv.lock"
    lock = _read_toml(lock_path)
    raw_lock_members = lock.get("manifest", {}).get("members")
    relative_lock = _relative(root, lock_path)
    if not isinstance(raw_lock_members, list) or not all(
        isinstance(member, str) and member for member in raw_lock_members
    ):
        yield WorkspacePackagingViolation(
            relative_lock,
            0,
            "uv.lock manifest.members must contain distribution names",
        )
        return
    actual = {_normalize_name(member) for member in raw_lock_members}
    expected = {member.name for member in members}
    if root_name is not None:
        expected.add(root_name)
    for missing in sorted(expected - actual):
        yield WorkspacePackagingViolation(
            relative_lock,
            0,
            f"uv.lock manifest is missing workspace project {missing}",
        )
    for stale in sorted(actual - expected):
        yield WorkspacePackagingViolation(
            relative_lock,
            0,
            f"uv.lock manifest contains non-workspace project {stale}",
        )


def _validate_dockerfile(
    root: Path,
    dockerfile: Path,
    members: tuple[WorkspaceMember, ...],
) -> Iterable[WorkspacePackagingViolation]:
    try:
        source = dockerfile.read_text(encoding="utf-8")
    except OSError as exc:
        yield WorkspacePackagingViolation(
            _relative(root, dockerfile), 0, f"could not inspect Dockerfile: {exc}"
        )
        return
    logical_lines = tuple(_docker_logical_lines(source))
    sync_lines = [
        line for line, instruction in logical_lines if UV_SYNC_PATTERN.search(instruction)
    ]
    if not sync_lines:
        return
    first_sync_line = sync_lines[0]
    copied: dict[str, int] = {}
    for line, instruction in logical_lines:
        if line >= first_sync_line:
            break
        verb, _, arguments = instruction.partition(" ")
        if verb.upper() != "COPY":
            continue
        for source_path in _copy_sources(arguments):
            copied[source_path] = line

    relative_dockerfile = _relative(root, dockerfile)
    expected = {
        "pyproject.toml",
        "uv.lock",
        *(member.manifest_path for member in members),
    }
    copied_manifests = {
        path for path in copied if path == "pyproject.toml" or path.endswith("/pyproject.toml")
    }
    for missing in sorted(expected - copied.keys()):
        yield WorkspacePackagingViolation(
            relative_dockerfile,
            first_sync_line,
            f"uv workspace sync requires COPY of {missing} before this instruction",
        )
    for stale in sorted(copied_manifests - expected):
        yield WorkspacePackagingViolation(
            relative_dockerfile,
            copied[stale],
            f"Docker build copies non-workspace manifest {stale}",
        )


def _docker_logical_lines(source: str) -> Iterable[tuple[int, str]]:
    parts: list[str] = []
    start_line = 0
    for line_number, raw_line in enumerate(source.splitlines(), start=1):
        stripped = raw_line.strip()
        if not parts and (not stripped or stripped.startswith("#")):
            continue
        if not parts:
            start_line = line_number
        continued = stripped.endswith("\\")
        parts.append(stripped.removesuffix("\\").strip())
        if not continued:
            yield start_line, " ".join(parts)
            parts = []
    if parts:
        yield start_line, " ".join(parts)


def _copy_sources(arguments: str) -> tuple[str, ...]:
    try:
        tokens = shlex.split(arguments, posix=True)
    except ValueError:
        return ()
    positional = [token for token in tokens if not token.startswith("--")]
    if len(positional) < 2:
        return ()
    return tuple(token.removeprefix("./").replace("\\", "/") for token in positional[:-1])


def _repository_relative_path(value: str, *, field: str) -> str:
    normalized = value.replace("\\", "/")
    path = Path(normalized)
    if path.is_absolute() or ".." in path.parts or normalized.startswith("/"):
        raise ValueError(f"{field} must be a repository-relative path: {value!r}")
    canonical = path.as_posix().removeprefix("./").rstrip("/")
    if not canonical or canonical == ".":
        raise ValueError(f"{field} must not be empty")
    return canonical


def _duplicates(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return tuple(sorted(duplicates))


def _normalize_name(value: str) -> str:
    return value.strip().lower().replace("_", "-").replace(".", "-")


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as stream:
            return tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"could not read {path}: {exc}") from exc


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate uv workspace lock and Docker manifest inputs."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=REPOSITORY_ROOT,
        help="Repository root to inspect (defaults to the current project).",
    )
    return parser


def main() -> int:
    """Validate packaging metadata and print actionable source locations."""
    arguments = _parser().parse_args()
    try:
        violations = validate_workspace_packaging(arguments.root.resolve())
    except ValueError as exc:
        print(f"Workspace packaging validation failed: {exc}")
        return 1
    if violations:
        print("Workspace packaging violations:")
        for violation in violations:
            print(f"- {violation}")
        return 1
    print("Validated uv workspace lock and Docker manifest inputs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
