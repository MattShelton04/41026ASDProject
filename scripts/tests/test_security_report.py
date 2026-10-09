"""Deterministic tests for the pre-commit security scans and their report (no network)."""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml
from scripts import dev
from scripts.security import cli, scans
from scripts.security.policy import (
    BASELINE_NAME,
    DETECT_SECRETS_EXCLUDE_FILES,
    DETECT_SECRETS_EXCLUDE_LINES,
    AcceptedRisks,
    AcceptedVulnerability,
    PolicyError,
    RuffFix,
    load_accepted_risks,
    load_ruff_policy,
    load_slices,
    slice_key,
)
from scripts.security.report import (
    ACCEPTED_RISK,
    CANDIDATE_CONFIRMED,
    CANDIDATE_NEW,
    FALSE_POSITIVE,
    FIXED,
    NOQA_JUSTIFIED,
    NOQA_WITHOUT_REASON,
    OPEN,
    PENDING_OWNER,
    UNAUDITED,
    PipAuditResult,
    RawRuffFinding,
    ReportContext,
    SecurityReport,
    classify_ruff,
    classify_secrets,
    classify_vulnerabilities,
    parse_noqa,
    render_markdown,
    ruff_payload,
    secrets_payload,
)

ROOT = Path(__file__).resolve().parents[2]

README = """\
| Student | Owner / student ID | Feature | Local frontend | Owned storage |
|---|---|---|---|---|
| 1 | Ada Lovelace / 11111111 | [Data Platform](student-1/README.md) | 5200 | PostgreSQL |
| 2 | Grace Hopper / 22222222 | [Market Cases](student-2/README.md) | 5300 | SQLite |
"""

PYPROJECT = """\
[tool.ruff]
target-version = "py312"
extend-exclude = ["tmp"]

[tool.ruff.lint]
select = ["E", "S"]

[tool.ruff.lint.per-file-ignores]
"**/tests/**" = ["S101", "S105"]

[tool.ruff.lint.extend-per-file-ignores]
"student-2/app.py" = ["S608"]
"""

SOURCE = {
    "shared/run.py": [
        "import subprocess",
        "subprocess.run(argv)  # noqa: S603 - fixed argv, no shell",
        "subprocess.run(argv)  # noqa: S603",
        "eval(value)",
    ],
    "student-2/app.py": ['cursor.execute(f"SELECT {column} FROM t")'],
    "student-1/hidden.py": ["requests.get(url)"],
}


def _raw(path: str, row: int, code: str, *, noqa_row: int | None = None) -> RawRuffFinding:
    return RawRuffFinding(path, row, 1, noqa_row or row, code, f"{code} message")


def _line_at(path: str, row: int) -> str:
    return SOURCE[path][row - 1]


def _ruff_fixture() -> tuple[list[RawRuffFinding], list[RawRuffFinding]]:
    gate = [_raw("shared/run.py", 4, "S307")]
    audit = [
        _raw("shared/run.py", 2, "S603"),
        _raw("shared/run.py", 3, "S603"),
        _raw("shared/run.py", 4, "S307"),
        _raw("student-2/app.py", 1, "S608"),
        _raw("student-1/hidden.py", 1, "S113"),
    ]
    return gate, audit


def _accepted() -> AcceptedRisks:
    return AcceptedRisks(
        vulnerabilities=(
            AcceptedVulnerability(
                package="pillow",
                ids=("PYSEC-1", "PYSEC-STALE"),
                reason="Blocked by an upstream pin; no untrusted images are decoded.",
                follow_up="Upgrade the pin.",
                reviewed="2026-10-09",
            ),
        ),
        ruff_fixed=(RuffFix("student-1/app.py", "S101", 2, "assert replaced by TypeError"),),
    )


PIP_AUDIT_JSON: dict[str, Any] = {
    "dependencies": [
        {
            "name": "Pillow",
            "version": "11.3.0",
            "vulns": [
                {"id": "PYSEC-1", "fix_versions": ["12.0"], "aliases": ["CVE-1"]},
                {"id": "PYSEC-1", "fix_versions": ["12.0"], "aliases": ["CVE-1"]},
            ],
        },
        {
            "name": "werkzeug",
            "version": "3.1.8",
            "vulns": [{"id": "GHSA-x", "fix_versions": ["3.1.9"], "aliases": []}],
        },
        {"name": "flask", "version": "3.1.3", "vulns": []},
        {"name": "local-thing", "skip_reason": "not on PyPI"},
    ],
    "fixes": [],
}


