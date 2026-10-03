"""Visual CI captures immutable application revisions without development mounts."""

from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _workflow() -> dict:
    return yaml.safe_load((ROOT / ".github/workflows/visual-capture.yml").read_text())


def test_capture_builds_revision_images_without_read_only_nested_source_mounts() -> None:
    steps = _workflow()["jobs"]["capture"]["steps"]
    startup = next(step for step in steps if step["name"] == "Start offline stack")
    assert startup["working-directory"] == "app"
    assert {"--offline", "--no-reload", "--build"} <= set(startup["run"].split())
    browser = next(step for step in steps if step["name"] == "Install lockfile-pinned Chromium")
    assert "--only-shell" in browser["run"].split()
    assert "--with-deps" in browser["run"].split()
    canaries = next(step for step in steps if step["name"] == "Harness policy tests")
    assert canaries["env"]["VISUAL_REQUIRE_BROWSER"] == "1"


def test_capture_triggers_cover_the_runtime_and_packaging_inputs_it_executes() -> None:
    events = _workflow()[True]  # PyYAML's YAML 1.1 parser reads the `on` key as a boolean.
    for event in ("push", "pull_request"):
        for path in (
            "student-4/pyproject.toml",
            "student-4/feature.yaml",
            "shared/contracts/pyproject.toml",
            "scripts/dev.py",
            "scripts/devtools/cli.py",
        ):
            assert any(fnmatchcase(path, pattern) for pattern in events[event]["paths"]), path
