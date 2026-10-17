"""Versioned contracts for the agentic loop's Release 2 evidence review modes.

A review mode collects bounded release evidence into an :class:`EvidenceReviewBundle` with a
deterministic checklist, then asks an AI-mode run (or a deterministic stand-in) for an
:class:`EvidenceReviewOutput`. The checklist sets a verdict floor: a model may be stricter than
the checklist but never more lenient, and every finding must cite evidence from the bundle.

A check may name the ``owner`` responsible for its evidence (``shared``, ``student-1`` ...) and
may be ``blocked``: not evaluated because a prerequisite check failed. ``blocked_by`` then names
the failed *root* check, so a group-wide review reports one missing export as one root cause
instead of a cascade of identical failures. :func:`owner_coverage` summarises the checks per
owner. Both fields are optional, so bundles and logs written before they existed still parse.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, JsonValue, model_validator

from shared_contracts.agent import PromptSet
from shared_contracts.base import ContractModel

REVIEW_FEATURE_KEY = "agentic-loop"
"""Feature key recorded on review runs so Activity history groups them apart from features."""

REVIEW_EVIDENCE_TOOL = "review.evidence.v1"
"""Read-only AI-mode tool that returns a review run's attached, schema-validated bundle."""

ReviewMode = Literal["multi-agent", "testing", "cloud"]
REVIEW_MODES: tuple[ReviewMode, ...] = ("multi-agent", "testing", "cloud")
REVIEW_PROMPT_SETS: Mapping[ReviewMode, PromptSet] = {
    "multi-agent": "review-multi-agent.v2",
    "testing": "review-testing.v2",
    "cloud": "review-cloud.v2",
}
"""The prompt set each mode uses for new reviews."""
REVIEW_PROMPT_SET_VERSIONS: Mapping[ReviewMode, tuple[PromptSet, ...]] = {
    "multi-agent": ("review-multi-agent.v1", "review-multi-agent.v2"),
    "testing": ("review-testing.v1", "review-testing.v2"),
    "cloud": ("review-cloud.v1", "review-cloud.v2"),
}
"""Every prompt set a mode's review runs may use; older versions stay valid for history."""
MAX_REVIEW_OBJECTIVE_CHARS = 15_000
"""Serialized bundle budget; AI-mode accepts objectives of at most 16,000 characters."""

