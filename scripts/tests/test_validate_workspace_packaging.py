"""Tests for uv workspace and Docker packaging validation."""

from __future__ import annotations

from pathlib import Path

from scripts.validate_workspace_packaging import validate_workspace_packaging


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        """
[project]
name = "example-root"
version = "0.1.0"

[tool.uv.workspace]
members = ["shared/contracts", "student-1"]
""".strip()
        + "\n",
        encoding="utf-8",
    )
    projects = {
        "shared/contracts": "shared-contracts",
        "student-1": "student-1-feature",
    }
    for member, name in projects.items():
        manifest = root / member / "pyproject.toml"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(f'[project]\nname = "{name}"\nversion = "0.1.0"\n', encoding="utf-8")
    (root / "uv.lock").write_text(
        """
version = 1

[manifest]
members = ["example-root", "shared-contracts", "student-1-feature"]
""".strip()
        + "\n",
        encoding="utf-8",
    )
    dockerfile = root / "student-1" / "Dockerfile"
    dockerfile.write_text(
        """
FROM python:3.12 AS builder
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY shared/contracts/pyproject.toml shared/contracts/pyproject.toml
COPY student-1/pyproject.toml student-1/pyproject.toml
RUN uv sync --locked --package student-1-feature --no-install-workspace
""".lstrip(),
        encoding="utf-8",
    )
    (root / "shared" / "frontend" / "Dockerfile").parent.mkdir(parents=True)
    (root / "shared" / "frontend" / "Dockerfile").write_text(
        "FROM nginx:alpine\nCOPY shared/frontend /usr/share/nginx/html\n",
        encoding="utf-8",
    )
    return root


def test_complete_workspace_lock_and_docker_inputs_pass(tmp_path: Path) -> None:
    assert validate_workspace_packaging(_workspace(tmp_path)) == ()


def test_missing_member_manifest_before_sync_is_source_located(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    dockerfile = root / "student-1" / "Dockerfile"
    dockerfile.write_text(
        dockerfile.read_text(encoding="utf-8").replace(
            "COPY shared/contracts/pyproject.toml shared/contracts/pyproject.toml\n", ""
        ),
        encoding="utf-8",
    )

    violations = validate_workspace_packaging(root)

    assert len(violations) == 1
    assert str(violations[0]) == (
        "student-1/Dockerfile:5: uv workspace sync requires COPY of "
        "shared/contracts/pyproject.toml before this instruction"
    )


def test_manifest_copied_after_first_sync_does_not_satisfy_build(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    dockerfile = root / "student-1" / "Dockerfile"
    source = dockerfile.read_text(encoding="utf-8")
    source = source.replace(
        "COPY shared/contracts/pyproject.toml shared/contracts/pyproject.toml\n", ""
    )
    source += "COPY shared/contracts/pyproject.toml shared/contracts/pyproject.toml\n"
    dockerfile.write_text(source, encoding="utf-8")

    violations = validate_workspace_packaging(root)

    assert len(violations) == 1
    assert "before this instruction" in violations[0].message


def test_stale_docker_manifest_and_lock_member_are_rejected(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    dockerfile = root / "student-1" / "Dockerfile"
    dockerfile.write_text(
        dockerfile.read_text(encoding="utf-8").replace(
            "COPY student-1/pyproject.toml student-1/pyproject.toml\n",
            "COPY student-1/pyproject.toml student-1/pyproject.toml\n"
            "COPY removed/pyproject.toml removed/pyproject.toml\n",
        ),
        encoding="utf-8",
    )
    lock = root / "uv.lock"
    lock.write_text(
        lock.read_text(encoding="utf-8").replace(
            '"student-1-feature"]', '"student-1-feature", "removed-feature"]'
        ),
        encoding="utf-8",
    )

    messages = [item.message for item in validate_workspace_packaging(root)]

    assert messages == [
        "Docker build copies non-workspace manifest removed/pyproject.toml",
        "uv.lock manifest contains non-workspace project removed-feature",
    ]


def test_lock_missing_workspace_distribution_is_rejected(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    lock = root / "uv.lock"
    lock.write_text(
        lock.read_text(encoding="utf-8").replace(', "shared-contracts"', ""),
        encoding="utf-8",
    )

    violations = validate_workspace_packaging(root)

    assert len(violations) == 1
    assert violations[0].path == "uv.lock"
    assert violations[0].message == "uv.lock manifest is missing workspace project shared-contracts"


def test_frontend_only_dockerfile_needs_no_workspace_manifests(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    frontend = root / "shared" / "frontend" / "Dockerfile"
    assert "uv sync" not in frontend.read_text(encoding="utf-8")

    assert validate_workspace_packaging(root) == ()


def test_dockerfiles_in_hidden_runtime_and_worktree_trees_are_ignored(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    stale = (
        (root / "student-1" / "Dockerfile")
        .read_text(encoding="utf-8")
        .replace("COPY shared/contracts/pyproject.toml shared/contracts/pyproject.toml\n", "")
    )
    for hidden in (
        ".propertyscope-runtime/snapshot/student-1",
        ".claude/worktrees/agent/student-1",
    ):
        (root / hidden).mkdir(parents=True)
        (root / hidden / "Dockerfile").write_text(stale, encoding="utf-8")

    assert validate_workspace_packaging(root) == ()
