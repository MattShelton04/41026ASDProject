"""Versioned contracts for the agentic loop's Release 2 evidence review modes.

A review mode collects bounded release evidence into an :class:`EvidenceReviewBundle` with a
deterministic checklist, then asks an AI-mode run (or a deterministic stand-in) for an
:class:`EvidenceReviewOutput`. The checklist sets a verdict floor: a model may be stricter than
the checklist but never more lenient, and every finding must cite evidence from the bundle.
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
    "multi-agent": "review-multi-agent.v1",
    "testing": "review-testing.v1",
    "cloud": "review-cloud.v1",
}
MAX_REVIEW_OBJECTIVE_CHARS = 15_000
"""Serialized bundle budget; AI-mode accepts objectives of at most 16,000 characters."""

ReviewIdentifier = Annotated[
    str, Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9_.-]*$")
]
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

    PASS = "pass"
    PASS_WITH_RISKS = "pass_with_risks"
    FAIL = "fail"


class CheckStatus(StrEnum):
    """Deterministic outcome of one checklist item."""

    PASSED = "passed"
    FAILED = "failed"


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
    """One deterministic checklist item with the evidence that decided it."""

    id: ReviewIdentifier
    title: str = Field(min_length=1, max_length=200)
    status: CheckStatus
    required: bool = True
    detail: str = Field(min_length=1, max_length=500)
    evidence_refs: tuple[EvidenceRef, ...] = Field(default=(), max_length=10)


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
        """Reject ambiguous check or input identities that findings could cite."""
        check_ids = [check.id for check in self.checks]
        if len(check_ids) != len(set(check_ids)):
            raise ValueError("check ids must be unique")
        paths = [item.path for item in self.inputs]
        if len(paths) != len(set(paths)):
            raise ValueError("input paths must be unique")
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


_VERDICT_ORDER = {
    ReviewVerdict.PASS: 0,
    ReviewVerdict.PASS_WITH_RISKS: 1,
    ReviewVerdict.FAIL: 2,
}


def checklist_verdict(checks: Iterable[EvidenceCheck]) -> ReviewVerdict:
    """A failed required check fails the review; a failed advisory check adds risk."""
    failed = [check for check in checks if check.status is CheckStatus.FAILED]
    if any(check.required for check in failed):
        return ReviewVerdict.FAIL
    if failed:
        return ReviewVerdict.PASS_WITH_RISKS
    return ReviewVerdict.PASS


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
