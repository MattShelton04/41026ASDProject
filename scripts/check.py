"""Run composable deterministic quality checks from the repository root."""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
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
    "ai-services/mcp-server/tests",
    "ai-services/rag-server/tests",
    "ai-services/multi-agent-server/tests",
    "shared/tool-runtime/tests",
    "scripts/tests",
)
JAVASCRIPT_SOURCE_ROOTS = (
    REPOSITORY_ROOT / "shared" / "frontend",
    REPOSITORY_ROOT / "scripts",
    *sorted(REPOSITORY_ROOT.glob("student-*/frontend")),
)

JAVASCRIPT_SUFFIXES = frozenset({".js", ".mjs", ".cjs"})
JAVASCRIPT_EXCLUDED_DIRECTORIES = frozenset({"vendor", "node_modules", "__pycache__"})

Command = tuple[str, ...]

JOBS_ENVIRONMENT = "PROPERTYSCOPE_CHECK_JOBS"
FORCE_ENVIRONMENT = "PROPERTYSCOPE_CHECK_FORCE"
MAX_PYTEST_WORKERS = 8
XDIST_MIN_MODULES = 20
HEARTBEAT_SECONDS = 60.0
DISPLAY_WIDTH = 110
# Kept in the Git common directory: shared by every worktree of this clone, never committed.
PASSED_TREES_FILE = Path("propertyscope-check") / "passed-trees"
PASSED_TREES_LIMIT = 50

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
        "ai-services/mcp-server/src/mcp_server",
        "ai-services/rag-server/src/rag_server",
        "ai-services/multi-agent-server/src/multi_agent_server",
        "shared/tool-runtime/src/shared_tool_runtime",
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
        "scripts/visual",
        "scripts/devtools",
        "scripts/security",
        "scripts/capture_local_deployment.py",
        "scripts/check.py",
        "scripts/collect_ci_evidence.py",
        "scripts/cloud_deployment_report.py",
        "scripts/cloud_smoke.py",
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
    "--cov=shared_tool_runtime",
    "--cov=mcp_server",
    "--cov=rag_server",
    "--cov=multi_agent_server",
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
    node_tests = (*shared_frontend_tests(), *feature_inputs.node_test_files)
    if node_tests:
        commands.append(
            ("node", "--import", "./scripts/frontend-test-bootstrap.mjs", "--test", *node_tests)
        )
    return tuple(commands)


def _javascript_paths(roots: Sequence[Path]) -> tuple[str, ...]:
    paths: set[str] = set()
    for root in roots:
        for directory, children, files in root.walk():
            children[:] = sorted(
                name for name in children if name not in JAVASCRIPT_EXCLUDED_DIRECTORIES
            )
            for name in files:
                path = directory / name
                if path.suffix in JAVASCRIPT_SUFFIXES:
                    paths.add(path.relative_to(REPOSITORY_ROOT).as_posix())
    return tuple(sorted(paths))


def javascript_sources() -> tuple[str, ...]:
    """Discover first-party browser and tooling modules without dependency trees."""
    return _javascript_paths(JAVASCRIPT_SOURCE_ROOTS)


def shared_frontend_tests() -> tuple[str, ...]:
    """Automatically include Shared behavior tests; feature tests remain manifest-owned."""
    return tuple(
        path
        for path in _javascript_paths((REPOSITORY_ROOT / "shared" / "frontend",))
        if Path(path).stem.endswith(".test")
    )


def compile_commands() -> tuple[Command, ...]:
    """Build dependency-free JavaScript syntax checks for every first-party module."""
    return tuple(("node", "--check", source) for source in javascript_sources())


