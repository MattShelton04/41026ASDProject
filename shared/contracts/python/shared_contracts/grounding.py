"""Versioned, domain-neutral grounding intent and model-authored claims."""

from collections.abc import Sequence
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from shared_contracts.base import ContractModel

RETRIEVAL_TOOL = "context.retrieve.v1"
"""Shared read-only guidance tool AI-mode adds to every grounded run's allowlist."""


def grounded_allowlist_variants(
    *allowlists: Sequence[str], retrieval_tool: str = RETRIEVAL_TOOL
) -> tuple[tuple[str, ...], ...]:
    """Expand approved tool allowlists with the grounded variant AI-mode actually records.

    A feature backend that validates an exact historical allowlist tuple before reading its
    own run must also approve the grounded variant. AI-mode appends ``retrieval_tool`` when
    the run's feature has a registered corpus, so a backend checking only its pre-grounding
    tuples rejects its own runs the moment a corpus is registered.

    Returns every supplied allowlist in order, then each grounded variant in the same order.
    Ownership stays exact: this widens the approved set by one known tool, it does not relax
    the comparison to an unrestricted read.
    """
    if not allowlists:
        raise ValueError("at least one tool allowlist is required")
    base: list[tuple[str, ...]] = []
    for allowlist in allowlists:
        variant = tuple(allowlist)
        if not variant:
            raise ValueError("a tool allowlist must not be empty")
        if len(set(variant)) != len(variant):
            raise ValueError("a tool allowlist must not contain duplicates")
        if retrieval_tool in variant:
            raise ValueError(
                f"supply the pre-grounding allowlist; {retrieval_tool} is added by this helper"
            )
        if variant in base:
            raise ValueError("duplicate tool allowlist")
        base.append(variant)
    return (*base, *((*variant, retrieval_tool) for variant in base))


class GroundingRequest(ContractModel):
    """Public guidance scope fixed by the caller, never by retrieved instructions."""

    corpus_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]*$", max_length=100)


class GroundedClaim(ContractModel):
    """A claim with a distinct support boundary for guidance and current tool facts."""

    text: str = Field(min_length=1, max_length=1500)
    kind: Literal["guidance", "tool_fact"]
    citation_ids: tuple[str, ...] = Field(default=(), max_length=5)
    tool_call_ids: tuple[UUID, ...] = Field(default=(), max_length=5)

    @model_validator(mode="after")
    def support_matches_kind(self) -> "GroundedClaim":
        if self.kind == "guidance" and (not self.citation_ids or self.tool_call_ids):
            raise ValueError("guidance requires document citations only")
        if self.kind == "tool_fact" and (not self.tool_call_ids or self.citation_ids):
            raise ValueError("tool facts require tool call references only")
        return self


class GroundedAnswer(ContractModel):
    """Typed R1 completion, validated against actual persisted evidence before success."""

    summary: str = Field(min_length=1, max_length=2000)
    findings: tuple[GroundedClaim, ...] = Field(default=(), max_length=10)
    confidence: Literal["high", "moderate", "low", "insufficient"]
    confidence_reason: str = Field(min_length=1, max_length=500)
    evidence_gaps: tuple[str, ...] = Field(default=(), max_length=10)
    next_step: str = Field(min_length=1, max_length=1000)
    safety_boundary: str = Field(min_length=1, max_length=1000)
