"""Run composable deterministic quality checks from the repository root."""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CORE_TEST_PATHS = (
    "shared/contracts/tests",
    "shared/testkit/tests",
    "ai-services/agent-core/tests",
    "ai-services/ai-mode/tests",
    "scripts/tests",
)
FRONTEND_TEST_PATHS = (
    "poc/feature-6/tests/frontend-model.test.mjs",
    "student-1/tests/frontend/core.test.mjs",
    "shared/frontend/dashboard.test.mjs",
    "shared/frontend/ai-chat/ai-chat.test.mjs",
    "shared/frontend/mapping/mapping.test.mjs",
    "shared/frontend/operations/ai-mode/polling.test.mjs",
)
JAVASCRIPT_SOURCE_ROOTS = (
    REPOSITORY_ROOT / "poc" / "feature-6" / "frontend",
    REPOSITORY_ROOT / "shared" / "frontend",
    REPOSITORY_ROOT / "student-1" / "frontend",
)

Command = tuple[str, ...]

FORMAT_CHECK_COMMANDS: tuple[Command, ...] = (
    (sys.executable, "-m", "ruff", "format", "--check", "."),
)
FORMAT_WRITE_COMMANDS: tuple[Command, ...] = ((sys.executable, "-m", "ruff", "format", "."),)
LINT_COMMANDS: tuple[Command, ...] = ((sys.executable, "-m", "ruff", "check", "."),)
ARCHITECTURE_COMMANDS: tuple[Command, ...] = (
    (sys.executable, "scripts/generate_contracts.py", "--check"),
    (sys.executable, "scripts/validate_architecture.py"),
    (sys.executable, "scripts/validate_model_registry.py"),
    (sys.executable, "scripts/validate_tool_catalogs.py"),
)
STYLE_COMMANDS: tuple[Command, ...] = ((sys.executable, "scripts/validate_frontend_styles.py"),)
TYPECHECK_COMMANDS: tuple[Command, ...] = (
    (
        sys.executable,
        "-m",
        "mypy",
        "shared/contracts/python/shared_contracts",
        "shared/testkit/python/shared_testkit",
        "ai-services/agent-core/src/agent_core",
        "ai-services/ai-mode/src/ai_mode",
        "student-1/backend/src/propertyscope_data_platform",
        "student-1/database/src/propertyscope_data_store",
        "poc/feature-6/backend/src/propertyscope_integration_poc",
        "poc/feature-6/database/src/propertyscope_integration_store",
        "student-1/tests",
        "scripts/ui_audit",
        "scripts/devtools",
        "scripts/check.py",
        "scripts/dev.py",
        "scripts/generate_contracts.py",
        "scripts/validate_architecture.py",
        "scripts/validate_frontend_styles.py",
        "scripts/validate_model_registry.py",
        "scripts/validate_tool_catalogs.py",
    ),
)
TEST_COMMANDS: tuple[Command, ...] = (
    (
        sys.executable,
        "-m",
        "pytest",
        "--cov=agent_core",
        "--cov=ai_mode",
        "--cov=shared_contracts",
        "--cov=shared_testkit",
        "--cov-report=term-missing",
        *CORE_TEST_PATHS,
    ),
    (
        sys.executable,
        "-m",
        "pytest",
        "poc/feature-6/tests",
    ),
    (
        sys.executable,
        "-m",
        "pytest",
        "--cov=propertyscope_data_platform",
        "--cov=propertyscope_data_store",
        "--cov-report=term-missing",
        "--cov-fail-under=60",
        "--ignore=student-1/tests/e2e/test_form_behaviour_playwright.py",
        "student-1/tests",
    ),
    ("node", "--test", *FRONTEND_TEST_PATHS),
)


def javascript_sources() -> tuple[str, ...]:
    """Return first-party browser modules as stable repository-relative paths."""
    sources: list[str] = []
    for root in JAVASCRIPT_SOURCE_ROOTS:
        for path in root.rglob("*.js"):
            relative = path.relative_to(REPOSITORY_ROOT)
            if "vendor" in relative.parts:
                continue
            sources.append(relative.as_posix())
    return tuple(sorted(sources))


def compile_commands() -> tuple[Command, ...]:
    """Build dependency-free JavaScript syntax checks for every first-party module."""
    return tuple(("node", "--check", source) for source in javascript_sources())


def commands_for(stage: str, *, write: bool = False) -> tuple[Command, ...]:
    """Return the commands for one public quality stage."""
    stages: dict[str, tuple[Command, ...]] = {
        "format": FORMAT_WRITE_COMMANDS if write else FORMAT_CHECK_COMMANDS,
        "lint": LINT_COMMANDS,
        "architecture": ARCHITECTURE_COMMANDS,
        "styles": STYLE_COMMANDS,
        "typecheck": TYPECHECK_COMMANDS,
        "compile": compile_commands(),
        "test": TEST_COMMANDS,
    }
    if stage == "check":
        return tuple(
            command
            for name in (
                "format",
                "lint",
                "architecture",
                "styles",
                "typecheck",
                "compile",
                "test",
            )
            for command in stages[name]
        )
    return stages[stage]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a deterministic repository quality stage (default: check)."
    )
    commands = parser.add_subparsers(dest="stage")
    formatter = commands.add_parser("format", help="Check Python formatting")
    formatter.add_argument(
        "--write",
        action="store_true",
        help="Apply Python formatting instead of checking it",
    )
    commands.add_parser("lint", help="Run Ruff lint checks")
    commands.add_parser("architecture", help="Validate contracts and repository boundaries")
    commands.add_parser("styles", help="Validate the reviewed frontend style baseline")
    commands.add_parser("typecheck", help="Run strict Python type checking")
    commands.add_parser("compile", help="Syntax-check first-party browser JavaScript")
    commands.add_parser("test", help="Run deterministic Python and frontend tests")
    commands.add_parser("check", help="Run every deterministic pre-pull-request check")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the selected checks in fail-fast order."""
    arguments = _parser().parse_args(argv)
    stage = arguments.stage or "check"
    write = bool(getattr(arguments, "write", False))
    for command in commands_for(stage, write=write):
        print(f"\n> {shlex.join(command)}", flush=True)
        try:
            subprocess.run(command, cwd=REPOSITORY_ROOT, check=True)
        except FileNotFoundError:
            print(
                f"error: {command[0]} is not available. See README.md for prerequisites.",
                file=sys.stderr,
            )
            return 2
        except subprocess.CalledProcessError as exc:
            return exc.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
