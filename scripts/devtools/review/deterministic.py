"""Checklist-derived review used by ``--deterministic`` runs and explicit fallbacks.

It never interprets evidence beyond the deterministic checklist. Findings follow root causes:
each failed check is one finding, except that owners whose evidence was not submitted share one
finding per check kind (for example "Evidence not submitted by student-2 and student-3"), with
the checks it blocked counted per owner instead of listed as failures. Every recommendation is
the fixed remediation for its check kind, attributed to the owner when evidence is missing, and
the verdict is exactly the checklist verdict.
"""

from __future__ import annotations

from collections.abc import Sequence

from shared_contracts.evidence_review import (
    UNASSIGNED_OWNER,
    CheckStatus,
    EvidenceCheck,
    EvidenceReviewBundle,
    EvidenceReviewFinding,
    EvidenceReviewOutput,
    EvidenceReviewRisk,
    OwnerStatus,
    ReviewSeverity,
    blocked_by_root,
    owner_coverage,
)

MAX_FINDINGS = 30  # EvidenceReviewOutput.findings max_length
MAX_RISKS = 15  # EvidenceReviewOutput.risks max_length
MAX_REFS = 10  # EvidenceReviewFinding.evidence_refs max_length
MODE_TITLES = {
    "multi-agent": "Multi-Agent Workflow Review",
    "testing": "Testing Report Review",
    "cloud": "Cloud Deployment Report Review",
}
EVIDENCE_COVERAGE_AREA = "evidence coverage"
REMEDIATION = {
    "evidence": "Export the student's workflow runs from the Multi-Agent Server "
    "(workflow_history.jsonl and coordination_audit.jsonl) into the evidence folder.",
    "testing:evidence": "Collect the CI endpoint evidence with `uv run python "
    "scripts/collect_ci_evidence.py --student N`, which writes ci/student-N.md and "
    "ci/student-N/run.log.",
    "stages": "Re-run the workflow through the Multi-Agent Server so Planner, Worker and Reviewer "
    "stages are recorded before human review, then re-export it.",
    "human-decision": "Record a human decision (approve, correct, partial or reject) with the "
    "reviewer's name through the UI or CLI, then re-export the run.",
    "transitions": "Investigate the illegal or out-of-order transition; export the run again "
    "from the server rather than editing JSONL by hand.",
    "tool-allowlist": "Restrict the workflow template to read-only allowlisted tools and make "
    "the export record the template's allowed_tools.",
    "handoffs": "Emit agent.handoff audit events for planner to worker, worker to reviewer and "
    "reviewer to human.",
    "correlation": "Export history and audit together for each run so both files cover the same "
    "run IDs.",
    "report": "Regenerate the report with `uv run scripts/dev.py security report` (security) or "
    "the cloud deployment workflow (cloud) so it records all required facts.",
    "traceability": "Record the scanned commit SHA in the security report.",
    "ruff": "Fix each Ruff S finding, or add a reasoned `# noqa` and explain it in the report.",
    "ruff-owners": "Each named owner fixes or justifies their pending Ruff security findings.",
    "secrets": "Remove or rotate real secrets; audit false positives in .secrets.baseline.",
    "dependencies": "Upgrade the vulnerable dependency, or record the accepted vulnerability ID "
    "and its justification in the security report.",
    "dependencies-clean": "Schedule upgrades for dependencies with accepted vulnerabilities.",
    "run": "Re-collect CI evidence with the Actions run URL and commit SHA.",
    "green": "Fix the failing CI job and re-collect evidence from a green run.",
    "endpoints": "Add or fix endpoint tests so at least two endpoint functions pass in CI.",
    "junit": "Publish the JUnit totals line from shared_testkit.junit_summary in the CI evidence.",
    "log": "Re-run `uv run python scripts/collect_ci_evidence.py --student N` so the endpoint "
    "run log is retained beside the CI evidence.",
    "smoke": "Re-run the public smoke test after fixing the failing case.",
    "frontend": "Restore public access to the shared frontend before release.",
    "crud": "Fix the feature's CRUD path on the cloud deployment and re-run its smoke case.",
    "ai-disabled": "Turn the cloud AI tier off for the baseline release and re-run the smoke test.",
    "images": "Deploy images tagged with the reviewed commit SHA or pinned by digest.",
    "commit-consistency": "Regenerate the report and smoke output from the same deployment run.",
    "https": "Serve the public endpoint over HTTPS.",
    "workflow": "Fix the deployment workflow errors and attach the logs of a successful run.",
    "log-secrets": "Rotate the exposed credential and remove it from stored workflow logs.",
}
"""Fixed remediation per check kind; a ``<mode>:<kind>`` key overrides the plain kind."""


