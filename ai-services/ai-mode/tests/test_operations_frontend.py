"""Behavior tests for the framework-free operations polling module."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
POLLING_TEST = (
    REPOSITORY_ROOT / "shared" / "frontend" / "operations" / "ai-mode" / "polling.test.mjs"
)


def test_operations_polling_behavior_with_node_builtin_runner() -> None:
    """Keep browser-independent scheduling behavior deterministic in the canonical suite."""
    node = shutil.which("node")
    assert node is not None, "Node.js 20 or newer is required for frontend behavior tests"

    completed = subprocess.run(
        [node, "--test", str(POLLING_TEST)],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
