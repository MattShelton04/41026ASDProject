"""Collect pre-commit security and post-commit CI evidence for the Testing Report Review.

Expected files below the evidence root:

``security/pre-commit-report.md``
    Human-readable scan report. It must name all three scans; a finding is *explained* when
    the report mentions it (Ruff code and file, pip-audit vulnerability ID or alias).
``security/ruff-security.json``
    ``ruff check --select S --output-format json`` output: a list of findings.
``security/detect-secrets.json``
    ``detect-secrets`` scan or audited baseline: ``{"results": {path: [secret, ...]}}``. A
    potential secret passes only when audited as ``"is_secret": false``.
``security/pip-audit.json``
    ``pip-audit --format json`` output: ``{"dependencies": [{"name", "version", "vulns"}]}``.
``ci/student-N.md`` (N = 1..5)
    CI endpoint evidence: the Actions run URL, the 40-character commit SHA, a
    ``Conclusion: success`` line and the JUnit summary from ``shared_testkit.junit_summary``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from pydantic import JsonValue

from scripts.devtools.review.bounded import EvidenceReader
from scripts.devtools.review.checklist import SHA_PATTERN, Checklist, summarise
from shared_contracts.evidence_review import EvidenceReviewBundle

STUDENTS = tuple(f"student-{number}" for number in range(1, 6))
REPORT = "security/pre-commit-report.md"
RUFF = "security/ruff-security.json"
SECRETS = "security/detect-secrets.json"
AUDIT = "security/pip-audit.json"
MIN_ENDPOINT_TESTS = 2
RUN_URL = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/actions/runs/\d+(?:/attempts/\d+)?")
CONCLUSION = re.compile(r"conclusion\W{1,8}([a-z_]+)", re.IGNORECASE)
TOTALS = re.compile(
    r"(\d+) passed, (\d+) failed, (\d+) errors?, (\d+) skipped of (\d+) tests", re.IGNORECASE
)
JUNIT_ATTRIBUTES = re.compile(
    r"tests\W{0,3}(\d+)\W+failures\W{0,3}(\d+)\W+errors\W{0,3}(\d+)", re.IGNORECASE
)
TEST_ROW = re.compile(
    r"^\|\s*`?([^|`]+?)`?\s*\|\s*\**(passed|failed|error|skipped)\**\s*\|", re.IGNORECASE
)
ENDPOINT = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\s+(/[\w./{}:-]*)")


def collect(reader: EvidenceReader) -> EvidenceReviewBundle:
    """Build the testing checklist from the security scans and every student's CI report."""
    checklist = Checklist(reader)
    security = _security(reader, checklist)
    ci: dict[str, JsonValue] = {student: _ci(reader, checklist, student) for student in STUDENTS}
    return checklist.bundle("testing", {"security": security, "ci": ci})


def _security(reader: EvidenceReader, checklist: Checklist) -> dict[str, JsonValue]:
    report = reader.read_text(REPORT)
    text = report.text or ""
    lowered = text.lower()
    scans = {"ruff": "ruff", "detect-secrets": "detect-secrets", "pip-audit": "pip-audit"}
    missing_scans = [name for name, needle in scans.items() if needle not in lowered]
    checklist.add(
        "security.report",
        "Pre-commit security report covers Ruff security rules, detect-secrets and pip-audit",
        passed=report.text is not None and not missing_scans,
        detail=(
            "The report names all three scans."
            if report.text is not None and not missing_scans
            else f"Evidence gap: {REPORT} is {report.status.value}."
            if report.text is None
            else f"The report does not mention: {', '.join(missing_scans)}."
        ),
        refs=(REPORT,),
    )
    checklist.add(
        "security.traceability",
        "Security report records the scanned commit",
        passed=SHA_PATTERN.search(text) is not None,
        required=False,
        detail=(
            "A 40-character commit SHA is recorded."
            if SHA_PATTERN.search(text)
            else "No commit SHA found, so the scan cannot be tied to a release commit."
        ),
        refs=(REPORT,),
    )
    return {
        "ruff": _ruff(reader, checklist, lowered),
        "secrets": _secrets(reader, checklist),
        "dependencies": _dependencies(reader, checklist, lowered),
    }


