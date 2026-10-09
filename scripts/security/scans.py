"""Run Ruff, detect-secrets and pip-audit with bounded time and repository-relative output."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from importlib import metadata
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from scripts.security.policy import (
    BASELINE_NAME,
    DETECT_SECRETS_EXCLUDE_FILES,
    DETECT_SECRETS_EXCLUDE_LINES,
    RuffPolicy,
    to_posix,
)
from scripts.security.report import PipAuditResult, RawRuffFinding

RUFF_TIMEOUT_SECONDS = 300
DETECT_SECRETS_TIMEOUT_SECONDS = 600
UV_EXPORT_TIMEOUT_SECONDS = 120
PIP_AUDIT_TIMEOUT_SECONDS = 300
PIP_AUDIT_REQUEST_TIMEOUT_SECONDS = 20

OFFLINE_HINT = (
    "pip-audit needs network access to the PyPI vulnerability service. Re-run when online; to "
    "commit while offline, skip only this hook with `SKIP=security-pip-audit git commit ...` and "
    "let CI run the audit."
)


class ScanError(RuntimeError):
    """A scanner could not run to completion."""


def python_tool(module: str, *arguments: str) -> tuple[str, ...]:
    """Run a tool from the locked environment, independent of PATH."""
    return (sys.executable, "-m", module, *arguments)


def display(command: Sequence[str]) -> str:
    """Show a command as a developer would type it inside `uv run`."""
    parts = list(command)
    if parts[:2] == [sys.executable, "-m"]:
        parts = [parts[2].replace("_", "-"), *parts[3:]]
    return " ".join(part if " " not in part else f"'{part}'" for part in parts)


def _run(
    command: Sequence[str], root: Path, timeout: float, *, check: bool = False
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(  # noqa: S603 - fixed tool argv, no shell
            list(command),
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ScanError(f"`{display(command)}` timed out after {timeout:.0f} s") from exc
    except FileNotFoundError as exc:
        raise ScanError(f"`{command[0]}` is not available") from exc
    if check and completed.returncode != 0:
        raise ScanError(
            f"`{display(command)}` failed with exit code {completed.returncode}: "
            f"{(completed.stderr or completed.stdout).strip()[-2000:]}"
        )
    return completed


# --------------------------------------------------------------------------------------------
# Ruff
# --------------------------------------------------------------------------------------------


def ruff_gate_command() -> tuple[str, ...]:
    return python_tool(
        "ruff", "check", ".", "--select", "S", "--output-format", "json", "--exit-zero"
    )


def ruff_audit_command(policy: RuffPolicy) -> tuple[str, ...]:
    return python_tool(
        "ruff",
        "check",
        ".",
        "--select",
        "S",
        "--ignore-noqa",
        *policy.isolated_arguments(),
        "--output-format",
        "json",
        "--exit-zero",
        "--no-cache",
    )


def run_ruff(root: Path, policy: RuffPolicy) -> tuple[list[RawRuffFinding], list[RawRuffFinding]]:
    """Return the configured (gate) findings and the audit findings that ignore exceptions."""

    def relative(filename: str) -> str:
        path = Path(filename)
        return str(path.relative_to(root)) if path.is_absolute() else filename

    results: list[list[RawRuffFinding]] = []
    for command in (ruff_gate_command(), ruff_audit_command(policy)):
        completed = _run(command, root, RUFF_TIMEOUT_SECONDS, check=True)
        items = json.loads(completed.stdout or "[]")
        results.append([RawRuffFinding.from_ruff(item, relative) for item in items])
    return results[0], results[1]


# --------------------------------------------------------------------------------------------
# detect-secrets
# --------------------------------------------------------------------------------------------


def detect_secrets_scan_arguments() -> tuple[str, ...]:
    arguments: list[str] = ["scan"]
    for pattern in DETECT_SECRETS_EXCLUDE_FILES:
        arguments.extend(("--exclude-files", pattern))
    for pattern in DETECT_SECRETS_EXCLUDE_LINES:
        arguments.extend(("--exclude-lines", pattern))
    return tuple(arguments)


def normalise_baseline(document: dict[str, Any]) -> dict[str, Any]:
    """Store POSIX paths (detect-secrets writes `\\` on Windows) in a stable order."""
    results: dict[str, list[dict[str, Any]]] = {}
    for path, entries in document.get("results", {}).items():
        posix = to_posix(path)
        merged = [*results.get(posix, []), *entries]
        for entry in merged:
            entry["filename"] = posix
        results[posix] = sorted(
            merged, key=lambda e: (e.get("line_number", 0), e["type"], e["hashed_secret"])
        )
    document["results"] = dict(sorted(results.items()))
    return document


def write_baseline(path: Path, document: dict[str, Any]) -> None:
    path.write_bytes((json.dumps(document, indent=2) + "\n").encode("utf-8"))


def refresh_baseline(root: Path) -> Path:
    """Create or update `.secrets.baseline`, keeping audit decisions, with POSIX paths."""
    baseline = root / BASELINE_NAME
    arguments = list(detect_secrets_scan_arguments())
    if baseline.exists():
        arguments.extend(("--baseline", BASELINE_NAME))
    completed = _run(
        python_tool("detect_secrets", *arguments), root, DETECT_SECRETS_TIMEOUT_SECONDS, check=True
    )
    document = (
        json.loads(baseline.read_text(encoding="utf-8"))
        if baseline.exists()
        else json.loads(completed.stdout)
    )
    write_baseline(baseline, normalise_baseline(document))
    return baseline


def run_detect_secrets(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Scan the tracked tree with the baseline's settings without modifying the baseline.

    Returns the committed baseline and the fresh scan, both with POSIX paths.
    """
    baseline_path = root / BASELINE_NAME
    if not baseline_path.exists():
        raise ScanError(f"{BASELINE_NAME} is missing; create it with `security baseline`")
    committed = normalise_baseline(json.loads(baseline_path.read_text(encoding="utf-8")))
    with TemporaryDirectory(prefix="propertyscope-secrets-") as directory:
        copy = Path(directory) / BASELINE_NAME
        shutil.copyfile(baseline_path, copy)
        _run(
            python_tool("detect_secrets", "scan", "--baseline", str(copy)),
            root,
            DETECT_SECRETS_TIMEOUT_SECONDS,
            check=True,
        )
        fresh = normalise_baseline(json.loads(copy.read_text(encoding="utf-8")))
    return committed, fresh


