"""Command line for the pre-commit security scans and the security testing report."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from scripts.security import scans
from scripts.security.policy import (
    ACCEPTED_RISKS_PATH,
    EVIDENCE_DIRECTORY,
    REPORT_NAME,
    REPOSITORY_ROOT,
    PolicyError,
    load_accepted_risks,
    load_ruff_policy,
    load_slices,
)
from scripts.security.report import (
    ReportContext,
    SecurityReport,
    classify_ruff,
    classify_secrets,
    classify_vulnerabilities,
    render_markdown,
    ruff_payload,
    secrets_payload,
)

SECURITY_HOOK_PREFIX = "security-"


def _line_reader(root: Path) -> Callable[[str, int], str]:
    cache: dict[str, list[str]] = {}

    def line_at(path: str, row: int) -> str:
        if path not in cache:
            try:
                cache[path] = (root / path).read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                cache[path] = []
        lines = cache[path]
        return lines[row - 1] if 0 < row <= len(lines) else ""

    return line_at


def commit_hooks(root: Path) -> tuple[tuple[str, str, str], ...]:
    """Describe the security hooks configured in `.pre-commit-config.yaml`."""
    config = yaml.safe_load((root / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    rows: list[tuple[str, str, str]] = []
    for repository in config.get("repos", []):
        for hook in repository.get("hooks", []):
            if not str(hook.get("id", "")).startswith(SECURITY_HOOK_PREFIX):
                continue
            stages = ", ".join(hook.get("stages", ["pre-commit"]))
            trigger = f"`git commit` ({stages})"
            if hook.get("files"):
                trigger += f"; staged files matching `{hook['files']}`"
            elif hook.get("types_or") or hook.get("types"):
                kinds = hook.get("types_or") or hook.get("types")
                trigger += f"; staged {'/'.join(kinds)} files"
            rows.append((f"`{hook['id']}`", str(hook.get("name", "")), trigger))
    return tuple(rows)


def build_report(
    root: Path = REPOSITORY_ROOT,
) -> tuple[SecurityReport, Mapping[str, Any] | None]:
    """Run all three scans; return the classified report and the raw pip-audit JSON."""
    policy = load_ruff_policy((root / "pyproject.toml").read_text(encoding="utf-8"))
    accepted = load_accepted_risks(ACCEPTED_RISKS_PATH)
    slices = load_slices((root / "README.md").read_text(encoding="utf-8"))
    print("Running Ruff security rules ...", flush=True)
    gate, audit = scans.run_ruff(root, policy)
    ruff = classify_ruff(
        gate, audit, policy=policy, line_at=_line_reader(root), fixed=accepted.ruff_fixed
    )
    print("Running detect-secrets against .secrets.baseline ...", flush=True)
    committed, fresh = scans.run_detect_secrets(root)
    secrets, stale = classify_secrets(fresh.get("results", {}), committed.get("results", {}))
    print("Running pip-audit against uv.lock ...", flush=True)
    audit_result = scans.run_pip_audit(root)
    vulnerabilities, audited, skipped, stale_ids = classify_vulnerabilities(audit_result, accepted)
    branch, commit, dirty = scans.git_state(root)
    commands = {
        "Ruff (gate, as in the commit hook)": scans.display(scans.ruff_gate_command()),
        "Ruff (audit)": scans.display(scans.ruff_audit_command(policy)),
        "detect-secrets": "detect-secrets scan --baseline <copy of .secrets.baseline>",
        "Lockfile export": "uv export --locked --all-packages --all-groups --no-emit-workspace "
        "--format requirements-txt --output-file <tmp>/requirements.txt",
        "pip-audit": "pip-audit --requirement <tmp>/requirements.txt --disable-pip "
        "--format json (no ignores; accepted risks are classified afterwards)",
    }
    context = ReportContext(
        generated_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
        branch=branch,
        commit=commit,
        dirty=dirty,
        tool_versions=scans.tool_versions(root),
        commands=commands,
    )
    report = SecurityReport(
        context=context,
        slices=slices,
        ruff=ruff,
        secrets=secrets,
        stale_baseline_entries=stale,
        vulnerabilities=vulnerabilities,
        audited_packages=audited,
        skipped_packages=skipped,
        pip_audit_error=audit_result.error,
        accepted=accepted,
        stale_accepted_ids=stale_ids,
        hooks=commit_hooks(root),
        policy_ignores=policy.per_file_ignores,
    )
    return report, audit_result.data


def write_evidence(
    report: SecurityReport, pip_audit: Mapping[str, Any] | None, output_directory: Path
) -> tuple[Path, ...]:
    """Write the Markdown report and the three JSON result files."""
    output_directory.mkdir(parents=True, exist_ok=True)
    files = {
        REPORT_NAME: render_markdown(report),
        "ruff-security.json": json.dumps(ruff_payload(report), indent=2) + "\n",
        "detect-secrets.json": json.dumps(secrets_payload(report), indent=2) + "\n",
        "pip-audit.json": json.dumps(
            pip_audit
            if pip_audit is not None
            else {"error": report.pip_audit_error, "dependencies": []},
            indent=2,
        )
        + "\n",
    }
    written = []
    for name, content in files.items():
        path = output_directory / name
        path.write_bytes(content.encode("utf-8"))
        written.append(path)
    return tuple(written)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.security",
        description="Pre-commit security scans (Ruff S rules, detect-secrets, pip-audit).",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    report = commands.add_parser("report", help="Run all scans and write the evidence report")
    report.add_argument("--output-dir", type=Path, default=EVIDENCE_DIRECTORY)
    report.add_argument(
        "--check", action="store_true", help="Exit non-zero when any finding is unexplained"
    )
    commands.add_parser("pip-audit", help="Pre-commit hook: audit uv.lock with pip-audit")
    hook = commands.add_parser(
        "detect-secrets", help="Pre-commit hook: detect-secrets against .secrets.baseline"
    )
    hook.add_argument("filenames", nargs="*")
    commands.add_parser(
        "baseline", help="Create or refresh .secrets.baseline, keeping audit decisions"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    root = REPOSITORY_ROOT
    try:
        if arguments.command == "pip-audit":
            return scans.pip_audit_hook(root, load_accepted_risks().ignored_vulnerability_ids())
        if arguments.command == "detect-secrets":
            return scans.detect_secrets_hook(root, arguments.filenames)
        if arguments.command == "baseline":
            path = scans.refresh_baseline(root)
            print(
                f"Updated {path.name}. Review new entries with "
                "`uv run detect-secrets audit .secrets.baseline` before committing."
            )
            return 0
        report, pip_audit = build_report(root)
        written = write_evidence(report, pip_audit, arguments.output_dir)
    except (PolicyError, scans.ScanError) as exc:
        print(f"security: {exc}", file=sys.stderr)
        return 2
    for path in written:
        print(f"wrote {path.relative_to(root) if path.is_relative_to(root) else path}")
    failures = report.failures()
    for failure in failures:
        print(f"  needs action: {failure}", file=sys.stderr)
    if not failures:
        print("Security scans: PASS (no unexplained findings)")
    return 1 if failures and arguments.check else 0
