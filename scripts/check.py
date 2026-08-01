"""Run the repository's deterministic local quality gate."""

from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

COMMANDS: tuple[tuple[str, ...], ...] = (
    (sys.executable, "-m", "ruff", "format", "--check", "."),
    (sys.executable, "-m", "ruff", "check", "."),
    (sys.executable, "scripts/generate_contracts.py", "--check"),
    (
        sys.executable,
        "-m",
        "mypy",
        "shared/contracts/python/shared_contracts",
        "shared/testkit/python/shared_testkit",
        "ai-services/agent-core/src/agent_core",
        "ai-services/ai-mode/src/ai_mode",
        "examples/integration-test-feature/src/integration_test_feature",
        "scripts/check.py",
        "scripts/generate_contracts.py",
    ),
    (
        sys.executable,
        "-m",
        "pytest",
        "--cov=agent_core",
        "--cov=ai_mode",
        "--cov=integration_test_feature",
        "--cov=shared_contracts",
        "--cov=shared_testkit",
        "--cov-report=term-missing",
    ),
)


def main() -> None:
    """Run each check in fail-fast order."""
    for command in COMMANDS:
        print(f"\n> {shlex.join(command)}", flush=True)
        subprocess.run(command, cwd=REPOSITORY_ROOT, check=True)


if __name__ == "__main__":
    main()