def detect_secrets_hook(root: Path, filenames: Sequence[str]) -> int:
    """Run the upstream pre-commit hook, then keep any baseline rewrite in POSIX form."""
    baseline = root / BASELINE_NAME
    before = baseline.read_bytes() if baseline.exists() else b""
    command = python_tool("detect_secrets.pre_commit_hook", "--baseline", BASELINE_NAME, *filenames)
    completed = subprocess.run(  # noqa: S603 - fixed tool argv and staged paths, no shell
        command, cwd=root, check=False, timeout=DETECT_SECRETS_TIMEOUT_SECONDS
    )
    if baseline.exists() and baseline.read_bytes() != before:
        write_baseline(baseline, normalise_baseline(json.loads(baseline.read_bytes())))
    return completed.returncode


# --------------------------------------------------------------------------------------------
# pip-audit
# --------------------------------------------------------------------------------------------


def uv_executable() -> str:
    uv = os.environ.get("UV") or shutil.which("uv")
    if not uv:
        raise ScanError("uv is not available on PATH")
    return uv


def export_command(output: Path) -> tuple[str, ...]:
    return (
        uv_executable(),
        "export",
        "--locked",
        "--all-packages",
        "--all-groups",
        "--no-emit-workspace",
        "--format",
        "requirements-txt",
        "--quiet",
        "--output-file",
        str(output),
    )


def pip_audit_command(
    requirements: Path, ignore_ids: Sequence[str], *, json_output: Path | None
) -> tuple[str, ...]:
    arguments = [
        "--requirement",
        str(requirements),
        "--disable-pip",
        "--progress-spinner",
        "off",
        "--timeout",
        str(PIP_AUDIT_REQUEST_TIMEOUT_SECONDS),
    ]
    for vuln_id in ignore_ids:
        arguments.extend(("--ignore-vuln", vuln_id))
    if json_output is not None:
        arguments.extend(("--format", "json", "--output", str(json_output)))
    return python_tool("pip_audit", *arguments)


