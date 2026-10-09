"""Classify security scan output and render the pre-commit security testing report.

Everything here is pure: the scan runners in `scans.py` supply tool output, so tests can build a
report from fixture JSON without Ruff, detect-secrets, pip-audit or the network.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from scripts.security.policy import (
    AcceptedRisks,
    RuffFix,
    RuffPolicy,
    Slice,
    slice_key,
    to_posix,
)

# Ruff statuses.
FIXED = "fixed"
NOQA_JUSTIFIED = "noqa-justified"
PENDING_OWNER = "pending-owner"
OPEN = "open"
NOQA_WITHOUT_REASON = "noqa-without-reason"
# detect-secrets statuses.
FALSE_POSITIVE = "reviewed-false-positive"
CANDIDATE_NEW = "new-unreviewed"
CANDIDATE_CONFIRMED = "confirmed-secret"
UNAUDITED = "unaudited"
# pip-audit statuses.
ACCEPTED_RISK = "accepted-risk"

FAILING_STATUSES = frozenset(
    {OPEN, NOQA_WITHOUT_REASON, CANDIDATE_NEW, CANDIDATE_CONFIRMED, UNAUDITED}
)

RULE_NAMES = {
    "S101": "assert used outside tests",
    "S104": "binds to all network interfaces",
    "S105": "possible hard-coded password string",
    "S106": "possible hard-coded password argument",
    "S107": "possible hard-coded password default",
    "S108": "insecure temporary file or directory",
    "S110": "try/except/pass hides errors",
    "S113": "HTTP request without a timeout",
    "S310": "URL open without a scheme allow-list",
    "S311": "non-cryptographic random generator",
    "S324": "insecure hash function",
    "S603": "subprocess call; inputs must be trusted",
    "S607": "process started with a partial executable path",
    "S608": "SQL built with string formatting",
}

POLICY_REASONS = {
    "S101": "test assertions",
    "S105": "fake fixture credentials",
    "S106": "fake fixture credentials",
    "S107": "fake fixture credentials",
    "S108": "fixture temp paths",
    "S311": "seeded test randomness",
}

NOQA_PATTERN = re.compile(
    r"#\s*noqa:\s*(?P<codes>[A-Z]+[0-9]+(?:\s*,\s*[A-Z]+[0-9]+)*)(?P<rest>.*)$"
)


@dataclass(frozen=True)
class RawRuffFinding:
    """One Ruff diagnostic with a repository-relative POSIX path."""

    path: str
    row: int
    column: int
    noqa_row: int
    code: str
    message: str

    @classmethod
    def from_ruff(cls, item: Mapping[str, Any], relative: Callable[[str], str]) -> RawRuffFinding:
        location = item["location"]
        return cls(
            path=to_posix(relative(str(item["filename"]))),
            row=int(location["row"]),
            column=int(location["column"]),
            noqa_row=int(item.get("noqa_row") or location["row"]),
            code=str(item["code"]),
            message=str(item["message"]),
        )

    @property
    def key(self) -> tuple[str, int, int, str]:
        return (self.path, self.row, self.column, self.code)


@dataclass(frozen=True)
class RuffFinding:
    path: str
    row: int
    code: str
    message: str
    slice: str
    status: str
    justification: str
    count: int = 1


@dataclass(frozen=True)
class SecretFinding:
    path: str
    line: int
    type: str
    hashed_secret: str
    slice: str
    status: str


@dataclass(frozen=True)
class VulnerabilityFinding:
    package: str
    version: str
    vuln_id: str
    aliases: tuple[str, ...]
    fix_versions: tuple[str, ...]
    status: str
    reason: str


@dataclass(frozen=True)
class PipAuditResult:
    """pip-audit JSON, or the reason it could not be produced (for example, offline)."""

    data: Mapping[str, Any] | None
    error: str | None = None


@dataclass(frozen=True)
class ReportContext:
    generated_at: str
    branch: str
    commit: str
    dirty: bool
    tool_versions: Mapping[str, str]
    commands: Mapping[str, str]


@dataclass(frozen=True)
class SecurityReport:
    context: ReportContext
    slices: Mapping[str, Slice]
    ruff: tuple[RuffFinding, ...]
    secrets: tuple[SecretFinding, ...]
    stale_baseline_entries: int
    vulnerabilities: tuple[VulnerabilityFinding, ...]
    audited_packages: int
    skipped_packages: tuple[str, ...]
    pip_audit_error: str | None
    accepted: AcceptedRisks
    stale_accepted_ids: tuple[str, ...]
    hooks: tuple[tuple[str, str, str], ...] = field(default=())
    policy_ignores: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def failures(self) -> list[str]:
        """Return every reason the security gate should fail."""
        problems = [
            f"Ruff {item.status}: {item.path}:{item.row} {item.code}"
            for item in self.ruff
            if item.status in FAILING_STATUSES
        ]
        problems.extend(
            f"detect-secrets {item.status}: {item.path}:{item.line} {item.type}"
            for item in self.secrets
            if item.status in FAILING_STATUSES
        )
        problems.extend(
            f"pip-audit open vulnerability: {item.package} {item.version} {item.vuln_id}"
            for item in self.vulnerabilities
            if item.status == OPEN
        )
        if self.pip_audit_error:
            problems.append(f"pip-audit did not complete: {self.pip_audit_error}")
        return problems


def parse_noqa(line: str) -> tuple[frozenset[str], str]:
    """Return the codes and free-text reason of a `# noqa: Sxxx - reason` comment."""
    match = NOQA_PATTERN.search(line)
    if match is None:
        return frozenset(), ""
    codes = frozenset(code.strip() for code in match["codes"].split(","))
    reason = match["rest"].strip().lstrip("-#:").strip()
    return codes, reason


def classify_ruff(
    gate: Iterable[RawRuffFinding],
    audit: Iterable[RawRuffFinding],
    *,
    policy: RuffPolicy,
    line_at: Callable[[str, int], str],
    fixed: Sequence[RuffFix] = (),
) -> tuple[RuffFinding, ...]:
    """Explain every `S` finding.

    `gate` is the normal configured run (anything left is open). `audit` ignores `# noqa` and the
    owner exception table, so it also lists findings that are justified or waiting for an owner.
    """
    gate_findings = {item.key: item for item in gate}
    findings: list[RuffFinding] = []
    seen: set[tuple[str, int, int, str]] = set()
    for item in audit:
        seen.add(item.key)
        status, justification = _ruff_status(item, gate_findings, policy, line_at)
        findings.append(
            RuffFinding(
                path=item.path,
                row=item.row,
                code=item.code,
                message=item.message,
                slice=slice_key(item.path),
                status=status,
                justification=justification,
            )
        )
    for key, item in gate_findings.items():
        if key not in seen:
            findings.append(
                RuffFinding(
                    item.path, item.row, item.code, item.message, slice_key(item.path), OPEN, ""
                )
            )
    findings.extend(
        RuffFinding(
            path=fix.path,
            row=0,
            code=fix.rule,
            message=RULE_NAMES.get(fix.rule, fix.rule),
            slice=slice_key(fix.path),
            status=FIXED,
            justification=fix.change,
            count=fix.count,
        )
        for fix in fixed
    )
    return tuple(sorted(findings, key=lambda f: (f.slice, f.path, f.row, f.code, f.status)))


def _ruff_status(
    item: RawRuffFinding,
    gate: Mapping[tuple[str, int, int, str], RawRuffFinding],
    policy: RuffPolicy,
    line_at: Callable[[str, int], str],
) -> tuple[str, str]:
    if item.key in gate:
        return OPEN, "Fails the commit hook: fix it or add `# noqa: CODE - reason`."
    codes, reason = parse_noqa(line_at(item.path, item.noqa_row))
    if item.code in codes:
        return (NOQA_JUSTIFIED, reason) if reason else (NOQA_WITHOUT_REASON, "")
    if policy.owner_exception(item.path, item.code):
        return (
            PENDING_OWNER,
            "Temporarily allowed by `[tool.ruff.lint.extend-per-file-ignores]`; owner to fix "
            "or justify.",
        )
    return OPEN, "Suppressed outside the reviewed policy."


def classify_secrets(
    scan: Mapping[str, Sequence[Mapping[str, Any]]],
    baseline: Mapping[str, Sequence[Mapping[str, Any]]],
) -> tuple[tuple[SecretFinding, ...], int]:
    """Compare a fresh detect-secrets scan with the reviewed baseline.

    Returns the classified findings and the number of baseline entries no longer found.
    """
    reviewed: dict[tuple[str, str, str], Any] = {}
    for path, entries in baseline.items():
        for entry in entries:
            key = (to_posix(path), str(entry["hashed_secret"]), str(entry["type"]))
            reviewed[key] = entry.get("is_secret")
    findings: list[SecretFinding] = []
    found: set[tuple[str, str, str]] = set()
    for path, entries in scan.items():
        posix = to_posix(path)
        for entry in entries:
            key = (posix, str(entry["hashed_secret"]), str(entry["type"]))
            found.add(key)
            if key not in reviewed:
                status = CANDIDATE_NEW
            elif reviewed[key] is False:
                status = FALSE_POSITIVE
            elif reviewed[key] is True:
                status = CANDIDATE_CONFIRMED
            else:
                status = UNAUDITED
            findings.append(
                SecretFinding(
                    path=posix,
                    line=int(entry.get("line_number", 0)),
                    type=key[2],
                    hashed_secret=key[1],
                    slice=slice_key(posix),
                    status=status,
                )
            )
    stale = sum(1 for key in reviewed if key not in found)
    ordered = sorted(findings, key=lambda f: (f.slice, f.path, f.line, f.type))
    return tuple(ordered), stale


def classify_vulnerabilities(
    result: PipAuditResult, accepted: AcceptedRisks
) -> tuple[tuple[VulnerabilityFinding, ...], int, tuple[str, ...], tuple[str, ...]]:
    """Return findings, audited package count, skipped packages and stale accepted IDs."""
    if result.data is None:
        return (), 0, (), ()
    findings: dict[tuple[str, str], VulnerabilityFinding] = {}
    skipped: list[str] = []
    dependencies = result.data.get("dependencies", [])
    for dependency in dependencies:
        name = str(dependency["name"]).lower()
        if dependency.get("skip_reason"):
            skipped.append(f"{name}: {dependency['skip_reason']}")
            continue
        for vuln in dependency.get("vulns", []):
            vuln_id = str(vuln["id"])
            exception = accepted.vulnerability(name, vuln_id)
            findings.setdefault(
                (name, vuln_id),
                VulnerabilityFinding(
                    package=name,
                    version=str(dependency.get("version", "")),
                    vuln_id=vuln_id,
                    aliases=tuple(sorted(str(alias) for alias in vuln.get("aliases", []))),
                    fix_versions=tuple(str(item) for item in vuln.get("fix_versions", [])),
                    status=ACCEPTED_RISK if exception else OPEN,
                    reason=exception.reason if exception else "",
                ),
            )
    reported = {vuln_id for _, vuln_id in findings}
    stale = tuple(vuln for vuln in accepted.ignored_vulnerability_ids() if vuln not in reported)
    audited = len(dependencies) - len(skipped)
    ordered = tuple(sorted(findings.values(), key=lambda f: (f.status, f.package, f.vuln_id)))
    return ordered, audited, tuple(skipped), stale


# --------------------------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------------------------


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _table(headers: Sequence[str], rows: Iterable[Sequence[object]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    lines.extend("| " + " | ".join(_cell(value) for value in row) + " |" for row in rows)
    return lines


def _verdict(passed: bool) -> str:
    return "**PASS**" if passed else "**FAIL**"


def _count(findings: Iterable[RuffFinding], status: str) -> int:
    return sum(item.count for item in findings if item.status == status)


def render_markdown(report: SecurityReport) -> str:
    """Render the reviewable Markdown report."""
    context = report.context
    ruff_failed = any(item.status in FAILING_STATUSES for item in report.ruff)
    secrets_failed = any(item.status in FAILING_STATUSES for item in report.secrets)
    open_vulns = [item for item in report.vulnerabilities if item.status == OPEN]
    accepted_vulns = [item for item in report.vulnerabilities if item.status == ACCEPTED_RISK]
    pip_failed = bool(open_vulns) or report.pip_audit_error is not None
    failures = report.failures()

    out: list[str] = [
        "# Pre-commit security testing report",
        "",
        "Generated by `uv run scripts/dev.py security report` for Release 2 requirements R2-30 "
        "(security scans run when code is committed) and R2-31 (each student records the "
        "results for their own contribution).",
        "",
        f"- **Generated:** {context.generated_at}",
        f"- **Branch:** `{context.branch}`",
        f"- **Commit scanned:** `{context.commit}`"
        + (" (with uncommitted changes)" if context.dirty else ""),
        "- **Tools:** "
        + ", ".join(f"{name} {version}" for name, version in sorted(context.tool_versions.items())),
        f"- **Overall:** {_verdict(not failures)}"
        + ("" if not failures else f" ({len(failures)} item(s) need action, listed below)"),
        "",
        "## Summary",
        "",
    ]
    ruff_summary = (
        f"{_count(report.ruff, OPEN) + _count(report.ruff, NOQA_WITHOUT_REASON)} open; "
        f"{_count(report.ruff, FIXED)} fixed; {_count(report.ruff, NOQA_JUSTIFIED)} justified "
        f"with `# noqa`; {_count(report.ruff, PENDING_OWNER)} pending owner"
    )
    secret_counts = Counter(item.status for item in report.secrets)
    secrets_summary = (
        f"{secret_counts[CANDIDATE_NEW]} new; {secret_counts[CANDIDATE_CONFIRMED]} confirmed; "
        f"{secret_counts[UNAUDITED]} unaudited; {secret_counts[FALSE_POSITIVE]} reviewed false "
        "positives in `.secrets.baseline`"
    )
    if report.pip_audit_error:
        pip_summary = f"not completed: {report.pip_audit_error}"
    else:
        pip_summary = (
            f"{report.audited_packages} locked packages audited; {len(open_vulns)} open; "
            f"{len(accepted_vulns)} accepted risk(s) in "
            f"{len({item.package for item in accepted_vulns})} package(s)"
        )
    out.extend(
        _table(
            ("Scan", "Tool", "Result", "Findings"),
            (
                (
                    "Python security lint (flake8-bandit `S` rules)",
                    "Ruff",
                    _verdict(not ruff_failed),
                    ruff_summary,
                ),
                (
                    "Committed secrets",
                    "detect-secrets",
                    _verdict(not secrets_failed),
                    secrets_summary,
                ),
                (
                    "Known-vulnerable dependencies",
                    "pip-audit",
                    _verdict(not pip_failed),
                    pip_summary,
                ),
            ),
        )
    )
    out.extend(
        [
            "",
            "Status meanings: **open** fails the commit hook; **fixed** was remediated in code; "
            "**noqa-justified** carries a reviewed `# noqa: CODE - reason` on the line; "
            "**pending-owner** is temporarily allowed for that file only and the owner must fix "
            "or justify it; **reviewed-false-positive** is marked `is_secret: false` in the "
            "baseline; **accepted-risk** is listed with a reason in "
            "`scripts/security/accepted-risks.toml`.",
            "",
        ]
    )
    if failures:
        out.extend(["### Items that need action", ""])
        out.extend(f"- {_cell(item)}" for item in failures)
        out.append("")

    out.extend(["## How the scans run during a commit", ""])
    if report.hooks:
        out.extend(_table(("Hook id", "Shown as", "Runs when"), report.hooks))
        out.append("")
    out.extend(
        [
            "Install once with `uv run pre-commit install --hook-type pre-commit --hook-type "
            "pre-push`. `git commit` then runs the hooks on the staged files; "
            "`.github/workflows/integration-ci.yml` repeats all three scans on every pull request "
            "and push to `main`.",
            "",
        ]
    )
    if report.policy_ignores:
        out.extend(
            [
                "## Reviewed rule policy",
                "",
                "These `[tool.ruff.lint.per-file-ignores]` entries apply to test code and "
                "test-only assertion helpers, which never run in a service. Findings they cover "
                "are not listed below. Every other exception is either a `# noqa` with a reason "
                "or a pending-owner entry.",
                "",
            ]
        )
        out.extend(
            _table(
                ("Paths", "Rules not applied", "Why"),
                (
                    (
                        f"`{pattern}`",
                        ", ".join(codes),
                        "; ".join(dict.fromkeys(POLICY_REASONS.get(code, code) for code in codes)),
                    )
                    for pattern, codes in report.policy_ignores.items()
                ),
            )
        )
        out.append("")
    out.extend(["## Results by slice", ""])
    rows = []
    for key, owned in report.slices.items():
        mine = [item for item in report.ruff if item.slice == key]
        secrets = [item for item in report.secrets if item.slice == key]
        rows.append(
            (
                owned.title,
                owned.owner,
                _count(mine, OPEN) + _count(mine, NOQA_WITHOUT_REASON),
                _count(mine, FIXED),
                _count(mine, NOQA_JUSTIFIED),
                _count(mine, PENDING_OWNER),
                sum(1 for item in secrets if item.status == FALSE_POSITIVE),
                sum(1 for item in secrets if item.status in FAILING_STATUSES),
            )
        )
    out.extend(
        _table(
            (
                "Slice",
                "Owner",
                "Ruff open",
                "Ruff fixed",
                "Ruff noqa-justified",
                "Ruff pending owner",
                "Secrets: reviewed false positives",
                "Secrets: need action",
            ),
            rows,
        )
    )
    out.extend(
        [
            "",
            "Dependencies come from the single workspace lockfile (`uv.lock`), so pip-audit "
            "results are reported once, for the Shared platform, below.",
            "",
        ]
    )
    for key, owned in report.slices.items():
        out.extend(_render_slice(report, key, owned))
    out.extend(_render_dependencies(report, open_vulns, accepted_vulns))
    out.extend(_render_reproduce(report))
    return "\n".join(out).rstrip() + "\n"


def _render_slice(report: SecurityReport, key: str, owned: Slice) -> list[str]:
    mine = [item for item in report.ruff if item.slice == key]
    secrets = [item for item in report.secrets if item.slice == key]
    out = [f"### {owned.title}: {owned.owner}", "", f"*{owned.feature}*", ""]
    pending = [item for item in mine if item.status == PENDING_OWNER]
    if pending:
        by_rule = Counter(item.code for item in pending)
        out.extend(
            [
                f"**Owner action:** {len(pending)} finding(s) are pending ("
                + ", ".join(f"{code} x{count}" for code, count in sorted(by_rule.items()))
                + "). Fix each one, or add `# noqa: CODE - reason` on the reported line, then "
                "delete this slice's entries from `[tool.ruff.lint.extend-per-file-ignores]` in "
                "the root `pyproject.toml` and re-run the report.",
                "",
            ]
        )
    if mine:
        rule_counts = Counter(item.code for item in mine for _ in range(item.count))
        out.append(
            "Ruff rules seen: "
            + ", ".join(
                f"{code} ({RULE_NAMES.get(code, 'see Ruff docs')}) x{count}"
                for code, count in sorted(rule_counts.items())
            )
        )
        out.append("")
        out.extend(
            _table(
                ("Location", "Rule", "Status", "Justification or change"),
                (
                    (
                        f"`{item.path}`" + (f":{item.row}" if item.row else f" (x{item.count})"),
                        item.code,
                        item.status,
                        item.justification,
                    )
                    for item in mine
                ),
            )
        )
    else:
        out.append("Ruff security rules: no findings.")
    out.append("")
    if secrets:
        out.extend(
            _table(
                ("Secret candidate", "Detector", "Status"),
                ((f"`{item.path}`:{item.line}", item.type, item.status) for item in secrets),
            )
        )
    else:
        out.append("detect-secrets: no candidates.")
    out.append("")
    return out


def _render_dependencies(
    report: SecurityReport,
    open_vulns: Sequence[VulnerabilityFinding],
    accepted_vulns: Sequence[VulnerabilityFinding],
) -> list[str]:
    out = ["## Dependency audit (pip-audit)", ""]
    if report.pip_audit_error:
        out.extend([f"pip-audit did not complete: {report.pip_audit_error}", ""])
        return out
    out.append(
        f"{report.audited_packages} third-party packages from `uv.lock` (all workspace members "
        "and dependency groups, all platforms) were checked against the PyPI vulnerability "
        "service."
    )
    out.append("")
    if report.skipped_packages:
        out.extend(["Skipped:", ""])
        out.extend(f"- {_cell(item)}" for item in report.skipped_packages)
        out.append("")
    if open_vulns:
        out.extend(["### Open vulnerabilities", ""])
        out.extend(
            _table(
                ("Package", "Version", "ID", "Aliases", "Fixed in"),
                (
                    (
                        v.package,
                        v.version,
                        v.vuln_id,
                        ", ".join(v.aliases),
                        ", ".join(v.fix_versions),
                    )
                    for v in open_vulns
                ),
            )
        )
        out.append("")
    else:
        out.extend(["No open vulnerabilities.", ""])
    out.extend(["### Accepted risks", ""])
    if not report.accepted.vulnerabilities:
        out.extend(["None.", ""])
    for item in report.accepted.vulnerabilities:
        listed = [v for v in accepted_vulns if v.package == item.package]
        fixed_in = sorted({version for v in listed for version in v.fix_versions})
        out.extend(
            [
                f"**{item.package}** ({len(item.ids)} ID(s), reviewed {item.reviewed}; "
                f"fixed upstream in {', '.join(fixed_in) or 'n/a'})",
                "",
                f"- Reason: {item.reason}",
                f"- Follow-up: {item.follow_up}",
                f"- IDs: {', '.join(item.ids)}",
                "",
            ]
        )
    if report.stale_accepted_ids:
        out.extend(
            [
                "Accepted IDs no longer reported (delete them from "
                f"`scripts/security/accepted-risks.toml`): {', '.join(report.stale_accepted_ids)}",
                "",
            ]
        )
    return out


def _render_reproduce(report: SecurityReport) -> list[str]:
    out = ["## Commands run", ""]
    out.extend(
        _table(
            ("Step", "Command"),
            ((name, f"`{command}`") for name, command in report.context.commands.items()),
        )
    )
    out.extend(
        [
            "",
            "## Reproduce",
            "",
            "```text",
            "uv sync --locked --all-packages --all-groups",
            "uv run pre-commit run --all-files                 # every commit hook",
            "uv run scripts/dev.py security report             # regenerate this report",
            "uv run scripts/dev.py security report --check     # fail on unexplained items",
            "```",
            "",
            "Raw results: `ruff-security.json`, `detect-secrets.json` and `pip-audit.json` "
            "in this directory.",
        ]
    )
    return out


def ruff_payload(report: SecurityReport) -> dict[str, Any]:
    return {
        "tool": "ruff",
        "version": report.context.tool_versions.get("ruff", ""),
        "commit": report.context.commit,
        "command": report.context.commands.get("Ruff (audit)", ""),
        "findings": [
            {
                "path": item.path,
                "row": item.row or None,
                "code": item.code,
                "message": item.message,
                "slice": item.slice,
                "status": item.status,
                "justification": item.justification,
                "count": item.count,
            }
            for item in report.ruff
        ],
    }


def secrets_payload(report: SecurityReport) -> dict[str, Any]:
    return {
        "tool": "detect-secrets",
        "version": report.context.tool_versions.get("detect-secrets", ""),
        "commit": report.context.commit,
        "baseline": ".secrets.baseline",
        "stale_baseline_entries": report.stale_baseline_entries,
        "findings": [
            {
                "path": item.path,
                "line": item.line,
                "type": item.type,
                "hashed_secret": item.hashed_secret,
                "slice": item.slice,
                "status": item.status,
            }
            for item in report.secrets
        ],
    }