def check_kind(check: EvidenceCheck) -> str:
    """Return the remediation key for a check id such as ``ci.student-1.green``."""
    parts = check.id.split(".")
    if parts[0] == "cloud" and len(parts) >= 2 and parts[1] == "crud":
        return "crud"
    return parts[-1]


def remediation(mode: str, check: EvidenceCheck) -> str:
    """Return the fixed remediation for a check, preferring a mode-specific entry."""
    kind = check_kind(check)
    return REMEDIATION.get(f"{mode}:{kind}") or REMEDIATION.get(kind) or f"Resolve {check.id}."


def join_names(names: Sequence[str]) -> str:
    """Render ``a``, ``a and b`` or ``a, b and c``."""
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


class _RootCause:
    """One failed check, or several identical evidence gaps across owners."""

    def __init__(self, checks: list[EvidenceCheck], *, not_submitted: bool) -> None:
        self.checks = checks
        self.not_submitted = not_submitted

    @property
    def required(self) -> bool:
        return any(check.required for check in self.checks)

    @property
    def owners(self) -> list[str]:
        return list(dict.fromkeys(check.owner or UNASSIGNED_OWNER for check in self.checks))


def root_causes(bundle: EvidenceReviewBundle) -> list[_RootCause]:
    """Group failed checks into root causes, required ones first, otherwise checklist order."""
    roots = blocked_by_root(bundle.checks)
    not_submitted = {
        item.owner
        for item in owner_coverage(bundle)
        if item.status is OwnerStatus.EVIDENCE_NOT_SUBMITTED
    }
    groups: dict[tuple[str, ...], _RootCause] = {}
    for check in bundle.checks:
        if check.status is not CheckStatus.FAILED:
            continue
        missing = check.id in roots and (check.owner or UNASSIGNED_OWNER) in not_submitted
        key = ("missing", check_kind(check), str(check.required)) if missing else (check.id,)
        if key in groups:
            groups[key].checks.append(check)
        else:
            groups[key] = _RootCause([check], not_submitted=missing)
    return sorted(groups.values(), key=lambda cause: not cause.required)


def deterministic_review(bundle: EvidenceReviewBundle) -> EvidenceReviewOutput:
    """Turn the checklist into findings, risks and recommendations without a model."""
    roots = blocked_by_root(bundle.checks)
    causes = root_causes(bundle)
    # Beyond the schema's finding limit the remaining root causes are summarised in one final
    # finding, so no failed check silently disappears from the review.
    shown = causes if len(causes) <= MAX_FINDINGS else causes[: MAX_FINDINGS - 1]
    findings = [_finding(bundle, cause, roots) for cause in shown]
    overflow = [check for cause in causes[len(shown) :] for check in cause.checks]
    if overflow:
        findings.append(
            EvidenceReviewFinding(
                severity=(
                    ReviewSeverity.HIGH
                    if any(check.required for check in overflow)
                    else ReviewSeverity.MEDIUM
                ),
                area=bundle.mode,
                message=(
                    f"{len(overflow)} further failed check(s), listed in the checklist: "
                    + ", ".join(check.id for check in overflow)
                )[:1_000],
                evidence_refs=tuple(check.id for check in overflow[:MAX_REFS]),
            )
        )
    if not findings:
        findings.append(
            EvidenceReviewFinding(
                severity=ReviewSeverity.INFO,
                area=bundle.mode,
                message=f"All {len(bundle.checks)} deterministic checks passed.",
                evidence_refs=tuple(check.id for check in bundle.checks[:MAX_REFS]),
            )
        )
    return EvidenceReviewOutput(
        summary=_summary(bundle),
        findings=tuple(findings),
        risks=tuple(_risks(bundle, roots)),
        recommendations=tuple(_recommendations(bundle, causes)),
        verdict=bundle.checklist_verdict(),
    )