def _report(**overrides: Any) -> SecurityReport:
    policy = load_ruff_policy(PYPROJECT)
    gate, audit = _ruff_fixture()
    accepted = _accepted()
    ruff = classify_ruff(gate, audit, policy=policy, line_at=_line_at, fixed=accepted.ruff_fixed)
    secrets, stale = classify_secrets(
        {"shared/a.py": [{"type": "Secret Keyword", "hashed_secret": "h1", "line_number": 3}]},
        {"shared/a.py": [{"type": "Secret Keyword", "hashed_secret": "h1", "is_secret": False}]},
    )
    vulns, audited, skipped, stale_ids = classify_vulnerabilities(
        PipAuditResult(PIP_AUDIT_JSON), accepted
    )
    values: dict[str, Any] = {
        "context": ReportContext(
            generated_at="2026-10-09T00:00:00+00:00",
            branch="feature",
            commit="abc123",
            dirty=False,
            tool_versions={"ruff": "0.16.1", "detect-secrets": "1.5.0"},
            commands={"Ruff (audit)": "ruff check . --select S --ignore-noqa"},
        ),
        "slices": load_slices(README),
        "ruff": ruff,
        "secrets": secrets,
        "stale_baseline_entries": stale,
        "vulnerabilities": vulns,
        "audited_packages": audited,
        "skipped_packages": skipped,
        "pip_audit_error": None,
        "accepted": accepted,
        "stale_accepted_ids": stale_ids,
        "hooks": (("`security-ruff`", "security: Ruff", "`git commit`"),),
        "policy_ignores": policy.per_file_ignores,
    }
    values.update(overrides)
    return SecurityReport(**values)


# ---------------------------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "codes", "reason"),
    [
        ("run()  # noqa: S603 - fixed argv, no shell", {"S603"}, "fixed argv, no shell"),
        ("run()  # noqa: S603, S607 - git from PATH", {"S603", "S607"}, "git from PATH"),
        ("run()  # noqa: S603  # loopback only", {"S603"}, "loopback only"),
        ("run()  # noqa: S603", {"S603"}, ""),
        ("run()", set(), ""),
    ],
)
def test_noqa_comments_yield_codes_and_reasons(line: str, codes: set[str], reason: str) -> None:
    assert parse_noqa(line) == (frozenset(codes), reason)


def test_ruff_findings_are_explained_by_noqa_owner_exception_or_left_open() -> None:
    gate, audit = _ruff_fixture()
    findings = classify_ruff(
        gate,
        audit,
        policy=load_ruff_policy(PYPROJECT),
        line_at=_line_at,
        fixed=(RuffFix("student-1/app.py", "S101", 2, "assert replaced"),),
    )
    by_location = {(item.path, item.row): item for item in findings}
    assert by_location["shared/run.py", 2].status == NOQA_JUSTIFIED
    assert by_location["shared/run.py", 2].justification == "fixed argv, no shell"
    assert by_location["shared/run.py", 3].status == NOQA_WITHOUT_REASON
    assert by_location["shared/run.py", 4].status == OPEN
    assert by_location["student-2/app.py", 1].status == PENDING_OWNER
    assert by_location["student-2/app.py", 1].slice == "student-2"
    # Suppressed by something other than the reviewed policy: never silently accepted.
    assert by_location["student-1/hidden.py", 1].status == OPEN
    fixed = by_location["student-1/app.py", 0]
    assert (fixed.status, fixed.count, fixed.slice) == (FIXED, 2, "student-1")


def test_gate_findings_missing_from_the_audit_run_are_still_open() -> None:
    findings = classify_ruff(
        [_raw("shared/x.py", 1, "S101")],
        [],
        policy=load_ruff_policy(PYPROJECT),
        line_at=lambda path, row: "",
    )
    assert [(item.path, item.status) for item in findings] == [("shared/x.py", OPEN)]


