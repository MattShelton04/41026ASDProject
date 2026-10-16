"""Shared isolation for script tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts import check, dev


@pytest.fixture(autouse=True)
def ignore_developer_env_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep a developer's real root .env out of tests; every dev.py command loads it."""
    monkeypatch.setattr(dev, "DEFAULT_ENV_FILE", tmp_path / "absent.env")


@pytest.fixture(autouse=True)
def ignore_hook_git_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    """Git hooks export GIT_DIR and friends; a test's temporary repository must not inherit them."""
    for name in check.GIT_REPOSITORY_ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)