def _finding(
    bundle: EvidenceReviewBundle, cause: _RootCause, roots: dict[str, tuple[str, ...]]
) -> EvidenceReviewFinding:
    first = cause.checks[0]
    severity = ReviewSeverity.HIGH if cause.required else ReviewSeverity.MEDIUM
    blocked = {check.id: len(roots.get(check.id, ())) for check in cause.checks}
    if cause.not_submitted:
        per_owner = ", ".join(
            f"{check.owner or UNASSIGNED_OWNER} {blocked[check.id]}" for check in cause.checks
        )
        message = (
            f"Evidence not submitted by {join_names(cause.owners)} "
            f"({', '.join(check.id for check in cause.checks)} failed). "
            f"{sum(blocked.values())} dependent check(s) were not evaluated ({per_owner}). "
            "This is missing owner evidence, not a defect in the checked behaviour. "
            f"{first.detail}"
        )
        refs = [check.id for check in cause.checks]
        refs += [ref for ref in first.evidence_refs if ref not in refs]
        return EvidenceReviewFinding(
            severity=severity,
            area=EVIDENCE_COVERAGE_AREA,
            message=message[:1_000],
            evidence_refs=tuple(refs[:MAX_REFS]),
        )
    message = f"{first.title}: {first.detail}"
    if blocked[first.id]:
        message += (
            f" {blocked[first.id]} dependent check(s) were not evaluated: "
            + ", ".join(roots[first.id])
            + "."
        )
    return EvidenceReviewFinding(
        severity=severity,
        area=first.id.split(".")[0] if bundle.mode != "testing" else first.id.rsplit(".", 1)[0],
        message=message[:1_000],
        evidence_refs=(first.id, *first.evidence_refs[: MAX_REFS - 1]),
    )


def _risks(
    bundle: EvidenceReviewBundle, roots: dict[str, tuple[str, ...]]
) -> list[EvidenceReviewRisk]:
    risks: list[EvidenceReviewRisk] = []
    blocked = [check for check in bundle.checks if check.status is CheckStatus.BLOCKED]
    if blocked:
        owners = list(dict.fromkeys(check.owner or UNASSIGNED_OWNER for check in blocked))
        required = any(check.required for check in blocked)
        risks.append(
            EvidenceReviewRisk(
                severity=ReviewSeverity.HIGH if required else ReviewSeverity.MEDIUM,
                description=(
                    f"{len(blocked)} check(s) were not evaluated because evidence from "
                    f"{join_names(owners)} is missing or unreadable, so the review cannot show "
                    "those controls work."
                )[:600],
                mitigation=(
                    f"{join_names(owners)} submit the missing evidence and the review is re-run; "
                    + (
                        "until then the checklist verdict stays fail."
                        if required
                        else "until then the gaps remain release risks."
                    )
                )[:600],
            )
        )
    risks += [
        EvidenceReviewRisk(
            severity=ReviewSeverity.MEDIUM,
            description=f"Advisory check not met: {check.title}.",
            mitigation=remediation(bundle.mode, check),
        )
        for check in bundle.checks
        if check.status is CheckStatus.FAILED and not check.required
    ]
    risks = risks[: MAX_RISKS - 1]
    if bundle.compacted:
        risks.append(
            EvidenceReviewRisk(
                severity=ReviewSeverity.LOW,
                description="Collected facts were compacted to fit the run budget.",
                mitigation="Read the full facts in the review report before deciding.",
            )
        )
    return risks


def _recommendations(bundle: EvidenceReviewBundle, causes: Sequence[_RootCause]) -> list[str]:
    items: list[str] = []
    for cause in causes:
        text = remediation(bundle.mode, cause.checks[0])
        if cause.not_submitted:
            text = f"{join_names(cause.owners)}: submit the missing evidence. {text}"
        items.append(text)
    return list(dict.fromkeys(items))[:15]


def _summary(bundle: EvidenceReviewBundle) -> str:
    counts = dict.fromkeys(CheckStatus, 0)
    for check in bundle.checks:
        counts[check.status] += 1
    required_failed = sum(
        1 for check in bundle.checks if check.required and check.status is CheckStatus.FAILED
    )
    unread = sum(1 for item in bundle.inputs if item.status.value != "read")
    blocked = (
        f" and {counts[CheckStatus.BLOCKED]} were not evaluated because a prerequisite failed"
        if counts[CheckStatus.BLOCKED]
        else ""
    )
    parts = [
        f"{MODE_TITLES[bundle.mode]}: {counts[CheckStatus.PASSED]} of {len(bundle.checks)} "
        f"checks passed, {counts[CheckStatus.FAILED]} failed ({required_failed} required)"
        f"{blocked}, across {len(bundle.inputs)} evidence file(s), {unread} of them missing or "
        "unreadable."
    ]
    coverage = owner_coverage(bundle)
    if coverage:
        by_status: dict[OwnerStatus, list[str]] = {}
        for item in coverage:
            by_status.setdefault(item.status, []).append(item.owner)
        parts.append(
            " ".join(
                f"{status.label.capitalize()}: {join_names(owners)}."
                for status, owners in by_status.items()
            )
        )
    parts.append("Verdict taken from the deterministic checklist without a model.")
    return " ".join(parts)[:1_500]