def _looks_offline(output: str) -> bool:
    markers = ("ConnectionError", "Max retries exceeded", "NameResolutionError", "timed out")
    return any(marker in output for marker in markers)


def run_pip_audit(root: Path) -> PipAuditResult:
    """Audit every locked third-party package without applying accepted-risk ignores."""
    with TemporaryDirectory(prefix="propertyscope-pip-audit-") as directory:
        requirements = Path(directory) / "requirements.txt"
        output = Path(directory) / "pip-audit.json"
        try:
            _run(export_command(requirements), root, UV_EXPORT_TIMEOUT_SECONDS, check=True)
            completed = _run(
                pip_audit_command(requirements, (), json_output=output),
                root,
                PIP_AUDIT_TIMEOUT_SECONDS,
            )
        except ScanError as exc:
            return PipAuditResult(None, str(exc))
        if output.exists():
            data: Mapping[str, Any] = json.loads(output.read_text(encoding="utf-8"))
            return PipAuditResult(data)
        detail = (completed.stderr or completed.stdout).strip().splitlines()
        reason = (
            "offline or vulnerability service unreachable"
            if _looks_offline(completed.stderr + completed.stdout)
            else (detail[-1] if detail else f"exit code {completed.returncode}")
        )
        return PipAuditResult(None, reason)


def pip_audit_hook(root: Path, ignore_ids: Sequence[str]) -> int:
    """Pre-commit entry point: audit the lockfile with reviewed ignores, failing clearly."""
    with TemporaryDirectory(prefix="propertyscope-pip-audit-") as directory:
        requirements = Path(directory) / "requirements.txt"
        try:
            _run(export_command(requirements), root, UV_EXPORT_TIMEOUT_SECONDS, check=True)
        except ScanError as exc:
            print(f"security-pip-audit: {exc}", file=sys.stderr)
            return 2
        command = pip_audit_command(requirements, ignore_ids, json_output=None)
        print(
            "pip-audit: auditing every package locked in uv.lock "
            f"({len(ignore_ids)} reviewed exception(s) from scripts/security/accepted-risks.toml)",
            flush=True,
        )
        try:
            completed = _run(command, root, PIP_AUDIT_TIMEOUT_SECONDS)
        except ScanError as exc:
            print(f"security-pip-audit: {exc}\n{OFFLINE_HINT}", file=sys.stderr)
            return 2
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part.strip())
    if completed.returncode != 0 and _looks_offline(output):
        # Show the cause, not pip-audit's full network traceback.
        print(output.strip().splitlines()[-1], file=sys.stderr)
        print(OFFLINE_HINT, file=sys.stderr)
        return 2
    print(output.rstrip(), flush=True)
    if completed.returncode != 0:
        print(
            "Upgrade the package within its constraint (`uv lock --upgrade-package NAME`) or, "
            "if that is impossible, record a reviewed exception in "
            "scripts/security/accepted-risks.toml.",
            file=sys.stderr,
        )
    return completed.returncode


# --------------------------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------------------------


def tool_versions(root: Path) -> dict[str, str]:
    versions = {
        name: metadata.version(name)
        for name in ("ruff", "detect-secrets", "pip-audit", "pre-commit")
    }
    try:
        uv = _run((uv_executable(), "--version"), root, 30, check=True).stdout.split()
        versions["uv"] = uv[1] if len(uv) > 1 else "unknown"
    except ScanError:
        versions["uv"] = "unavailable"
    versions["python"] = sys.version.split()[0]
    return versions


def git_state(root: Path) -> tuple[str, str, bool]:
    """Return branch, commit and whether tracked files have uncommitted changes."""
    git = shutil.which("git")
    if not git:
        return "unknown", "unknown", False

    def read(*arguments: str) -> str:
        try:
            return _run((git, *arguments), root, 30, check=True).stdout.strip()
        except ScanError:
            return ""

    branch = read("branch", "--show-current") or "detached"
    commit = read("rev-parse", "HEAD") or "unknown"
    dirty = bool(read("status", "--porcelain", "--untracked-files=no"))
    return branch, commit, dirty