def _ruff(reader: EvidenceReader, checklist: Checklist, report: str) -> dict[str, JsonValue]:
    loaded, value = reader.read_json(RUFF)
    findings = [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []
    unexplained: list[str] = []
    codes: dict[str, int] = {}
    for finding in findings:
        code = str(finding.get("code") or "unknown")
        codes[code] = codes.get(code, 0) + 1
        filename = str(finding.get("filename") or "").replace("\\", "/")
        tail = "/".join(filename.split("/")[-2:]).lower()
        if code.lower() not in report or (tail and tail not in report):
            location = finding.get("location")
            row = location.get("row") if isinstance(location, dict) else None
            unexplained.append(f"{code} {tail}:{row}")
    valid = isinstance(value, list)
    checklist.add(
        "security.ruff",
        "Ruff security (S) findings are fixed or explained",
        passed=valid and not unexplained,
        detail=(
            f"{len(findings)} finding(s), all explained in the report."
            if valid and not unexplained
            else f"Evidence gap: {RUFF} is {loaded.status.value} or not a JSON list."
            if not valid
            else f"Unexplained findings: {summarise(unexplained)}."
        ),
        refs=(RUFF, REPORT),
    )
    return {"findings": len(findings), "by_code": dict(sorted(codes.items()))}


def _secrets(reader: EvidenceReader, checklist: Checklist) -> dict[str, JsonValue]:
    loaded, value = reader.read_json(SECRETS)
    results = value.get("results") if isinstance(value, dict) else None
    potential = 0
    unaudited: list[str] = []
    confirmed: list[str] = []
    if isinstance(results, dict):
        for path, entries in sorted(results.items()):
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                potential += 1
                label = f"{path}:{entry.get('line_number')} ({entry.get('type')})"
                if entry.get("is_secret") is True:
                    confirmed.append(label)
                elif entry.get("is_secret") is not False:
                    unaudited.append(label)
    valid = isinstance(results, dict)
    checklist.add(
        "security.secrets",
        "detect-secrets reports no confirmed or unaudited secrets",
        passed=valid and not unaudited and not confirmed,
        detail=(
            f"{potential} potential secret(s), all audited as false positives."
            if valid and not unaudited and not confirmed
            else f"Evidence gap: {SECRETS} is {loaded.status.value} or has no results object."
            if not valid
            else f"Confirmed: {summarise(confirmed) or 'none'}; unaudited: "
            f"{summarise(unaudited) or 'none'}."
        ),
        refs=(SECRETS, REPORT),
    )
    return {
        "potential": potential,
        "unaudited": len(unaudited),
        "confirmed": len(confirmed),
    }


def _dependencies(
    reader: EvidenceReader, checklist: Checklist, report: str
) -> dict[str, JsonValue]:
    loaded, value = reader.read_json(AUDIT)
    dependencies = (
        value.get("dependencies")
        if isinstance(value, dict)
        else value
        if isinstance(value, list)
        else None
    )
    scanned = 0
    vulnerable: list[str] = []
    unexplained: list[str] = []
    if isinstance(dependencies, list):
        for dependency in dependencies:
            if not isinstance(dependency, dict):
                continue
            scanned += 1
            vulns = dependency.get("vulns")
            if not isinstance(vulns, list):
                continue
            for vuln in vulns:
                if not isinstance(vuln, dict):
                    continue
                identifier = str(vuln.get("id") or "unknown")
                aliases = vuln.get("aliases")
                names = [identifier, *(aliases if isinstance(aliases, list) else [])]
                label = f"{dependency.get('name')} {dependency.get('version')} {identifier}"
                vulnerable.append(label)
                if not any(str(name).lower() in report for name in names):
                    unexplained.append(label)
    valid = isinstance(dependencies, list)
    checklist.add(
        "security.dependencies",
        "pip-audit reports no unexplained vulnerable dependencies",
        passed=valid and scanned > 0 and not unexplained,
        detail=(
            f"{scanned} dependencies audited; {len(vulnerable)} known vulnerability record(s), "
            "each explained in the report."
            if valid and scanned and not unexplained
            else f"Evidence gap: {AUDIT} is {loaded.status.value} or lists no dependencies."
            if not valid or not scanned
            else f"Unexplained vulnerable dependencies: {summarise(unexplained)}."
        ),
        refs=(AUDIT, REPORT),
    )
    checklist.add(
        "security.dependencies-clean",
        "No known vulnerable dependency remains, even if explained",
        passed=valid and not vulnerable,
        required=False,
        detail=(
            "No known vulnerabilities."
            if valid and not vulnerable
            else f"Accepted vulnerable dependencies remain: {summarise(vulnerable)}."
            if vulnerable
            else "Dependency audit unavailable."
        ),
        refs=(AUDIT,),
    )
    return {"scanned": scanned, "vulnerable": len(vulnerable), "unexplained": len(unexplained)}


def _ci(reader: EvidenceReader, checklist: Checklist, student: str) -> dict[str, JsonValue]:
    path = f"ci/{student}.md"
    loaded = reader.read_text(path)
    text = loaded.text or ""
    run_url = RUN_URL.search(text)
    sha = SHA_PATTERN.search(text)
    conclusion_match = CONCLUSION.search(text)
    conclusion = conclusion_match.group(1).lower() if conclusion_match else None
    outcomes = _test_outcomes(text)
    passed_tests = sorted(name for name, outcome in outcomes.items() if outcome == "passed")
    failing = sorted(name for name, outcome in outcomes.items() if outcome in {"failed", "error"})
    totals = _totals(text)
    endpoints = sorted({f"{method} {route}" for method, route in ENDPOINT.findall(text)})
    gap = f"Evidence gap: {path} is {loaded.status.value}."
    checklist.add(
        f"ci.{student}.run",
        f"{student} CI evidence links the Actions run and commit",
        passed=run_url is not None and sha is not None,
        detail=(
            f"Run {run_url.group(0)} at commit {sha.group(0)[:12]}."
            if run_url and sha
            else gap
            if loaded.text is None
            else "Missing "
            + " and ".join(
                label for label, found in (("run URL", run_url), ("commit SHA", sha)) if not found
            )
            + "."
        ),
        refs=(path,),
    )
    checklist.add(
        f"ci.{student}.green",
        f"{student} CI run concluded successfully",
        passed=conclusion == "success",
        detail=(
            "Conclusion: success."
            if conclusion == "success"
            else gap
            if loaded.text is None
            else f"Conclusion is {conclusion or 'not recorded'}."
        ),
        refs=(path,),
    )
    endpoint_ok = len(passed_tests) >= MIN_ENDPOINT_TESTS and not failing
    checklist.add(
        f"ci.{student}.endpoints",
        f"{student} endpoint tests cover at least two endpoint functions and all pass",
        passed=endpoint_ok,
        detail=(
            f"{len(passed_tests)} passing endpoint test(s): {summarise(passed_tests, limit=3)}."
            if endpoint_ok
            else gap
            if loaded.text is None
            else f"Failing tests: {summarise(failing)}."
            if failing
            else f"Only {len(passed_tests)} passing endpoint test(s) recorded; "
            f"{MIN_ENDPOINT_TESTS} are required."
        ),
        refs=(path,),
    )
    totals_ok = (
        totals is not None
        and totals["tests"] >= MIN_ENDPOINT_TESTS
        and not (totals["failed"] or totals["errors"])
    )
    checklist.add(
        f"ci.{student}.junit",
        f"{student} JUnit totals are recorded with no failures or errors",
        passed=totals_ok,
        required=False,
        detail=(
            f"{totals['passed']} passed of {totals['tests']} tests."
            if totals is not None and totals_ok
            else "No JUnit totals line recorded."
            if totals is None
            else f"{totals['failed']} failed and {totals['errors']} errors of {totals['tests']}."
        ),
        refs=(path,),
    )
    return {
        "run_url": run_url.group(0) if run_url else None,
        "commit": sha.group(0) if sha else None,
        "conclusion": conclusion,
        "passing_tests": len(passed_tests),
        "failing_tests": len(failing),
        "endpoints": list(endpoints[:10]),
        "totals": dict(totals) if totals is not None else None,
    }


def _test_outcomes(text: str) -> dict[str, str]:
    outcomes: dict[str, str] = {}
    for line in text.splitlines():
        match = TEST_ROW.match(line.strip())
        if match and match.group(1).strip().lower() not in {"test", "---"}:
            outcomes[match.group(1).strip()] = match.group(2).lower()
    return outcomes


def _totals(text: str) -> Mapping[str, int] | None:
    match = TOTALS.search(text)
    if match:
        passed, failed, errors, skipped, tests = (int(group) for group in match.groups())
        return {
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "skipped": skipped,
            "tests": tests,
        }
    attributes = JUNIT_ATTRIBUTES.search(text)
    if attributes:
        tests, failed, errors = (int(group) for group in attributes.groups())
        return {
            "passed": tests - failed - errors,
            "failed": failed,
            "errors": errors,
            "skipped": 0,
            "tests": tests,
        }
    return None
