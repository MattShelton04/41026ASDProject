"""Tests for the composable repository quality command."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest
from scripts import check
from scripts.onboarding import (
    FeatureQualityCheck,
    FeatureQualityInputs,
    OnboardingConfigurationError,
)


def test_javascript_compile_sources_are_first_party_and_repository_relative() -> None:
    sources = check.javascript_sources()

    assert "shared/frontend/app.js" in sources
    for student in range(1, 6):
        assert f"student-{student}/frontend/app.js" in sources
    assert all(not source.startswith(("/", "C:/", "C:\\")) for source in sources)
    assert all("/vendor/" not in source for source in sources)
    assert sources == tuple(sorted(set(sources)))
    assert "scripts/frontend-test-loader.mjs" in sources


def test_module_discovery_includes_supported_sources_and_shared_tests_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    files = (
        "shared/frontend/new.test.mjs",
        "shared/frontend/nested/module.cjs",
        "shared/frontend/classic.test.js",
        "shared/frontend/common.test.cjs",
        "shared/frontend/vendor/ignored.test.mjs",
        "shared/frontend/node_modules/ignored.js",
        "shared/frontend/readme.md",
        "student-1/frontend/unregistered.test.mjs",
        "scripts/tool.mjs",
    )
    for name in files:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    monkeypatch.setattr(check, "REPOSITORY_ROOT", tmp_path)
    roots = tuple(tmp_path / name for name in ("shared/frontend", "student-1/frontend", "scripts"))
    monkeypatch.setattr(check, "JAVASCRIPT_SOURCE_ROOTS", (*roots, roots[0]))
    monkeypatch.setattr(
        check, "discover_quality_inputs", lambda _root: FeatureQualityInputs(features=())
    )
    assert check.javascript_sources() == tuple(
        sorted((files[0], files[1], files[2], files[3], files[7], files[8]))
    )
    assert check.shared_frontend_tests() == tuple(sorted((files[0], files[2], files[3])))
    node_command = check.test_commands()[-1]
    assert files[0] in node_command
    assert files[7] not in node_command


@pytest.mark.parametrize("stage", ["format", "lint", "architecture", "styles", "typecheck"])
def test_static_stages_do_not_discover_unrelated_inputs(
    stage: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected(*_args: object) -> None:
        pytest.fail("unrelated discovery was invoked")

    monkeypatch.setattr(check, "compile_commands", unexpected)
    monkeypatch.setattr(check, "test_commands", unexpected)
    assert check.commands_for(stage)


def test_named_stages_are_composable_and_check_preserves_order() -> None:
    expected = tuple(
        command
        for stage in (
            "format",
            "lint",
            "architecture",
            "styles",
            "typecheck",
            "compile",
            "test",
        )
        for command in check.commands_for(stage)
    )

    assert check.commands_for("check") == expected
    assert "--check" in check.commands_for("format")[0]
    assert "--check" not in check.commands_for("format", write=True)[0]
    assert "shared/consumer-protocol/tests" in check.CORE_TEST_PATHS
    assert "--cov=shared_consumer_protocol" in check.commands_for("test")[0]
    assert all(command[:2] == ("node", "--check") for command in check.compile_commands())
    assert (check.sys.executable, "scripts/validate_workspace_packaging.py") in (
        check.commands_for("architecture")
    )
    assert (check.sys.executable, "scripts/generate_deployment.py", "--check") in (
        check.commands_for("architecture")
    )


def test_feature_quality_inputs_are_added_from_enabled_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        check,
        "discover_quality_inputs",
        lambda _root: FeatureQualityInputs(
            features=(
                FeatureQualityCheck(
                    feature_key="student-3-example",
                    owner="student-3",
                    python_test_paths=("student-3/tests",),
                    node_test_files=("student-3/tests/frontend.test.mjs",),
                    coverage_packages=("student_3_feature",),
                    coverage_fail_under=72,
                ),
            )
        ),
    )

    commands = check.commands_for("test")

    assert commands[1][-1] == "student-3/tests"
    assert "--cov=student_3_feature" in commands[1]
    assert "--cov-fail-under=72" in commands[1]
    assert "--ignore-glob=*/tests/e2e/*" in commands[1]
    assert commands[2][-1] == "student-3/tests/frontend.test.mjs"
    assert "student-1/tests" not in commands[1]


def test_discovery_failure_is_reported_before_running_commands(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        check,
        "commands_for",
        lambda _stage, *, write=False: (_ for _ in ()).throw(
            OnboardingConfigurationError("invalid selection")
        ),
    )

    assert check.main(["test"]) == 2
    assert "feature quality discovery failed: invalid selection" in capsys.readouterr().err


def _completed(command: Sequence[str], returncode: int) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess(list(command), returncode, stdout=b"")


def test_serial_run_streams_and_forwards_the_first_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []
    commands = (("first",), ("second",), ("third",))
    monkeypatch.setattr(check, "commands_for", lambda _stage, *, write=False: commands)

    def run(command: Sequence[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(tuple(command))
        return _completed(command, 7 if command[0] == "second" else 0)

    monkeypatch.setattr(check.subprocess, "run", run)

    assert check.main(["--jobs", "1", "lint"]) == 7
    assert calls == [("first",), ("second",)]


def test_concurrent_run_finishes_every_command_and_returns_the_first_declared_failure(
    monkeypatch: pytest.MonkeyPatch, capsysbinary: pytest.CaptureFixture[bytes]
) -> None:
    commands = (("first",), ("second",), ("third",), ("fourth",))
    codes = {"second": 3, "fourth": 5}
    monkeypatch.setattr(check, "commands_for", lambda _stage, *, write=False: commands)

    def run(command: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        assert kwargs["stdout"] is subprocess.PIPE
        assert kwargs["stderr"] is subprocess.STDOUT
        output = f"output of {command[0]}\n".encode()
        return subprocess.CompletedProcess(list(command), codes.get(command[0], 0), output)

    monkeypatch.setattr(check.subprocess, "run", run)

    assert check.main(["--jobs", "3", "test"]) == 3
    printed = capsysbinary.readouterr().out.decode()
    for name in ("first", "second", "third", "fourth"):
        header = printed.index(f"\n> {name}  [") + 1
        assert printed.index(f"output of {name}\n") == printed.index("\n", header) + 1
    assert "> second  [FAILED (exit 3)" in printed
    summary = printed[printed.index("Quality gate summary (4 commands, jobs=3") :]
    rows = [line.split()[0] for line in summary.splitlines()[1:]]
    assert rows == ["ok", "FAILED", "ok", "FAILED"]


def test_missing_executable_is_reported_in_both_modes(
    monkeypatch: pytest.MonkeyPatch, capsysbinary: pytest.CaptureFixture[bytes]
) -> None:
    monkeypatch.setattr(
        check, "commands_for", lambda _stage, *, write=False: (("absent-tool",), ("other",))
    )

    def run(command: Sequence[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        if command[0] == "absent-tool":
            raise FileNotFoundError(command[0])
        return _completed(command, 0)

    monkeypatch.setattr(check.subprocess, "run", run)

    assert check.main(["--jobs", "1", "test"]) == 2
    assert check.main(["--jobs", "2", "test"]) == 2
    captured = capsysbinary.readouterr()
    message = b"error: absent-tool is not available"
    assert message in captured.err
    assert message in captured.out


def test_pytest_commands_gain_xdist_workers_without_changing_their_checks() -> None:
    shared = check.SHARED_TEST_COMMAND

    distributed = check.with_pytest_workers(shared, 4)

    assert distributed[:7] == (*shared[:3], "-n", "4", "--dist", "worksteal")
    assert distributed[7:] == shared[3:]
    assert check.with_pytest_workers(shared, 0) == shared
    assert check.with_pytest_workers(check.LINT_COMMANDS[0], 4) == check.LINT_COMMANDS[0]


def test_workers_are_shared_by_large_suites_and_small_suites_stay_in_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def suite(name: str, modules: int) -> tuple[str, ...]:
        for number in range(modules):
            path = tmp_path / name / "tests" / f"test_{number}.py"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
        return (check.sys.executable, "-m", "pytest", f"--cov={name}", f"{name}/tests")

    small = suite("small", 1)
    for name in ("small/tests/e2e/test_browser.py", "small/tests/helper.py"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("", encoding="utf-8")
    larger = suite("larger", 3 * check.XDIST_MIN_MODULES)
    large = suite("large", check.XDIST_MIN_MODULES)
    monkeypatch.setattr(check, "REPOSITORY_ROOT", tmp_path)
    commands = (*check.LINT_COMMANDS, small, larger, large)

    assert check.count_test_modules(small) == 1
    assert check.pytest_worker_plan(commands, 1) == (0, 0, 0, 0)
    assert check.pytest_worker_plan(commands, 4) == (0, 0, 3, 2)
    assert check.pytest_worker_plan(commands, 12) == (0, 0, 8, 3)
    assert check.pytest_worker_plan((small, large), 64) == (0, check.MAX_PYTEST_WORKERS)


def test_serial_jobs_disable_xdist(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        check, "commands_for", lambda _stage, *, write=False: (check.SHARED_TEST_COMMAND,)
    )

    def run(command: Sequence[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        seen.append(tuple(command))
        return _completed(command, 0)

    monkeypatch.setattr(check.subprocess, "run", run)

    assert check.main(["--jobs", "1", "test"]) == 0
    assert seen == [check.SHARED_TEST_COMMAND]


def test_each_pytest_run_gets_a_private_coverage_file(tmp_path: Path) -> None:
    first = check._environment(check.SHARED_TEST_COMMAND, tmp_path, 0)
    second = check._environment(check.SHARED_TEST_COMMAND, tmp_path, 1)

    assert first is not None
    assert second is not None
    assert first["COVERAGE_FILE"] != second["COVERAGE_FILE"]
    assert Path(first["COVERAGE_FILE"]).parent.is_dir()
    assert check._environment(check.LINT_COMMANDS[0], tmp_path, 2) is None


def test_long_running_commands_start_first() -> None:
    commands = (
        *check.FORMAT_CHECK_COMMANDS,
        *check.TYPECHECK_COMMANDS,
        ("node", "--import", "./scripts/frontend-test-bootstrap.mjs", "--test", "a.test.mjs"),
        check.SHARED_TEST_COMMAND,
    )

    assert sorted(commands, key=check._priority)[0] == check.SHARED_TEST_COMMAND
    assert [check._priority(command) for command in commands] == [2, 1, 1, 0]


def test_jobs_come_from_the_option_environment_or_cpu_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(check.JOBS_ENVIRONMENT, "3")
    assert check.default_jobs() == 3
    monkeypatch.setenv(check.JOBS_ENVIRONMENT, "not-a-number")
    monkeypatch.setattr(check.os, "cpu_count", lambda: None)
    assert check.default_jobs() == 1
    with pytest.raises(SystemExit):
        check._parser().parse_args(["--jobs", "0"])


def test_hook_git_environment_never_reaches_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in check.GIT_REPOSITORY_ENVIRONMENT:
        monkeypatch.setenv(name, str(tmp_path / "hook-repository"))
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "0")
    seen: list[dict[str, str]] = []
    monkeypatch.setattr(
        check, "commands_for", lambda _stage, *, write=False: (check.SHARED_TEST_COMMAND, ("x",))
    )

    def run(command: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        environment = kwargs["env"]
        seen.append(dict(environment) if isinstance(environment, dict) else dict(check.os.environ))
        return _completed(command, 0)

    monkeypatch.setattr(check.subprocess, "run", run)

    assert check.main(["--jobs", "2", "test"]) == 0
    assert len(seen) == 2
    for environment in seen:
        assert not set(check.GIT_REPOSITORY_ENVIRONMENT) & set(environment)
        assert environment["GIT_TERMINAL_PROMPT"] == "0"


def test_default_stage_is_the_full_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    stages: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        check,
        "commands_for",
        lambda stage, *, write=False: stages.append((stage, write)) or (),
    )
    monkeypatch.setattr(check, "working_tree_hash", lambda: None)

    assert check.main([]) == 0
    assert stages == [("check", False)]


@pytest.fixture
def git_repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A tiny real Git repository stands in for the checkout."""
    for arguments in (
        ("init", "--quiet"),
        ("config", "user.name", "Check test"),
        ("config", "user.email", "check-test@example.invalid"),
        ("config", "core.autocrlf", "false"),
    ):
        subprocess.run(  # noqa: S603 - fixed git argv, no shell
            ("git", "-C", str(tmp_path), *arguments),  # noqa: S607 - git from the developer PATH
            check=True,
        )
    (tmp_path / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (tmp_path / "tracked.txt").write_text("one\n", encoding="utf-8")
    monkeypatch.setattr(check, "REPOSITORY_ROOT", tmp_path)
    return tmp_path


def test_working_tree_hash_matches_a_commit_of_everything_and_leaves_the_index_alone(
    git_repository: Path,
) -> None:
    assert check._git("add", ".gitignore") == ""
    staged = check._git("diff", "--cached", "--name-only")

    tree = check.working_tree_hash()

    assert tree
    assert check._git("diff", "--cached", "--name-only") == staged
    (git_repository / "ignored.txt").write_text("not part of a commit\n", encoding="utf-8")
    assert check.working_tree_hash() == tree
    assert check._git("add", "--all") == ""
    assert check._git("commit", "--quiet", "-m", "snapshot") == ""
    assert check._git("rev-parse", "HEAD^{tree}") == tree
    (git_repository / "tracked.txt").write_text("two\n", encoding="utf-8")
    assert check.working_tree_hash() != tree


def test_passed_trees_are_bounded_and_newest_last(
    git_repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(check, "PASSED_TREES_LIMIT", 6)
    assert check.passed_trees() == ()

    for number in range(check.PASSED_TREES_LIMIT + 2):
        check.record_passed_tree(f"tree-{number}", now=lambda: 1.0)
    check.record_passed_tree("tree-5", now=lambda: 2.0)

    trees = check.passed_trees()
    assert len(trees) == check.PASSED_TREES_LIMIT
    assert trees[-1] == "tree-5"
    assert trees.count("tree-5") == 1
    assert "tree-0" not in trees
    assert (git_repository / ".git" / check.PASSED_TREES_FILE).is_file()


@pytest.mark.parametrize(("before", "after", "recorded"), [("a", "a", ["a"]), ("a", "b", [])])
def test_full_gate_records_only_an_unchanged_passing_tree(
    monkeypatch: pytest.MonkeyPatch, before: str, after: str, recorded: list[str]
) -> None:
    hashes = iter((before, after))
    saved: list[str] = []
    monkeypatch.setattr(check, "working_tree_hash", lambda: next(hashes))
    monkeypatch.setattr(check, "commands_for", lambda _stage, *, write=False: ())
    monkeypatch.setattr(check, "record_passed_tree", saved.append)

    assert check.main(["check"]) == 0
    assert saved == recorded


def test_failing_full_gate_records_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    saved: list[str] = []
    monkeypatch.setattr(check, "working_tree_hash", lambda: "a")
    monkeypatch.setattr(check, "commands_for", lambda _stage, *, write=False: (("bad",),))
    monkeypatch.setattr(check.subprocess, "run", lambda command, **_kwargs: _completed(command, 1))
    monkeypatch.setattr(check, "record_passed_tree", saved.append)

    assert check.main(["check"]) == 1
    assert saved == []


def test_pre_push_skips_a_tree_that_already_passed(
    git_repository: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert check._git("add", "--all") == ""
    assert check._git("commit", "--quiet", "-m", "snapshot") == ""
    head = check._git("rev-parse", "HEAD")
    tree = check._git("rev-parse", "HEAD^{tree}")
    assert head
    assert tree
    runs: list[int] = []

    def full_gate(*, jobs: int) -> int:
        runs.append(jobs)
        return 0

    monkeypatch.setattr(check, "run_full_gate", full_gate)
    monkeypatch.setenv("PRE_COMMIT_TO_REF", head)
    monkeypatch.delenv(check.FORCE_ENVIRONMENT, raising=False)

    assert check.main(["--jobs", "2", "pre-push"]) == 0
    assert runs == [2]

    check.record_passed_tree(tree)
    assert check.main(["pre-push"]) == 0
    assert runs == [2]
    assert "already passed on the pushed tree" in capsys.readouterr().out

    monkeypatch.setenv(check.FORCE_ENVIRONMENT, "1")
    assert check.main(["--jobs", "2", "pre-push"]) == 0
    assert runs == [2, 2]


def test_pre_push_warns_when_the_checked_tree_is_not_the_pushed_one(
    git_repository: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert check._git("add", "--all") == ""
    assert check._git("commit", "--quiet", "-m", "snapshot") == ""
    (git_repository / "tracked.txt").write_text("uncommitted\n", encoding="utf-8")
    monkeypatch.delenv("PRE_COMMIT_TO_REF", raising=False)
    monkeypatch.setattr(check, "run_full_gate", lambda *, jobs: 0)

    assert check.main(["pre-push"]) == 0
    assert "differs from the pushed commit" in capsys.readouterr().out
    monkeypatch.setattr(check, "run_full_gate", lambda *, jobs: 4)
    assert check.main(["pre-push"]) == 4
