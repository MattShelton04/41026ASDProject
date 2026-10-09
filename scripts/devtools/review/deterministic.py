"""Checklist-derived review used by ``--deterministic`` runs and explicit fallbacks.

It never interprets evidence beyond the deterministic checklist: every finding is a failed
check, every recommendation is the fixed remediation for that check kind, and the verdict is
exactly the checklist verdict.
"""

from __future__ import annotations

from shared_contracts.evidence_review import (
    CheckStatus,
    EvidenceCheck,
    EvidenceReviewBundle,
    EvidenceReviewFinding,
    EvidenceReviewOutput,
    EvidenceReviewRisk,
    ReviewSeverity,
)

MODE_TITLES = {
    "multi-agent": "Multi-Agent Workflow Review",
    "testing": "Testing Report Review",
    "cloud": "Cloud Deployment Report Review",
}
REMEDIATION = {
    "evidence": "Export the student's workflow runs from the Multi-Agent Server "
    "(workflow_history.jsonl and coordination_audit.jsonl) into the evidence folder.",
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
    "secrets": "Remove or rotate real secrets; audit false positives in .secrets.baseline.",
    "dependencies": "Upgrade the vulnerable dependency, or record the accepted vulnerability ID "
    "and its justification in the security report.",
    "dependencies-clean": "Schedule upgrades for dependencies with accepted vulnerabilities.",
    "run": "Re-collect CI evidence with the Actions run URL and commit SHA.",
    "green": "Fix the failing CI job and re-collect evidence from a green run.",
    "endpoints": "Add or fix endpoint tests so at least two endpoint functions pass in CI.",
    "junit": "Publish the JUnit totals line from shared_testkit.junit_summary in the CI evidence.",
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


def check_kind(check: EvidenceCheck) -> str:
    """Return the remediation key for a check id such as ``ci.student-1.green``."""
    parts = check.id.split(".")
    if parts[0] == "cloud" and len(parts) >= 2 and parts[1] == "crud":
        return "crud"
    return parts[-1]


def deterministic_review(bundle: EvidenceReviewBundle) -> EvidenceReviewOutput:
    """Turn the checklist into findings, risks and recommendations without a model."""
    failed = [check for check in bundle.checks if check.status is CheckStatus.FAILED]
    findings = [
        EvidenceReviewFinding(
            severity=ReviewSeverity.HIGH if check.required else ReviewSeverity.MEDIUM,
            area=check.id.split(".")[0] if bundle.mode != "testing" else check.id.rsplit(".", 1)[0],
            message=f"{check.title}: {check.detail}"[:1_000],
            evidence_refs=(check.id, *check.evidence_refs[:9]),
        )
        for check in failed[:30]
    ]
    if not findings:
        findings.append(
            EvidenceReviewFinding(
                severity=ReviewSeverity.INFO,
                area=bundle.mode,
                message=f"All {len(bundle.checks)} deterministic checks passed.",
                evidence_refs=tuple(check.id for check in bundle.checks[:10]),
            )
        )
    risks = [
        EvidenceReviewRisk(
            severity=ReviewSeverity.MEDIUM,
            description=f"Advisory check not met: {check.title}.",
            mitigation=REMEDIATION.get(check_kind(check), "Review the evidence manually."),
        )
        for check in failed
        if not check.required
    ][:14]
    if bundle.compacted:
        risks.append(
            EvidenceReviewRisk(
                severity=ReviewSeverity.LOW,
                description="Collected facts were compacted to fit the run budget.",
                mitigation="Read the full facts in the review report before deciding.",
            )
        )
    recommendations = list(
        dict.fromkeys(
            REMEDIATION.get(check_kind(check), f"Resolve {check.id}.")
            for check in failed
            if check.required
        )
    )[:15]
    required_failed = sum(1 for check in failed if check.required)
    unread = sum(1 for item in bundle.inputs if item.status.value != "read")
    summary = (
        f"{MODE_TITLES[bundle.mode]}: {len(bundle.checks) - len(failed)} of "
        f"{len(bundle.checks)} checks passed across {len(bundle.inputs)} evidence file(s); "
        f"{required_failed} required check(s) failed and {unread} input(s) were missing or "
        "unreadable. Verdict taken from the deterministic checklist without a model."
    )
    return EvidenceReviewOutput(
        summary=summary,
        findings=tuple(findings),
        risks=tuple(risks),
        recommendations=tuple(recommendations),
        verdict=bundle.checklist_verdict(),
    )
