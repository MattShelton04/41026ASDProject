"""Collect cloud deployment evidence for the Cloud Deployment Report Review.

The evidence is what ``cloud-deployment.yml`` writes, copied below the evidence root as
docs/release-2/evidence/cloud/README.md describes (``cloud/release-decision.md`` is written by the
human decision command and is deliberately not reviewed):

``cloud/cloud-deployment-report.md``
    ``scripts/cloud_deployment_report.py``: names the public URL and the deployed commit SHA.
``cloud/cloud-smoke.json`` (or ``cloud/smoke/cloud-smoke.json``; legacy ``cloud/smoke*.json``)
    ``scripts/cloud_smoke.py`` schema version 2::

        {"schema_version": 2, "base_url": "https://...", "commit_sha": "<40 hex>",
         "image_tag": "<tag>", "images": {"f1-backend": "<acr>/propertyscope/f1-backend:<tag>"},
         "images_source": "...", "ai_enabled": false, "ai_state": "disabled", "passed": true,
         "checks": [{"name": "CRUD source definition: update", "owner": "student-1",
                     "category": "crud", "operation": "update", "passed": true, ...}]}

    Categories are ``frontend``, ``health``, ``crud``, ``cleanup`` and ``ai``. Older documents may
    use ``feature``/``feature_key``/``student`` for the owner, ``ai_disabled`` for the AI
    category, and ``status``/``outcome``/``result`` set to ``passed``/``success`` for ``passed``.
``cloud/release-gate.json`` (or ``cloud/gate/release-gate.json``)
    ``scripts/verify_release_gate.py``: Integration CI and Student 1..5 CI green for the commit.
``cloud/image-build.json`` (or ``cloud/build/image-build.json``, advisory)
    The workflow's Docker build and validation job: the images built for the commit.
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
from scripts.verify_release_gate import GATE_JSON, REQUIRED_WORKFLOW_NAMES
from shared_contracts.evidence_review import EvidenceReviewBundle

STUDENTS = tuple(f"student-{number}" for number in range(1, 6))
REPORT = "cloud/cloud-deployment-report.md"
DECISION_FILE = "cloud/release-decision.md"
SMOKE_FILE = "cloud-smoke.json"
LEGACY_SMOKE_FILES = ("smoke*.json",)
BUILD_FILE = "image-build.json"
PASSING = frozenset({"passed", "pass", "success", "succeeded", "ok", "true"})
# Every CRUD case must at least create, read, delete and confirm the delete.
REQUIRED_CRUD_OPERATIONS = ("create", "read", "delete", "confirm-deleted")
ERROR_LINE = re.compile(
    r"##\[error\]|Process completed with exit code [1-9]|^\s*ERROR\b|^\[deploy\.sh\] ERROR:", re.M
)
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"AccountKey=[A-Za-z0-9+/=]{20,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)client_secret\W{1,4}[A-Za-z0-9~._-]{16,}"),
)
SHARED = "shared"
SMOKE_GATE = "cloud.smoke-output"
LOGS_GATE = "cloud.logs"
FEATURE_ALIASES = {
    student: (student, f"feature-{student[-1]}", f"f{student[-1]}") for student in STUDENTS
}


def collect(reader: EvidenceReader) -> EvidenceReviewBundle:
    """Build the cloud checklist from the report, gate, smoke output and workflow logs."""
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
        owner=SHARED,
    )
    smoke_path, extra_smoke = _smoke_paths(reader)
    _, value = reader.read_json(smoke_path)
    smoke: dict[str, JsonValue] = value if isinstance(value, dict) else {}
    raw_checks = smoke.get("checks")
    checks = (
        [item for item in raw_checks if isinstance(item, dict)]
        if isinstance(raw_checks, list)
        else []
    )
    smoke_refs = (smoke_path,)
    commit = first_string(smoke, "commit_sha", "commit", "sha")
    commit = commit.lower() if commit else None
    expected_commit = commit or (report_commit.group(0) if report_commit else None)
    gate = _release_gate(reader, checklist, expected_commit)
    build = _image_build(reader, checklist, expected_commit)
    failed_checks = [_label(check) for check in checks if not _passed(check)]
    ignored = (
        f" Also found {summarise(extra_smoke)}; only {smoke_path} is reviewed."
        if extra_smoke
        else ""
    )
    # Narrow gate: the smoke document exists. Every smoke-derived check depends on it, so a
    # missing document is one root cause rather than a failure per feature.
    checklist.add(
        SMOKE_GATE,
        "Public smoke test output is present",
        passed=bool(checks),
        detail=(
            f"{smoke_path} records {len(checks)} smoke case(s)."
            if checks
            else f"Evidence gap: no smoke output with a checks list at {smoke_path}."
        )
        + ignored,
        refs=smoke_refs,
        owner=SHARED,
    )
    checklist.add(
        "cloud.smoke",
        "Every public smoke case passed",
        passed=not failed_checks,
        detail=(
            f"{len(checks)} smoke case(s) passed."
            if not failed_checks
            else f"Failed smoke cases: {summarise(failed_checks)}."
        ),
        refs=smoke_refs,
        prerequisite=SMOKE_GATE,
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
        prerequisite=SMOKE_GATE,
    )
    crud: dict[str, JsonValue] = {}
    crud_operations: dict[str, JsonValue] = {}
    for student in STUDENTS:
        cases = [
            check for check in checks if _category(check) == "crud" and _feature(check) == student
        ]
        operations = [first_string(check, "operation") for check in cases]
        recorded = [operation for operation in operations if operation]
        # Documents without operations (schema 1) cannot prove the cycle; judge them on outcome.
        absent = [op for op in REQUIRED_CRUD_OPERATIONS if op not in recorded] if recorded else []
        ok = bool(cases) and all(_passed(check) for check in cases) and not absent
        # A skipped case (a precondition outside the deployment) is unproven, not broken.
        skipped = [check for check in cases if check.get("skipped") is True]
        crud[student] = (
            "passed"
            if ok
            else "skipped"
            if cases and len(skipped) == len(cases)
            else "failed"
            if cases
            else "missing"
        )
        crud_operations[student] = list(dict.fromkeys(recorded))
        checklist.add(
            f"cloud.crud.{student}",
            f"{student} CRUD smoke case passed on the cloud deployment",
            passed=ok,
            detail=(
                f"{len(cases)} CRUD step(s) passed"
                + (f": {', '.join(dict.fromkeys(recorded))}." if recorded else ".")
                if ok
                else "CRUD case skipped: "
                + (first_string(skipped[0], "detail") or "precondition unmet").removeprefix(
                    "skipped: "
                )
                + "."
                if crud[student] == "skipped"
                else f"CRUD case failed: {summarise(_label(c) for c in cases if not _passed(c))}."
                if cases and not all(_passed(check) for check in cases)
                else f"CRUD case is missing step(s): {', '.join(absent)}."
                if cases
                else "No CRUD case recorded for this feature."
            ),
            refs=smoke_refs,
            owner=student,
            prerequisite=SMOKE_GATE,
        )
    ai_flag = smoke.get("ai_enabled")
    ai_state = first_string(smoke, "ai_state")
    ai_cases = [check for check in checks if _category(check) == "ai_disabled"]
    cases_ok = bool(ai_cases) and all(_passed(check) for check in ai_cases)
    # With an ai_enabled field an explicit observation is required, and any AI case must pass.
    explicit = ai_flag is False and (not ai_cases or cases_ok)
    ai_off = explicit if "ai_enabled" in smoke else cases_ok
    checklist.add(
        "cloud.ai-disabled",
        "AI-mode, MCP, RAG and Multi-Agent are disabled in the baseline deployment",
        passed=ai_off,
        detail=(
            "Smoke output records the AI tier as disabled"
            + (f" ({ai_state})." if ai_state else ".")
            if ai_off
            else "Smoke output reports the AI tier as enabled."
            if ai_flag is True
            else f"The AI tier was not shown to be disabled (observed: {ai_state})."
            if ai_state
            else "No evidence that the AI tier is disabled."
        ),
        refs=smoke_refs,
        prerequisite=SMOKE_GATE,
    )
    images = smoke.get("images")
    image_map = (
        {str(key): str(value) for key, value in sorted(images.items())}
        if isinstance(images, dict)
        else {}
    )
    images_source = first_string(smoke, "images_source")
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
            f"{len(image_map)} image(s) pinned to {commit[:12]} or a digest"
            + (f" (from {images_source})." if images_source else ".")
            if image_map and commit and not mismatched
            else "Smoke output records no image list or commit SHA."
            if not image_map or commit is None
            else f"Images not pinned to the commit: {summarise(mismatched)}."
        ),
        refs=smoke_refs,
        prerequisite=SMOKE_GATE,
    )
    checklist.add(
        "cloud.commit-consistency",
        "Report and smoke output name the same commit",
        passed=report_commit is not None
        and commit is not None
        and report_commit.group(0) == commit,
        detail=(
            "Report and smoke output agree."
            if report_commit and commit and report_commit.group(0) == commit
            else "The commit is missing from the report or smoke output, or they differ."
        ),
        refs=(REPORT, *smoke_refs),
        prerequisite=("cloud.report", SMOKE_GATE),
    )
    base_url = first_string(smoke, "base_url", "url")
    checklist.add(
        "cloud.https",
        "Public endpoint is served over HTTPS",
        passed=base_url is not None and base_url.startswith("https://"),
        required=False,
        detail=f"Base URL: {base_url or 'not recorded'}.",
        refs=smoke_refs,
        prerequisite=SMOKE_GATE,
    )
    logs = _logs(reader, checklist)
    return checklist.bundle(
        "cloud",
        {
            "base_url": base_url,
            "commit": commit,
            "report_urls": list(report_urls[:5]),
            "smoke_file": smoke_path,
            "smoke_schema_version": smoke.get("schema_version"),
            "smoke_cases": len(checks),
            "smoke_failed": len(failed_checks),
            "crud": crud,
            "crud_operations": crud_operations,
            "ai_enabled": ai_flag if isinstance(ai_flag, bool) else None,
            "ai_state": ai_state,
            "images": len(image_map),
            "images_source": images_source,
            "release_gate": gate,
            "image_build": build,
            "logs": logs,
        },
    )


def _smoke_paths(reader: EvidenceReader) -> tuple[str, list[str]]:
    """The smoke document to review (current name first), and any others found."""
    paths = reader.glob("cloud", (SMOKE_FILE,), max_depth=2) or reader.glob(
        "cloud", LEGACY_SMOKE_FILES, max_depth=2
    )
    paths = sorted(paths, key=lambda path: (path.count("/"), path))
    if not paths:
        return f"cloud/{SMOKE_FILE}", []
    return paths[0], paths[1:]


def _first_path(reader: EvidenceReader, name: str) -> str:
    paths = sorted(
        reader.glob("cloud", (name,), max_depth=2), key=lambda path: (path.count("/"), path)
    )
    return paths[0] if paths else f"cloud/{name}"


def _release_gate(
    reader: EvidenceReader, checklist: Checklist, commit: str | None
) -> dict[str, JsonValue]:
    path = _first_path(reader, GATE_JSON)
    loaded, value = reader.read_json(path)
    gate: Mapping[str, JsonValue] = value if isinstance(value, dict) else {}
    raw = gate.get("workflows")
    workflows = {
        str(item.get("workflow")): item
        for item in (raw if isinstance(raw, list) else [])
        if isinstance(item, dict)
    }
    missing = [name for name in REQUIRED_WORKFLOW_NAMES if name not in workflows]
    not_green = [
        f"{name} ({first_string(workflows[name], 'state', 'conclusion') or 'unknown'})"
        for name in REQUIRED_WORKFLOW_NAMES
        if name in workflows
        and not (
            workflows[name].get("passed") is True
            and first_string(workflows[name], "conclusion") == "success"
        )
    ]
    deploy_sha = (first_string(gate, "deploy_sha") or "").lower() or None
    same_commit = deploy_sha is not None and deploy_sha == commit
    passed = gate.get("passed") is True and not missing and not not_green and same_commit
    runs = [
        f"{name} #{workflows[name].get('run_number')}"
        f" at {str(workflows[name].get('head_sha') or '')[:7]}"
        f" ({workflows[name].get('relation')})"
        for name in REQUIRED_WORKFLOW_NAMES
        if name in workflows
    ]
    if passed:
        detail = f"All {len(REQUIRED_WORKFLOW_NAMES)} workflows green for {str(deploy_sha)[:12]}: "
        detail += "; ".join(runs) + "."
    elif not gate:
        detail = f"Evidence gap: {path} is {loaded.status.value}."
    elif missing:
        detail = f"The gate does not record {summarise(missing)}."
    elif not_green:
        detail = f"Not green: {summarise(not_green)}."
    elif not same_commit:
        detail = (
            f"The gate checked {deploy_sha or 'no commit'}, not the deployed commit "
            f"{commit or 'unknown'}."
        )
    else:
        detail = "The gate did not pass."
    checklist.add(
        "cloud.release-gate",
        "Integration CI and Student 1-5 CI were green for the deployed commit before deployment",
        passed=passed,
        detail=detail,
        refs=(path,),
        owner=SHARED,
    )
    return {
        "file": path,
        "passed": passed,
        "deploy_sha": deploy_sha,
        "workflows": {
            name: first_string(workflows[name], "state", "conclusion") for name in workflows
        },
    }


def _image_build(
    reader: EvidenceReader, checklist: Checklist, commit: str | None
) -> dict[str, JsonValue]:
    path = _first_path(reader, BUILD_FILE)
    loaded, value = reader.read_json(path)
    build: Mapping[str, JsonValue] = value if isinstance(value, dict) else {}
    raw = build.get("images")
    images = [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []
    built_commit = (first_string(build, "commit_sha") or "").lower() or None
    passed = build.get("passed") is True and bool(images) and built_commit == commit
    checklist.add(
        "cloud.build",
        "Docker images were built and validated for the deployed commit",
        passed=passed,
        required=False,
        detail=(
            f"{len(images)} image(s) built and validated for {str(built_commit)[:12]}."
            if passed
            else f"Evidence gap: {path} is {loaded.status.value}."
            if not build
            else f"Build record for {built_commit or 'no commit'} with {len(images)} image(s) "
            f"does not show a passing build of {commit or 'the deployed commit'}."
        ),
        refs=(path,),
        owner=SHARED,
    )
    return {"file": path, "passed": passed, "images": len(images)}


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
        LOGS_GATE,
        "Deployment workflow logs are present",
        passed=readable > 0,
        detail=(
            f"{readable} readable log file(s)."
            if readable
            else "Evidence gap: no readable deployment workflow log."
        ),
        refs=paths[:5],
        owner=SHARED,
    )
    checklist.add(
        "cloud.workflow",
        "Deployment workflow logs show no errors",
        passed=not errors,
        detail=(
            f"{readable} log file(s) contain no error annotations or failing exit codes."
            if not errors
            else f"{len(errors)} error line(s), first at {errors[0]}."
        ),
        refs=(*paths[:5], *errors[:5]),
        prerequisite=LOGS_GATE,
    )
    checklist.add(
        "cloud.log-secrets",
        "Workflow logs expose no secret-like values",
        passed=not secrets,
        detail=(
            "No private keys, account keys or provider tokens found."
            if not secrets
            else f"Secret-like value at {summarise(secrets)}; rotate it and purge the log."
        ),
        refs=(*paths[:5], *secrets[:5]),
        prerequisite=LOGS_GATE,
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
    # cloud_smoke.py writes "ai"; its AI check passes only when the tier is off (or, with
    # --expect-ai, reachable, which ai_enabled then records as true).
    if category in {"ai_disabled", "ai-disabled", "ai"} or (
        not category and "ai" in name.split() and "disabled" in name
    ):
        return "ai_disabled"
    return category or "other"


def _feature(check: Mapping[str, JsonValue]) -> str | None:
    value = (first_string(check, "owner", "feature", "feature_key", "student") or "").lower()
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