def test_raw_ruff_findings_use_repository_relative_posix_paths() -> None:
    item = {
        "filename": "C:\\repo\\student-3\\app.py",
        "location": {"row": 4, "column": 2},
        "noqa_row": 6,
        "code": "S104",
        "message": "bind",
    }
    raw = RawRuffFinding.from_ruff(item, lambda name: name.removeprefix("C:\\repo\\"))
    assert (raw.path, raw.row, raw.noqa_row) == ("student-3/app.py", 4, 6)


def test_secret_candidates_are_compared_with_the_reviewed_baseline() -> None:
    scan = {
        "shared\\a.py": [
            {"type": "Secret Keyword", "hashed_secret": "reviewed", "line_number": 1},
            {"type": "Secret Keyword", "hashed_secret": "new", "line_number": 2},
            {"type": "Secret Keyword", "hashed_secret": "real", "line_number": 3},
            {"type": "Secret Keyword", "hashed_secret": "unaudited", "line_number": 4},
        ]
    }
    baseline = {
        "shared/a.py": [
            {"type": "Secret Keyword", "hashed_secret": "reviewed", "is_secret": False},
            {"type": "Secret Keyword", "hashed_secret": "real", "is_secret": True},
            {"type": "Secret Keyword", "hashed_secret": "unaudited"},
            {"type": "Secret Keyword", "hashed_secret": "gone", "is_secret": False},
        ]
    }
    findings, stale = classify_secrets(scan, baseline)
    statuses = {item.hashed_secret: item.status for item in findings}
    assert statuses == {
        "reviewed": FALSE_POSITIVE,
        "new": CANDIDATE_NEW,
        "real": CANDIDATE_CONFIRMED,
        "unaudited": UNAUDITED,
    }
    assert {item.path for item in findings} == {"shared/a.py"}
    assert stale == 1


def test_vulnerabilities_are_deduplicated_and_split_into_accepted_and_open() -> None:
    findings, audited, skipped, stale = classify_vulnerabilities(
        PipAuditResult(PIP_AUDIT_JSON), _accepted()
    )
    assert [(item.package, item.vuln_id, item.status) for item in findings] == [
        ("pillow", "PYSEC-1", ACCEPTED_RISK),
        ("werkzeug", "GHSA-x", OPEN),
    ]
    assert audited == 3
    assert skipped == ("local-thing: not on PyPI",)
    assert stale == ("PYSEC-STALE",)


def test_an_unfinished_audit_is_reported_rather_than_treated_as_clean() -> None:
    assert classify_vulnerabilities(PipAuditResult(None, "offline"), _accepted()) == (
        (),
        0,
        (),
        (),
    )
    report = _report(vulnerabilities=(), pip_audit_error="offline")
    assert "pip-audit did not complete: offline" in report.failures()


# ---------------------------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------------------------


def test_report_lists_each_slice_with_its_owner_and_owner_actions() -> None:
    report = _report()
    markdown = render_markdown(report)
    assert markdown.startswith("# Pre-commit security testing report\n")
    assert "| Shared platform | Ada Lovelace (group lead) |" in markdown
    assert "### Student 2: Grace Hopper" in markdown
    assert "**Owner action:** 1 finding(s) are pending (S608 x1)" in markdown
    assert "`student-1/app.py` (x2) | S101 | fixed | assert replaced by TypeError" in markdown
    assert "| `shared/run.py`:2 | S603 | noqa-justified | fixed argv, no shell |" in markdown
    assert "## Reviewed rule policy" in markdown
    assert "`**/tests/**` | S101, S105 | test assertions; fake fixture credentials" in markdown
    assert "**pillow** (2 ID(s), reviewed 2026-10-09; fixed upstream in 12.0)" in markdown
    assert "PYSEC-STALE" in markdown
    assert "### Open vulnerabilities" in markdown
    assert "| werkzeug | 3.1.8 | GHSA-x |" in markdown
    assert "**Overall:** **FAIL**" in markdown
    assert "### Items that need action" in markdown


def test_report_failures_name_every_unexplained_item() -> None:
    failures = _report().failures()
    assert "Ruff open: shared/run.py:4 S307" in failures
    assert "Ruff noqa-without-reason: shared/run.py:3 S603" in failures
    assert "pip-audit open vulnerability: werkzeug 3.1.8 GHSA-x" in failures
    assert not any("student-2" in failure for failure in failures)


