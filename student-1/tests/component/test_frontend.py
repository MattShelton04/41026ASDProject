"""Deterministic behavior checks for the framework-free Feature 1 frontend modules."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FRONTEND_TEST = REPOSITORY_ROOT / "student-1" / "tests" / "frontend" / "core.test.mjs"
FRONTEND_BOOTSTRAP = "./scripts/frontend-test-bootstrap.mjs"


def test_feature_frontend_behavior_with_node_builtin_runner() -> None:
    """Keep API, routing, formatting, polling and route wiring in the canonical gate."""
    node = shutil.which("node")
    assert node is not None, "Node.js 20 or newer is required for frontend behavior tests"

    completed = subprocess.run(  # noqa: S603 - node test argv without a shell
        [node, "--import", str(FRONTEND_BOOTSTRAP), "--test", str(FRONTEND_TEST)],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
