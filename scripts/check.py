"""Run the repository's deterministic local quality gate."""

from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CORE_TEST_PATHS = (
    "shared/contracts/tests",
    "shared/testkit/tests",
    "ai-services/agent-core/tests",
    "ai-services/ai-mode/tests",
    "examples/integration-test-feature/tests",
    "scripts/tests",
)
FRONTEND_TEST_PATHS = (
    "student-1/tests/frontend/core.test.mjs",
    "shared/frontend/dashboard.test.mjs",
    "shared/frontend/mapping/mapping.test.mjs",
    "shared/frontend/operations/ai-mode/polling.test.mjs",
)

COMMANDS: tuple[tuple[str, ...], ...] = (
    (sys.executable, "-m", "ruff", "format", "--check", "."),
    (sys.executable, "-m", "ruff", "check", "."),
    (sys.executable, "scripts/generate_contracts.py", "--check"),
    (sys.executable, "scripts/validate_architecture.py"),
    (sys.executable, "scripts/validate_frontend_styles.py"),
    (sys.executable, "scripts/validate_model_registry.py"),
    (sys.executable, "scripts/validate_tool_catalogs.py"),
    (
        sys.executable,
        "-m",
        "mypy",
        "shared/contracts/python/shared_contracts",
        "shared/testkit/python/shared_testkit",
        "ai-services/agent-core/src/agent_core",
        "ai-services/ai-mode/src/ai_mode",
        "examples/integration-test-feature/src/integration_test_feature",
        "student-1/backend/src/propertyscope_data_platform",
        "student-1/database/src/propertyscope_data_store",
        "scripts/ui_audit",
        "scripts/check.py",
        "scripts/dev.py",
        "scripts/generate_contracts.py",
        "scripts/validate_architecture.py",
        "scripts/validate_frontend_styles.py",
        "scripts/validate_model_registry.py",
        "scripts/validate_tool_catalogs.py",
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
        *CORE_TEST_PATHS,
    ),
    (
        sys.executable,
        "-m",
        "pytest",
        "--cov=propertyscope_data_platform",
        "--cov=propertyscope_data_store",
        "--cov-report=term-missing",
        "--cov-fail-under=60",
        "student-1/tests",
    ),
    ("node", "--test", *FRONTEND_TEST_PATHS),
)


def main() -> None:
    """Run each check in fail-fast order."""
    for command in COMMANDS:
        print(f"\n> {shlex.join(command)}", flush=True)
        subprocess.run(command, cwd=REPOSITORY_ROOT, check=True)


if __name__ == "__main__":
    main()