def test_clean_report_passes_and_escapes_table_cells() -> None:
    report = _report(
        ruff=(),
        vulnerabilities=(),
        stale_accepted_ids=(),
        hooks=(("`x`", "a|b", "`git commit`"),),
    )
    markdown = render_markdown(report)
    assert report.failures() == []
    assert "**Overall:** **PASS**" in markdown
    assert "a\\|b" in markdown
    assert "No open vulnerabilities." in markdown


def test_json_payloads_carry_status_and_slice() -> None:
    report = _report()
    ruff = ruff_payload(report)
    assert ruff["tool"] == "ruff"
    assert {item["status"] for item in ruff["findings"]} >= {OPEN, PENDING_OWNER, FIXED}
    secrets = secrets_payload(report)
    assert secrets["findings"][0]["status"] == FALSE_POSITIVE
    json.dumps(ruff)
    json.dumps(secrets)


def test_evidence_files_are_written_together(tmp_path: Path) -> None:
    written = cli.write_evidence(_report(), PIP_AUDIT_JSON, tmp_path)
    assert sorted(path.name for path in written) == [
        "detect-secrets.json",
        "pip-audit.json",
        "pre-commit-report.md",
        "ruff-security.json",
    ]
    assert json.loads((tmp_path / "pip-audit.json").read_text())["dependencies"]
    offline = cli.write_evidence(_report(pip_audit_error="offline"), None, tmp_path / "x")
    assert json.loads(offline[-1].read_text()) == {"error": "offline", "dependencies": []}


# ---------------------------------------------------------------------------------------------
# Policy inputs
# ---------------------------------------------------------------------------------------------


def test_slices_come_from_the_readme_team_table() -> None:
    slices = load_slices(README)
    assert list(slices) == ["shared", "student-1", "student-2"]
    assert slices["student-2"].owner == "Grace Hopper"
    assert slices["student-2"].feature == "Market Cases"
    with pytest.raises(PolicyError):
        load_slices("no table")


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("student-4/backend/x.py", "student-4"),
        ("scripts/dev.py", "shared"),
        ("README.md", "shared"),
    ],
)
def test_paths_map_to_their_owning_slice(path: str, expected: str) -> None:
    assert slice_key(path) == expected


def test_ruff_policy_requires_s_rules_and_builds_valid_isolated_overrides() -> None:
    policy = load_ruff_policy(PYPROJECT)
    assert policy.owner_exception("student-2/app.py", "S608")
    assert not policy.owner_exception("student-2/app.py", "S101")
    arguments = policy.isolated_arguments()
    assert arguments[0] == "--isolated"
    overrides = [
        arguments[index + 1] for index, value in enumerate(arguments) if value == "--config"
    ]
    parsed = [tomllib.loads(item) for item in overrides]
    assert parsed[-1]["lint"]["per-file-ignores"] == {"**/tests/**": ["S101", "S105"]}
    assert not any("extend-per-file-ignores" in item for item in overrides)
    with pytest.raises(PolicyError, match="must include the S"):
        load_ruff_policy('[tool.ruff.lint]\nselect = ["E"]\n')


def test_accepted_risks_require_reasons(tmp_path: Path) -> None:
    path = tmp_path / "risks.toml"
    path.write_text('[[pip_audit]]\npackage = "x"\nids = ["A"]\nreason = ""\n', encoding="utf-8")
    with pytest.raises(PolicyError, match="reason"):
        load_accepted_risks(path)
    path.write_text('[[ruff_fixed]]\npath = "a"\nrule = "S1"\ncount = 0\n', encoding="utf-8")
    with pytest.raises(PolicyError, match="count"):
        load_accepted_risks(path)


# ---------------------------------------------------------------------------------------------
# The committed configuration
# ---------------------------------------------------------------------------------------------


