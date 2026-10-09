"""Collect cloud deployment evidence for the Cloud Deployment Report Review.

Expected files below the evidence root (``cloud/release-decision.md`` is written by the human
decision command and is deliberately not reviewed):

``cloud/cloud-deployment-report.md``
    Deployment report naming the public URL and the deployed 40-character commit SHA.
``cloud/smoke*.json``
    Public smoke output::

        {"base_url": "https://...", "commit_sha": "<40 hex>", "ai_enabled": false,
         "images": {"service": "registry/name:<commit sha>" | "registry/name@sha256:<digest>"},
         "checks": [{"name": "home", "category": "frontend", "passed": true},
                    {"name": "listings CRUD", "category": "crud", "feature": "student-1",
                     "passed": true},
                    {"name": "AI routes disabled", "category": "ai_disabled", "passed": true}]}

    ``passed`` may instead be ``status``/``outcome``/``result`` with ``passed``/``success``;
    ``feature`` may be ``feature_key`` or ``student``.
``cloud/*.log``, ``cloud/logs/**``, ``cloud/workflow-logs/**``
    Deployment workflow logs; only the final 512 KiB of each log is read.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from pydantic import JsonValue

from scripts.devtools.review.bounded import DEFAULT_LOG_TAIL_BYTES, EvidenceReader
from scripts.devtools.review.checklist import (
    SHA_PATTERN,
    URL_PATTERN,
    Checklist,
    first_string,
    summarise,
)
from shared_contracts.evidence_review import EvidenceReviewBundle

STUDENTS = tuple(f"student-{number}" for number in range(1, 6))
REPORT = "cloud/cloud-deployment-report.md"
DECISION_FILE = "cloud/release-decision.md"
PASSING = frozenset({"passed", "pass", "success", "succeeded", "ok", "true"})
ERROR_LINE = re.compile(r"##\[error\]|Process completed with exit code [1-9]|^\s*ERROR\b", re.M)
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"AccountKey=[A-Za-z0-9+/=]{20,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)client_secret\W{1,4}[A-Za-z0-9~._-]{16,}"),
)
FEATURE_ALIASES = {
    student: (student, f"feature-{student[-1]}", f"f{student[-1]}") for student in STUDENTS
}


def collect(reader: EvidenceReader) -> EvidenceReviewBundle:
    """Build the cloud checklist from the report, smoke output and workflow logs."""
    checklist = Checklist(reader)
    report = reader.read_text(REPORT)
    report_text = report.text or ""
    report_commit = SHA_PATTERN.search(report_text)
    report_urls = sorted(set(URL_PATTERN.findall(report_text)))
    checklist.add(
        "cloud.report",
        "Cloud deployment report names the public URL and deployed commit",
        passed=report.text is not None and bool(report_urls) and report_commit is not None,
        detail=(
            f"Report records {len(report_urls)} URL(s) and commit {report_commit.group(0)[:12]}."
            if report.text is not None and report_urls and report_commit
            else f"Evidence gap: {REPORT} is {report.status.value}."
            if report.text is None
            else "The report does not record "
            + " and ".join(
                label
                for label, found in (("a URL", report_urls), ("a commit SHA", report_commit))
                if not found
            )
            + "."
        ),
        refs=(REPORT,),
    )
    smoke_paths = reader.glob("cloud", ("smoke*.json",), max_depth=2) or ["cloud/smoke.json"]
    smoke: dict[str, JsonValue] = {}
    checks: list[dict[str, JsonValue]] = []
    for path in smoke_paths:
        _, value = reader.read_json(path)
        if isinstance(value, dict):
            smoke = smoke or value
            raw_checks = value.get("checks")
            if isinstance(raw_checks, list):
                checks.extend(item for item in raw_checks if isinstance(item, dict))
    smoke_refs = tuple(smoke_paths)
    failed_checks = [_label(check) for check in checks if not _passed(check)]
    checklist.add(
        "cloud.smoke",
        "Public smoke test output is present and every case passed",
        passed=bool(checks) and not failed_checks,
        detail=(
            f"{len(checks)} smoke case(s) passed."
            if checks and not failed_checks
            else "Evidence gap: no smoke output with a checks list was found."
            if not checks
            else f"Failed smoke cases: {summarise(failed_checks)}."
        ),
        refs=smoke_refs,
    )
    frontend = [check for check in checks if _category(check) == "frontend"]
    checklist.add(
        "cloud.frontend",
        "Deployed frontend UI is reachable",
        passed=bool(frontend) and all(_passed(check) for check in frontend),
        detail=(
            f"{len(frontend)} frontend case(s) passed."
            if frontend and all(_passed(check) for check in frontend)
            else "No passing frontend reachability case recorded."
        ),
        refs=smoke_refs,
    )
    crud: dict[str, JsonValue] = {}
    for student in STUDENTS:
        cases = [
            check for check in checks if _category(check) == "crud" and _feature(check) == student
        ]
        ok = bool(cases) and all(_passed(check) for check in cases)
        crud[student] = "passed" if ok else "failed" if cases else "missing"
        checklist.add(
            f"cloud.crud.{student}",
            f"{student} CRUD smoke case passed on the cloud deployment",
            passed=ok,
            detail=(
                f"{len(cases)} CRUD case(s) passed."
                if ok
                else f"CRUD case failed: {summarise(_label(check) for check in cases)}."
                if cases
                else "No CRUD case recorded for this feature."
            ),
            refs=smoke_refs,
        )
    ai_flag = smoke.get("ai_enabled")
    ai_cases = [check for check in checks if _category(check) == "ai_disabled"]
    ai_off = ai_flag is False or (
        ai_flag is None and bool(ai_cases) and all(_passed(check) for check in ai_cases)
    )
    if ai_flag is False and ai_cases:
        ai_off = all(_passed(check) for check in ai_cases)
    checklist.add(
        "cloud.ai-disabled",
        "AI-mode, MCP, RAG and Multi-Agent are disabled in the baseline deployment",
        passed=ai_off,
        detail=(
            "Smoke output records the AI tier as disabled."
            if ai_off
            else "Smoke output reports the AI tier as enabled."
            if ai_flag is True
            else "No evidence that the AI tier is disabled."
        ),
        refs=smoke_refs,
    )
    commit = first_string(smoke, "commit_sha", "commit", "sha")
    images = smoke.get("images")
    image_map = (
        {str(key): str(value) for key, value in sorted(images.items())}
        if isinstance(images, dict)
        else {}
    )
    mismatched = [
        f"{service}={reference}"
        for service, reference in image_map.items()
        if not _pinned(reference, commit)
    ]
    checklist.add(
        "cloud.images",
        "Deployed images are pinned to the reviewed commit or an immutable digest",
        passed=bool(image_map) and commit is not None and not mismatched,
        detail=(
            f"{len(image_map)} image(s) pinned to {commit[:12]} or a digest."
            if image_map and commit and not mismatched
            else "Smoke output records no image list or commit SHA."
            if not image_map or commit is None
            else f"Images not pinned to the commit: {summarise(mismatched)}."
        ),
        refs=smoke_refs,
    )
    checklist.add(
        "cloud.commit-consistency",
        "Report and smoke output name the same commit",
        passed=report_commit is not None
        and commit is not None
        and report_commit.group(0) == commit.lower(),
        detail=(
            "Report and smoke output agree."
            if report_commit and commit and report_commit.group(0) == commit.lower()
            else "The commit is missing from the report or smoke output, or they differ."
        ),
        refs=(REPORT, *smoke_refs),
    )
    base_url = first_string(smoke, "base_url", "url")
    checklist.add(
        "cloud.https",
        "Public endpoint is served over HTTPS",
        passed=base_url is not None and base_url.startswith("https://"),
        required=False,
        detail=f"Base URL: {base_url or 'not recorded'}.",
        refs=smoke_refs,
    )
    logs = _logs(reader, checklist)
    return checklist.bundle(
        "cloud",
        {
            "base_url": base_url,
            "commit": commit,
            "report_urls": list(report_urls[:5]),
            "smoke_cases": len(checks),
            "smoke_failed": len(failed_checks),
            "crud": crud,
            "ai_enabled": ai_flag if isinstance(ai_flag, bool) else None,
            "images": len(image_map),
            "logs": logs,
        },
    )


def _logs(reader: EvidenceReader, checklist: Checklist) -> dict[str, JsonValue]:
    paths = sorted(
        {
            *reader.glob("cloud", ("*.log",), max_depth=1),
            *reader.glob("cloud/logs", ("*.log", "*.txt"), max_depth=3),
            *reader.glob("cloud/workflow-logs", ("*.log", "*.txt"), max_depth=3),
        }
    )
    errors: list[str] = []
    secrets: list[str] = []
    readable = 0
    for path in paths:
        loaded = reader.read_text(path, tail_bytes=DEFAULT_LOG_TAIL_BYTES)
        if loaded.text is None:
            continue
        readable += 1
        for number, line in enumerate(loaded.text.splitlines(), start=1):
            if ERROR_LINE.search(line):
                errors.append(f"{path}#line-{number}")
            if any(pattern.search(line) for pattern in SECRET_PATTERNS):
                secrets.append(f"{path}#line-{number}")
    checklist.add(
        "cloud.workflow",
        "Deployment workflow logs are present and show no errors",
        passed=readable > 0 and not errors,
        detail=(
            f"{readable} log file(s) contain no error annotations or failing exit codes."
            if readable and not errors
            else "Evidence gap: no readable deployment workflow log."
            if not readable
            else f"{len(errors)} error line(s), first at {errors[0]}."
        ),
        refs=(*paths[:5], *errors[:5]),
    )
    checklist.add(
        "cloud.log-secrets",
        "Workflow logs expose no secret-like values",
        passed=readable > 0 and not secrets,
        detail=(
            "No private keys, account keys or provider tokens found."
            if readable and not secrets
            else "Evidence gap: no readable deployment workflow log."
            if not readable
            else f"Secret-like value at {summarise(secrets)}; rotate it and purge the log."
        ),
        refs=(*paths[:5], *secrets[:5]),
    )
    return {"files": len(paths), "readable": readable, "error_lines": len(errors)}


def _passed(check: Mapping[str, JsonValue]) -> bool:
    value = check.get("passed")
    if isinstance(value, bool):
        return value
    status = first_string(check, "status", "outcome", "result")
    return status is not None and status.lower() in PASSING


def _category(check: Mapping[str, JsonValue]) -> str:
    category = (first_string(check, "category", "kind", "type") or "").lower()
    name = (first_string(check, "name", "id") or "").lower()
    if category in {"frontend", "home", "ui"} or (not category and "home" in name):
        return "frontend"
    if category == "crud" or (not category and "crud" in name):
        return "crud"
    if category in {"ai_disabled", "ai-disabled", "ai"} or (
        not category and "ai" in name.split() and "disabled" in name
    ):
        return "ai_disabled"
    return category or "other"


def _feature(check: Mapping[str, JsonValue]) -> str | None:
    value = (first_string(check, "feature", "feature_key", "student") or "").lower()
    name = (first_string(check, "name", "id") or "").lower()
    for student, aliases in FEATURE_ALIASES.items():
        if any(value == alias or value.startswith(f"{alias}-") for alias in aliases):
            return student
        if not value and any(re.search(rf"\b{alias}\b", name) for alias in aliases):
            return student
    return None


def _pinned(reference: str, commit: str | None) -> bool:
    if "@sha256:" in reference:
        return True
    tag = reference.rsplit(":", 1)[-1] if ":" in reference.rsplit("/", 1)[-1] else ""
    return commit is not None and len(tag) >= 7 and commit.lower().startswith(tag.lower())


def _label(check: Mapping[str, JsonValue]) -> str:
    return first_string(check, "name", "id") or "unnamed case"