ReviewIdentifier = Annotated[
    str, Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9_.-]*$")
]
ReviewOwner = Annotated[str, Field(min_length=1, max_length=50, pattern=r"^[a-z0-9][a-z0-9_.-]*$")]
EvidenceRef = Annotated[str, Field(min_length=1, max_length=300)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class ReviewSeverity(StrEnum):
    """Ordered impact of one finding or risk."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ReviewVerdict(StrEnum):
    """Overall release-readiness outcome of one review."""

    PASS = "pass"  # noqa: S105 - verdict label, not a credential
    PASS_WITH_RISKS = "pass_with_risks"  # noqa: S105 - verdict label, not a credential
    FAIL = "fail"


class CheckStatus(StrEnum):
    """Deterministic outcome of one checklist item."""

    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    """Not evaluated because a prerequisite check failed; ``blocked_by`` names that root."""


class OwnerStatus(StrEnum):
    """How completely one owner's checks were demonstrated, for the coverage table."""

    COMPLETE = "complete"
    EVIDENCE_NOT_SUBMITTED = "evidence_not_submitted"
    EVIDENCE_INCOMPLETE = "evidence_incomplete"
    BLOCKED_UPSTREAM = "blocked_upstream"
    FAILING = "failing"
    ADVISORY_GAPS = "advisory_gaps"

    @property
    def label(self) -> str:
        """Plain-language label used in review reports."""
        return _OWNER_STATUS_LABELS[self]


_OWNER_STATUS_LABELS = {
    OwnerStatus.COMPLETE: "complete",
    OwnerStatus.EVIDENCE_NOT_SUBMITTED: "evidence not submitted",
    OwnerStatus.EVIDENCE_INCOMPLETE: "evidence incomplete",
    OwnerStatus.BLOCKED_UPSTREAM: "blocked by another owner's evidence",
    OwnerStatus.FAILING: "required checks failing",
    OwnerStatus.ADVISORY_GAPS: "advisory gaps only",
}
UNASSIGNED_OWNER = "unassigned"
"""Coverage group for checks without an owner in a bundle where other checks have one."""


class InputStatus(StrEnum):
    """Whether a collector could read one evidence file inside its bounds."""

    READ = "read"
    MISSING = "missing"
    OVERSIZE = "oversize"
    INVALID = "invalid"


class EvidenceInput(ContractModel):
    """One allowlisted evidence file, identified by its path relative to the evidence root."""

    path: str = Field(min_length=1, max_length=300)
    status: InputStatus
    sha256: Sha256 | None = None
    bytes: int | None = Field(default=None, ge=0)
    detail: str | None = Field(default=None, max_length=300)


class EvidenceCheck(ContractModel):
    """One deterministic checklist item with the evidence that decided it.

    ``owner`` names who supplies the evidence (for example ``shared`` or ``student-2``).
    A ``blocked`` check was not evaluated; ``blocked_by`` is the failed root check that
    stopped it, never another blocked check.
    """

    id: ReviewIdentifier
    title: str = Field(min_length=1, max_length=200)
    status: CheckStatus
    required: bool = True
    detail: str = Field(min_length=1, max_length=500)
    evidence_refs: tuple[EvidenceRef, ...] = Field(default=(), max_length=10)
    owner: ReviewOwner | None = None
    blocked_by: ReviewIdentifier | None = None

    @model_validator(mode="after")
    def blocked_names_its_root(self) -> EvidenceCheck:
        """A blocked check names the root check that stopped it; no other status may."""
        if (self.status is CheckStatus.BLOCKED) is not (self.blocked_by is not None):
            raise ValueError("blocked_by is required for, and only allowed on, a blocked check")
        if self.blocked_by == self.id:
            raise ValueError("a check cannot block itself")
        return self


class EvidenceReviewBundle(ContractModel):
    """Bounded collected evidence, attached to a review run as its objective."""

    schema_version: Literal["1.0"] = "1.0"
    mode: ReviewMode
    inputs: tuple[EvidenceInput, ...] = Field(max_length=200)
    checks: tuple[EvidenceCheck, ...] = Field(min_length=1, max_length=200)
    facts: dict[str, JsonValue] = Field(default_factory=dict, max_length=50)
    compacted: bool = False

    @model_validator(mode="after")
    def identities_are_unique(self) -> EvidenceReviewBundle:
        """Reject ambiguous identities, and blocked checks whose root is not a failure here."""
        check_ids = [check.id for check in self.checks]
        if len(check_ids) != len(set(check_ids)):
            raise ValueError("check ids must be unique")
        paths = [item.path for item in self.inputs]
        if len(paths) != len(set(paths)):
            raise ValueError("input paths must be unique")
        status = {check.id: check.status for check in self.checks}
        for check in self.checks:
            if check.blocked_by is not None and status.get(check.blocked_by) is not (
                CheckStatus.FAILED
            ):
                raise ValueError(
                    f"check {check.id} is blocked by {check.blocked_by}, which is not a failed "
                    "check in this bundle"
                )
        return self

    def checklist_verdict(self) -> ReviewVerdict:
        """Return the verdict floor that the deterministic checklist establishes."""
        return checklist_verdict(self.checks)

    def evidence_refs(self) -> frozenset[str]:
        """Return the identities a finding may cite: check ids and input paths."""
        return frozenset(
            (*(check.id for check in self.checks), *(item.path for item in self.inputs))
        )


class EvidenceReviewFinding(ContractModel):
    """One evidence-backed review observation."""

    severity: ReviewSeverity
    area: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=1_000)
    evidence_refs: tuple[EvidenceRef, ...] = Field(min_length=1, max_length=10)


class EvidenceReviewRisk(ContractModel):
    """A release risk that remains after the review, with its mitigation."""

    severity: ReviewSeverity
    description: str = Field(min_length=1, max_length=600)
    mitigation: str = Field(min_length=1, max_length=600)


class EvidenceReviewOutput(ContractModel):
    """Structured result every review prompt set must return as its final result."""

    summary: str = Field(min_length=1, max_length=1_500)
    findings: tuple[EvidenceReviewFinding, ...] = Field(default=(), max_length=30)
    risks: tuple[EvidenceReviewRisk, ...] = Field(default=(), max_length=15)
    recommendations: tuple[Annotated[str, Field(min_length=1, max_length=600)], ...] = Field(
        default=(), max_length=15
    )
    verdict: ReviewVerdict


class OwnerCoverage(ContractModel):
    """Checklist outcome for one evidence owner, derived by :func:`owner_coverage`."""

    owner: ReviewOwner
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    blocked: int = Field(ge=0)
    status: OwnerStatus
    roots: tuple[ReviewIdentifier, ...] = ()
    """Root checks that blocked this owner's checks, in checklist order."""


_VERDICT_ORDER = {
    ReviewVerdict.PASS: 0,
    ReviewVerdict.PASS_WITH_RISKS: 1,
    ReviewVerdict.FAIL: 2,
}