def commands_for(stage: str, *, write: bool = False) -> tuple[Command, ...]:
    """Return the commands for one public quality stage."""
    if stage == "check":
        return tuple(
            command
            for name in ("format", "lint", "architecture", "styles", "typecheck", "compile", "test")
            for command in commands_for(name)
        )
    if stage == "test":
        return test_commands()
    if stage == "compile":
        return compile_commands()
    stages: dict[str, tuple[Command, ...]] = {
        "format": FORMAT_WRITE_COMMANDS if write else FORMAT_CHECK_COMMANDS,
        "lint": LINT_COMMANDS,
        "architecture": ARCHITECTURE_COMMANDS,
        "styles": STYLE_COMMANDS,
        "typecheck": TYPECHECK_COMMANDS,
    }
    return stages[stage]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a deterministic repository quality stage (default: check)."
    )
    parser.add_argument(
        "--jobs",
        type=_positive_integer,
        help=(
            f"Commands to run at once (default: {JOBS_ENVIRONMENT} or the CPU count); "
            "1 runs them one at a time with live output and no pytest-xdist workers"
        ),
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
    commands.add_parser(
        "pre-push",
        help="Run the full check unless the pushed commit's tree already passed it",
    )
    return parser


def _positive_integer(value: str) -> int:
    if not value.isdigit() or int(value) < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return int(value)


@dataclass(frozen=True, slots=True)
class CommandResult:
    """The outcome of one quality command."""

    command: Command
    returncode: int
    seconds: float
    output: bytes = b""


def default_jobs() -> int:
    """Concurrent command slots: ``PROPERTYSCOPE_CHECK_JOBS`` or the logical CPU count."""
    configured = os.environ.get(JOBS_ENVIRONMENT, "").strip()
    if configured.isdigit() and int(configured) > 0:
        return int(configured)
    return max(1, os.cpu_count() or 1)


def _is_pytest(command: Command) -> bool:
    return command[1:3] == ("-m", "pytest")


def count_test_modules(command: Command) -> int:
    """Count the test modules a pytest command collects (e2e suites are never collected)."""
    return sum(
        1
        for argument in command[3:]
        if not argument.startswith("-")
        for path in (REPOSITORY_ROOT / argument).rglob("test_*.py")
        if "e2e" not in path.relative_to(REPOSITORY_ROOT).parts
    )


def pytest_worker_plan(commands: Sequence[Command], jobs: int) -> tuple[int, ...]:
    """Share ``jobs`` xdist workers among the large pytest commands by test-module count.

    Suites below ``XDIST_MIN_MODULES`` stay in-process (0), where worker start-up would cost more
    than it saves; so does everything when ``jobs`` is 1.
    """
    sizes = [
        count_test_modules(command) if jobs > 1 and _is_pytest(command) else 0
        for command in commands
    ]
    large = [size if size >= XDIST_MIN_MODULES else 0 for size in sizes]
    total = sum(large)
    return tuple(
        max(2, min(MAX_PYTEST_WORKERS, jobs, round(jobs * size / total))) if size else 0
        for size in large
    )


def with_pytest_workers(command: Command, workers: int) -> Command:
    """Distribute one pytest command over xdist workers, keeping its checks unchanged.

    Every worker collects the same deterministic test IDs, and pytest-cov combines coverage from
    all workers before its report and ``fail_under`` threshold are applied.
    """
    if workers < 2 or not _is_pytest(command):
        return command
    return (*command[:3], "-n", str(workers), "--dist", "worksteal", *command[3:])


def _display(command: Command) -> str:
    shown = ("python", *command[1:]) if command[0] == sys.executable else command
    text = shlex.join(shown)
    return text if len(text) <= DISPLAY_WIDTH else f"{text[: DISPLAY_WIDTH - 3]}..."


def _environment(command: Command, scratch: Path, index: int) -> dict[str, str] | None:
    """Give each pytest run a private coverage data file so concurrent runs cannot mix data."""
    if not _is_pytest(command):
        return None
    directory = scratch / f"coverage-{index}"
    directory.mkdir()
    return {**os.environ, "COVERAGE_FILE": str(directory / ".coverage")}


def _missing_executable(command: Command) -> str:
    return f"error: {command[0]} is not available. See README.md for prerequisites."


def _run_streaming(commands: Sequence[Command], scratch: Path) -> tuple[int, list[CommandResult]]:
    """Run commands one at a time with live output, stopping at the first failure."""
    results: list[CommandResult] = []
    for index, command in enumerate(commands):
        print(f"\n> {shlex.join(command)}", flush=True)
        started = time.perf_counter()
        try:
            completed = subprocess.run(  # noqa: S603 - fixed quality-gate argv, no shell
                command, cwd=REPOSITORY_ROOT, env=_environment(command, scratch, index), check=False
            )
        except FileNotFoundError:
            print(_missing_executable(command), file=sys.stderr)
            return 2, results
        results.append(CommandResult(command, completed.returncode, time.perf_counter() - started))
        if completed.returncode:
            return completed.returncode, results
    return 0, results


def _run_captured(command: Command, environment: Mapping[str, str] | None) -> CommandResult:
    started = time.perf_counter()
    try:
        completed = subprocess.run(  # noqa: S603 - fixed quality-gate argv, no shell
            command,
            cwd=REPOSITORY_ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
    except FileNotFoundError:
        message = f"{_missing_executable(command)}\n".encode()
        return CommandResult(command, 2, time.perf_counter() - started, message)
    return CommandResult(
        command, completed.returncode, time.perf_counter() - started, completed.stdout
    )


def _priority(command: Command) -> int:
    """Start the long-running commands first so they overlap the many short ones."""
    if _is_pytest(command):
        return 0
    if command[1:3] == ("-m", "mypy") or command[1:2] == ("--import",):
        return 1
    return 2


def _write_block(result: CommandResult) -> None:
    status = "ok" if result.returncode == 0 else f"FAILED (exit {result.returncode})"
    print(f"\n> {shlex.join(result.command)}  [{status}, {result.seconds:.1f}s]", flush=True)
    if result.output:
        sys.stdout.buffer.write(result.output)
        if not result.output.endswith(b"\n"):
            sys.stdout.buffer.write(b"\n")
        sys.stdout.buffer.flush()


def _run_concurrently(
    commands: Sequence[Command],
    jobs: int,
    scratch: Path,
    *,
    heartbeat_seconds: float = HEARTBEAT_SECONDS,
) -> tuple[int, list[CommandResult]]:
    """Run every command, at most ``jobs`` at once, printing each one's output as one block.

    Blocks appear as commands finish, never interleaved. All commands run to completion so one
    run reports every failure; the exit status is the first failure in declared order.
    """
    running: dict[int, float] = {}
    lock = threading.Lock()

    def run(index: int, environment: dict[str, str] | None) -> CommandResult:
        with lock:
            running[index] = time.perf_counter()
        try:
            return _run_captured(commands[index], environment)
        finally:
            with lock:
                running.pop(index, None)

    order = sorted(range(len(commands)), key=lambda index: (_priority(commands[index]), index))
    results: dict[int, CommandResult] = {}
    with ThreadPoolExecutor(max_workers=jobs, thread_name_prefix="check") as pool:
        futures: dict[Future[CommandResult], int] = {
            pool.submit(run, index, _environment(commands[index], scratch, index)): index
            for index in order
        }
        pending: set[Future[CommandResult]] = set(futures)
        while pending:
            done, pending = wait(pending, timeout=heartbeat_seconds, return_when=FIRST_COMPLETED)
            for future in sorted(done, key=futures.__getitem__):
                result = future.result()
                results[futures[future]] = result
                _write_block(result)
            if not done:
                now = time.perf_counter()
                with lock:
                    active = sorted(running.items())
                for index, started in active:
                    print(
                        f"... still running ({now - started:.0f}s): {_display(commands[index])}",
                        flush=True,
                    )
    ordered = [results[index] for index in range(len(commands))]
    failure = next((result.returncode for result in ordered if result.returncode), 0)
    return failure, ordered


def _print_summary(results: Sequence[CommandResult], *, jobs: int, seconds: float) -> None:
    if len(results) < 2:
        return
    print(f"\nQuality gate summary ({len(results)} commands, jobs={jobs}, {seconds:.1f}s wall):")
    compiled = [result for result in results if result.command[:2] == ("node", "--check")]
    for result in results:
        if len(compiled) > 1 and result in compiled:
            if result is compiled[0]:
                status = "FAILED" if any(item.returncode for item in compiled) else "ok"
                total = sum(item.seconds for item in compiled)
                print(f"  {status:<7}{total:7.1f}s  node --check ({len(compiled)} files, summed)")
            continue
        status = "ok" if result.returncode == 0 else "FAILED"
        print(f"  {status:<7}{result.seconds:7.1f}s  {_display(result.command)}")


def run_commands(commands: Sequence[Command], *, jobs: int) -> int:
    """Run quality commands serially (``jobs == 1``) or concurrently, then print timings."""
    started = time.perf_counter()
    plan = pytest_worker_plan(commands, jobs)
    commands = tuple(map(with_pytest_workers, commands, plan))
    with tempfile.TemporaryDirectory(prefix="propertyscope-check-") as directory:
        if jobs < 2 or len(commands) < 2:
            returncode, results = _run_streaming(commands, Path(directory))
        else:
            returncode, results = _run_concurrently(commands, jobs, Path(directory))
    _print_summary(results, jobs=jobs, seconds=time.perf_counter() - started)
    return returncode


def _git(*arguments: str, environment: Mapping[str, str] | None = None) -> str | None:
    try:
        completed = subprocess.run(  # noqa: S603 - fixed git argv, no shell
            ("git", *arguments),  # noqa: S607 - git is resolved from PATH like every hook
            cwd=REPOSITORY_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    return completed.stdout.strip() if completed.returncode == 0 else None


def working_tree_hash() -> str | None:
    """Hash the working tree exactly as ``git add --all`` would commit it.

    A private copy of the index is used, so the real index and staged changes are untouched.
    Ignored files (caches, ``.env``, local databases) are excluded, as they are from commits.
    """
    index = _git("rev-parse", "--git-path", "index")
    with tempfile.TemporaryDirectory(prefix="propertyscope-check-index-") as directory:
        private_index = Path(directory) / "index"
        if index and (REPOSITORY_ROOT / index).is_file():
            shutil.copyfile(REPOSITORY_ROOT / index, private_index)
        environment = {**os.environ, "GIT_INDEX_FILE": str(private_index)}
        if _git("add", "--all", environment=environment) is None:
            return None
        return _git("write-tree", environment=environment)


def _passed_trees_path() -> Path | None:
    common = _git("rev-parse", "--git-common-dir")
    return REPOSITORY_ROOT / common / PASSED_TREES_FILE if common else None


def passed_trees() -> tuple[str, ...]:
    """Return the trees on which the full gate passed in this clone, oldest first."""
    path = _passed_trees_path()
    if path is None or not path.is_file():
        return ()
    lines = path.read_text(encoding="utf-8").splitlines()
    return tuple(line.split()[0] for line in lines if line.strip())


def record_passed_tree(tree: str, *, now: Callable[[], float] = time.time) -> None:
    """Remember that the full gate passed on ``tree`` (bounded, newest last)."""
    path = _passed_trees_path()
    if path is None:
        return
    kept = [item for item in passed_trees() if item != tree][-(PASSED_TREES_LIMIT - 1) :]
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [*(f"{item}\n" for item in kept), f"{tree} {int(now())}\n"]
    path.write_text("".join(lines), encoding="utf-8")


def run_full_gate(*, jobs: int) -> int:
    """Run every stage; on success record the checked working tree for the pre-push hook."""
    tree = working_tree_hash()
    returncode = run_commands(commands_for("check"), jobs=jobs)
    if returncode or tree is None:
        return returncode
    if working_tree_hash() == tree:
        record_passed_tree(tree)
        print(f"\nFull gate passed on tree {tree[:12]}; pushing a commit with this tree skips it.")
    else:
        print("\nFull gate passed, but files changed while it ran, so the result is not recorded.")
    return returncode


def pre_push(*, jobs: int) -> int:
    """Skip the full gate when the pushed commit's tree already passed it; else run it."""
    target = os.environ.get("PRE_COMMIT_TO_REF") or "HEAD"
    tree = _git("rev-parse", f"{target}^{{tree}}")
    if tree and not os.environ.get(FORCE_ENVIRONMENT) and tree in passed_trees():
        print(
            f"Full gate already passed on the pushed tree {tree[:12]}; skipping it. "
            f"Set {FORCE_ENVIRONMENT}=1 to run it again."
        )
        return 0
    returncode = run_full_gate(jobs=jobs)
    if returncode == 0 and tree and working_tree_hash() != tree:
        print(
            "warning: the gate checked your working tree, which differs from the pushed commit; "
            "CI checks the pushed commit."
        )
    return returncode


def main(argv: Sequence[str] | None = None) -> int:
    """Run the selected checks; multi-command stages run their commands concurrently."""
    arguments = _parser().parse_args(argv)
    stage = arguments.stage or "check"
    write = bool(getattr(arguments, "write", False))
    jobs = arguments.jobs if arguments.jobs is not None else default_jobs()
    try:
        if stage == "pre-push":
            return pre_push(jobs=jobs)
        if stage == "check":
            return run_full_gate(jobs=jobs)
        commands = commands_for(stage, write=write)
    except OnboardingConfigurationError as exc:
        print(f"error: feature quality discovery failed: {exc}", file=sys.stderr)
        return 2
    return run_commands(commands, jobs=jobs)


if __name__ == "__main__":
    raise SystemExit(main())
