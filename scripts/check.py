"""Run composable deterministic quality checks from the repository root."""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.onboarding import OnboardingConfigurationError, discover_quality_inputs

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CORE_TEST_PATHS = (
    "shared/contracts/tests",
    "shared/consumer-protocol/tests",
    "shared/testkit/tests",
    "ai-services/agent-core/tests",
    "ai-services/ai-mode/tests",
    "scripts/tests",
)
FRONTEND_TEST_PATHS = (
    "shared/frontend/browser/browser.test.mjs",
    "shared/frontend/dashboard.test.mjs",
    "shared/frontend/ai-chat/ai-chat.test.mjs",
    "shared/frontend/mapping/mapping.test.mjs",
    "shared/frontend/operations/ai-mode/polling.test.mjs",
)
JAVASCRIPT_SOURCE_ROOTS = (
    REPOSITORY_ROOT / "shared" / "frontend",
    *sorted(REPOSITORY_ROOT.glob("student-*/frontend")),
)

Command = tuple[str, ...]

FORMAT_CHECK_COMMANDS: tuple[Command, ...] = (
    (sys.executable, "-m", "ruff", "format", "--check", "."),
)
FORMAT_WRITE_COMMANDS: tuple[Command, ...] = ((sys.executable, "-m", "ruff", "format", "."),)
LINT_COMMANDS: tuple[Command, ...] = ((sys.executable, "-m", "ruff", "check", "."),)
ARCHITECTURE_COMMANDS: tuple[Command, ...] = (
    (sys.executable, "scripts/generate_contracts.py", "--check"),
    (sys.executable, "scripts/generate_deployment.py", "--check"),
    (sys.executable, "scripts/validate_architecture.py"),
    (sys.executable, "scripts/validate_workspace_packaging.py"),
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
        "shared/consumer-protocol/python/shared_consumer_protocol",
        "shared/testkit/python/shared_testkit",
        "ai-services/agent-core/src/agent_core",
        "ai-services/ai-mode/src/ai_mode",
        "student-1/backend/src/propertyscope_data_platform",
        "student-1/database/src/propertyscope_data_store",
        "student-1/tests",
        "student-2/backend/src/propertyscope_market_intelligence",
        "student-2/database/src/propertyscope_market_store",
        "student-2/tests",
        "student-3/backend/src/propertyscope_suburb_analytics",
        "student-3/database/src/propertyscope_suburb_store",
        "student-4/backend/src/propertyscope_due_diligence",
        "student-4/database/src/propertyscope_due_diligence_store",
        "student-5/backend/src/propertyscope_buyer_workspaces",
        "student-5/database/src/propertyscope_buyer_store",
        "scripts/ui_audit",
        "scripts/devtools",
        "scripts/check.py",
        "scripts/dev.py",
        "scripts/generate_contracts.py",
        "scripts/generate_deployment.py",
        "scripts/live_nginx_recreation.py",
        "scripts/onboarding.py",
        "scripts/validate_architecture.py",
        "scripts/validate_frontend_styles.py",
        "scripts/validate_model_registry.py",
        "scripts/validate_tool_catalogs.py",
        "scripts/validate_workspace_packaging.py",
    ),
)
SHARED_TEST_COMMAND: Command = (
    sys.executable,
    "-m",
    "pytest",
    "--cov=agent_core",
    "--cov=ai_mode",
    "--cov=shared_contracts",
    "--cov=shared_consumer_protocol",
    "--cov=shared_testkit",
    "--cov-report=term-missing",
    *CORE_TEST_PATHS,
)


def test_commands() -> tuple[Command, ...]:
    """Build enabled feature-owned quality commands from validated metadata."""
    feature_inputs = discover_quality_inputs(REPOSITORY_ROOT)
    commands: list[Command] = [SHARED_TEST_COMMAND]
    for feature in feature_inputs.features:
        if not feature.python_test_paths:
            continue
        coverage_arguments = tuple(f"--cov={package}" for package in feature.coverage_packages)
        coverage_report = ("--cov-report=term-missing",) if coverage_arguments else ()
        coverage_threshold = (
            (f"--cov-fail-under={feature.coverage_fail_under}",)
            if feature.coverage_fail_under is not None
            else ()
        )
        commands.append(
            (
                sys.executable,
                "-m",
                "pytest",
                *coverage_arguments,
                *coverage_report,
                *coverage_threshold,
                "--ignore-glob=*/tests/e2e/*",
                *feature.python_test_paths,
            )
        )
    node_tests = (*FRONTEND_TEST_PATHS, *feature_inputs.node_test_files)
    if node_tests:
        commands.append(
            ("node", "--import", "./scripts/frontend-test-bootstrap.mjs", "--test", *node_tests)
        )
    return tuple(commands)


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
    discovered_tests = test_commands() if stage in {"test", "check"} else ()
    stages: dict[str, tuple[Command, ...]] = {
        "format": FORMAT_WRITE_COMMANDS if write else FORMAT_CHECK_COMMANDS,
        "lint": LINT_COMMANDS,
        "architecture": ARCHITECTURE_COMMANDS,
        "styles": STYLE_COMMANDS,
        "typecheck": TYPECHECK_COMMANDS,
        "compile": compile_commands(),
        "test": discovered_tests,
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
    try:
        commands = commands_for(stage, write=write)
    except OnboardingConfigurationError as exc:
        print(f"error: feature quality discovery failed: {exc}", file=sys.stderr)
        return 2
    for command in commands:
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
