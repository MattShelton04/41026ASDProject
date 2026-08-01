"""Run the repository's deterministic local quality gate."""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

COMMANDS: tuple[tuple[str, ...], ...] = (
    ("ruff", "format", "--check", "."),
    ("ruff", "check", "."),
    (
        "mypy",
        "shared/contracts/python/shared_contracts",
        "shared/testkit/python/shared_testkit",
        "ai-services/agent-core/src/agent_core",
        "ai-services/ai-mode/src/ai_mode",
        "scripts/check.py",
    ),
    (
        "pytest",
        "--cov=agent_core",
        "--cov=ai_mode",
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