def checklist_verdict(checks: Iterable[EvidenceCheck]) -> ReviewVerdict:
    """A failed or blocked required check fails the review; an unmet advisory check adds risk.

    A blocked check was never demonstrated, so it weighs like a failure: a review cannot pass
    while a required owner has not submitted evidence. Reports attribute such a verdict to the
    root check and its owner (see :func:`owner_coverage`), not to the behaviour being checked.
    """
    unmet = [check for check in checks if check.status is not CheckStatus.PASSED]
    if any(check.required for check in unmet):
        return ReviewVerdict.FAIL
    if unmet:
        return ReviewVerdict.PASS_WITH_RISKS
    return ReviewVerdict.PASS


def blocked_by_root(checks: Iterable[EvidenceCheck]) -> dict[str, tuple[str, ...]]:
    """Map each root check id to the ids of the checks it blocked, in checklist order."""
    roots: dict[str, list[str]] = {}
    for check in checks:
        if check.blocked_by is not None:
            roots.setdefault(check.blocked_by, []).append(check.id)
    return {root: tuple(blocked) for root, blocked in roots.items()}


def owner_coverage(bundle: EvidenceReviewBundle) -> tuple[OwnerCoverage, ...]:
    """Summarise checks per owner in first-appearance order; empty when no check has an owner.

    Status, in order of precedence: one of the owner's own failed checks blocked others
    (``evidence_not_submitted`` when every input those roots cite is missing, otherwise
    ``evidence_incomplete``); another owner's root blocked them (``blocked_upstream``); a
    required check failed (``failing``); only advisory checks failed (``advisory_gaps``);
    every check passed (``complete``).
    """
    if not any(check.owner for check in bundle.checks):
        return ()
    by_id = {check.id: check for check in bundle.checks}
    inputs = {item.path: item.status for item in bundle.inputs}
    groups: dict[str, list[EvidenceCheck]] = {}
    for check in bundle.checks:
        groups.setdefault(check.owner or UNASSIGNED_OWNER, []).append(check)
    coverage: list[OwnerCoverage] = []
    for owner, checks in groups.items():
        counts = dict.fromkeys(CheckStatus, 0)
        for check in checks:
            counts[check.status] += 1
        roots = list(dict.fromkeys(c.blocked_by for c in checks if c.blocked_by is not None))
        own_ids = {check.id for check in checks}
        own_roots = [root for root in roots if root in own_ids]
        if own_roots:
            status = (
                OwnerStatus.EVIDENCE_NOT_SUBMITTED
                if all(_cites_only_missing_inputs(by_id[root], inputs) for root in own_roots)
                else OwnerStatus.EVIDENCE_INCOMPLETE
            )
        elif roots:
            status = OwnerStatus.BLOCKED_UPSTREAM
        elif any(check.required and check.status is CheckStatus.FAILED for check in checks):
            status = OwnerStatus.FAILING
        elif counts[CheckStatus.FAILED]:
            status = OwnerStatus.ADVISORY_GAPS
        else:
            status = OwnerStatus.COMPLETE
        coverage.append(
            OwnerCoverage(
                owner=owner,
                passed=counts[CheckStatus.PASSED],
                failed=counts[CheckStatus.FAILED],
                blocked=counts[CheckStatus.BLOCKED],
                status=status,
                roots=tuple(roots),
            )
        )
    return tuple(coverage)


def _cites_only_missing_inputs(check: EvidenceCheck, inputs: Mapping[str, InputStatus]) -> bool:
    cited = [inputs.get(reference.partition("#")[0]) for reference in check.evidence_refs]
    known = [status for status in cited if status is not None]
    return bool(known) and all(status is InputStatus.MISSING for status in known)


def stricter_verdict(first: ReviewVerdict, second: ReviewVerdict) -> ReviewVerdict:
    """Return the less permissive of two verdicts."""
    return first if _VERDICT_ORDER[first] >= _VERDICT_ORDER[second] else second


def is_known_ref(reference: str, known: frozenset[str]) -> bool:
    """Accept an exact check id or input path, optionally anchored with ``#`` or ``:``."""
    if reference in known:
        return True
    for separator in ("#", ":"):
        base, found, _ = reference.partition(separator)
        if found and base in known:
            return True
    return False


def validate_review_output(
    output: EvidenceReviewOutput, bundle: EvidenceReviewBundle
) -> EvidenceReviewOutput:
    """Bind a model review to its bundle: cited evidence must exist, verdict must not relax."""
    known = bundle.evidence_refs()
    unknown = sorted(
        {
            reference
            for finding in output.findings
            for reference in finding.evidence_refs
            if not is_known_ref(reference, known)
        }
    )
    if unknown:
        raise ValueError(
            "findings cite evidence that is not in the review bundle: " + ", ".join(unknown[:5])
        )
    floor = bundle.checklist_verdict()
    if stricter_verdict(output.verdict, floor) is not output.verdict:
        raise ValueError(
            f"verdict {output.verdict.value} is more lenient than the deterministic checklist "
            f"verdict {floor.value}"
        )
    return output