def test_repository_policy_keeps_owner_exceptions_inside_other_students_slices() -> None:
    policy = load_ruff_policy((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert policy.per_file_ignores["**/tests/**"][0] == "S101"
    assert policy.owner_exceptions
    for pattern in policy.owner_exceptions:
        assert re.match(r"^student-[2-5]/", pattern), pattern
        assert "*" not in pattern, "owner exceptions must name individual files"


def test_committed_accepted_risks_are_complete() -> None:
    risks = load_accepted_risks()
    assert risks.ignored_vulnerability_ids()
    assert all(item.follow_up for item in risks.vulnerabilities)
    assert all((ROOT / fix.path).exists() for fix in risks.ruff_fixed)


def test_secrets_baseline_is_reviewed_portable_and_uses_the_scan_settings() -> None:
    baseline = json.loads((ROOT / BASELINE_NAME).read_text(encoding="utf-8"))
    entries = [entry for items in baseline["results"].values() for entry in items]
    assert entries, "the reviewed baseline should record the known false positives"
    assert all(entry["is_secret"] is False for entry in entries)
    assert all("\\" not in path for path in baseline["results"])
    filters = {item["path"]: item.get("pattern") for item in baseline["filters_used"]}
    assert filters["detect_secrets.filters.regex.should_exclude_file"] == list(
        DETECT_SECRETS_EXCLUDE_FILES
    )
    assert filters["detect_secrets.filters.regex.should_exclude_line"] == list(
        DETECT_SECRETS_EXCLUDE_LINES
    )


@pytest.mark.parametrize(
    ("line", "excluded"),
    [
        ('    "content_hash": "' + "a" * 64 + '",', True),
        ('BASELINE = "' + "b" * 40 + '"', True),
        ("ACTIONLINT_SHA256: " + "c" * 64, True),
        ('"headSha": "' + "d" * 40 + '",', True),
        ('api_key = "' + "e" * 64 + '"', False),
        ('"' + "f" * 64 + '"', False),
    ],
)
def test_only_named_digests_are_excluded_from_secret_scanning(line: str, excluded: bool) -> None:
    assert bool(re.search(DETECT_SECRETS_EXCLUDE_LINES[0], line)) is excluded


@pytest.mark.parametrize(
    ("path", "excluded"),
    [
        ("uv.lock", True),
        ("shared\\frontend\\vendor\\htmx.min.js", True),
        ("docs/a.png", True),
        ("student-1/app.py", False),
        ("docs/release-1/evidence/run.json", False),
    ],
)
def test_secret_scanning_skips_only_generated_vendor_and_binary_files(
    path: str, excluded: bool
) -> None:
    assert any(re.search(pattern, path) for pattern in DETECT_SECRETS_EXCLUDE_FILES) is excluded


def test_commit_hooks_include_the_three_security_scans() -> None:
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    hooks = {hook["id"]: hook for repo in config["repos"] for hook in repo["hooks"]}
    for hook_id in ("security-ruff", "security-detect-secrets", "security-pip-audit"):
        hook = hooks[hook_id]
        assert "pre-commit" in hook["stages"]
        assert hook["entry"].startswith("uv run --locked ")
        assert hook["name"].startswith("security: ")
    assert "--select S" in hooks["security-ruff"]["entry"]
    assert re.search(hooks["security-pip-audit"]["files"], "uv.lock")
    assert re.search(hooks["security-pip-audit"]["files"], "student-3/pyproject.toml")
    rows = cli.commit_hooks(ROOT)
    assert [row[0] for row in rows] == [
        "`security-ruff`",
        "`security-detect-secrets`",
        "`security-pip-audit`",
    ]


def test_integration_ci_runs_the_same_security_scans() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/integration-ci.yml").read_text(encoding="utf-8")
    )
    job = workflow["jobs"]["security"]
    commands = "\n".join(step.get("run", "") for step in job["steps"])
    for hook_id in ("security-ruff", "security-detect-secrets", "security-pip-audit"):
        assert f"pre-commit run {hook_id} --all-files" in commands
    assert "scripts.security report --check" in commands
    for step in job["steps"]:
        action = step.get("uses", "")
        if action:
            assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", action), action


# ---------------------------------------------------------------------------------------------
# Scanner wrappers (subprocess replaced; no network)
# ---------------------------------------------------------------------------------------------


def test_baseline_paths_are_normalised_and_merged() -> None:
    document = {
        "results": {
            "b\\x.py": [{"type": "T", "hashed_secret": "2", "line_number": 9}],
            "b/x.py": [{"type": "T", "hashed_secret": "1", "line_number": 1}],
            "a.py": [],
        }
    }
    normalised = scans.normalise_baseline(document)
    assert list(normalised["results"]) == ["a.py", "b/x.py"]
    assert [entry["hashed_secret"] for entry in normalised["results"]["b/x.py"]] == ["1", "2"]
    assert {entry["filename"] for entry in normalised["results"]["b/x.py"]} == {"b/x.py"}


def test_ruff_audit_ignores_noqa_and_owner_exceptions() -> None:
    command = scans.ruff_audit_command(load_ruff_policy(PYPROJECT))
    assert "--ignore-noqa" in command
    assert "--isolated" in command
    assert scans.display(command).startswith("ruff check . --select S")


def _completed(code: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(("tool",), code, stdout, stderr)


def test_pip_audit_hook_explains_an_offline_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run(
        command: tuple[str, ...], root: Path, timeout: float, *, check: bool = False
    ) -> subprocess.CompletedProcess[str]:
        calls.append(tuple(command))
        if "export" in command:
            return _completed(0)
        return _completed(1, stderr="Traceback ...\nConnectionError: Max retries exceeded")

    monkeypatch.setattr(scans, "_run", fake_run)
    monkeypatch.setattr(scans, "uv_executable", lambda: "uv")
    assert scans.pip_audit_hook(ROOT, ("PYSEC-1",)) == 2
    error = capsys.readouterr().err
    assert "SKIP=security-pip-audit" in error
    assert "Traceback" not in error
    audit = calls[-1]
    assert audit[audit.index("--ignore-vuln") + 1] == "PYSEC-1"
    assert "--disable-pip" in audit


def test_pip_audit_hook_reports_vulnerabilities_with_remediation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_run(
        command: tuple[str, ...], root: Path, timeout: float, *, check: bool = False
    ) -> subprocess.CompletedProcess[str]:
        if "export" in command:
            return _completed(0)
        return _completed(1, stdout="Found 1 known vulnerability in 1 package")

    monkeypatch.setattr(scans, "_run", fake_run)
    monkeypatch.setattr(scans, "uv_executable", lambda: "uv")
    assert scans.pip_audit_hook(ROOT, ()) == 1
    captured = capsys.readouterr()
    assert "Found 1 known vulnerability" in captured.out
    assert "uv lock --upgrade-package" in captured.err


def test_pip_audit_for_the_report_records_why_it_did_not_finish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(
        command: tuple[str, ...], root: Path, timeout: float, *, check: bool = False
    ) -> subprocess.CompletedProcess[str]:
        if "export" in command:
            return _completed(0)
        return _completed(1, stderr="NameResolutionError: pypi.org")

    monkeypatch.setattr(scans, "_run", fake_run)
    monkeypatch.setattr(scans, "uv_executable", lambda: "uv")
    result = scans.run_pip_audit(ROOT)
    assert result.data is None
    assert result.error == "offline or vulnerability service unreachable"


def test_dev_cli_forwards_security_report_options(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[list[str]] = []

    def fake_main(argv: list[str]) -> int:
        received.append(argv)
        return 7

    monkeypatch.setattr(cli, "main", fake_main)
    assert dev.main(["security", "report", "--check", "--output-dir", "out"]) == 7
    assert dev.main(["security", "baseline"]) == 7
    assert received == [["report", "--output-dir", "out", "--check"], ["baseline"]]


def test_security_cli_report_exit_code_follows_check(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cli, "build_report", lambda root: (_report(), PIP_AUDIT_JSON))
    assert cli.main(["report", "--output-dir", str(tmp_path)]) == 0
    assert cli.main(["report", "--output-dir", str(tmp_path), "--check"]) == 1
    assert (tmp_path / "pre-commit-report.md").exists()


def test_detect_secrets_hook_keeps_a_rewritten_baseline_portable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = tmp_path / BASELINE_NAME
    baseline.write_text('{"results": {}}', encoding="utf-8")

    def fake_hook(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert "detect_secrets.pre_commit_hook" in command
        assert kwargs["cwd"] == tmp_path
        rewritten = {"results": {"a\\b.py": [{"type": "T", "hashed_secret": "1"}]}}
        baseline.write_text(json.dumps(rewritten), encoding="utf-8")
        return _completed(0)

    monkeypatch.setattr(scans.subprocess, "run", fake_hook)
    assert scans.detect_secrets_hook(tmp_path, ["a/b.py"]) == 0
    assert list(json.loads(baseline.read_text(encoding="utf-8"))["results"]) == ["a/b.py"]
    assert "1 file(s) scanned" in capsys.readouterr().out
