"""Deterministic validation of grounded claims; no network or model authority."""

from typing import cast

from pydantic import JsonValue

from agent_core.errors import ModelOutputValidationError
from shared_contracts import Adaptation, AgentRun, ToolOutcome, ToolResult
from shared_contracts.grounding import GroundedAnswer
from shared_contracts.retrieval import EvidenceCitation

STRONG_MATCH_SCORE = 0.65
"""A cited passage at or above this similarity clearly addresses the question.

Measured with bge-small on the Feature 1 v2 evaluation: every expected passage for a supported
question scored at least 0.65, while passages from related but wrong documents mostly scored
between 0.55 and 0.65.
"""


def validate_adaptation_grounding(
    run: AgentRun, results: tuple[ToolResult, ...], value: Adaptation
) -> None:
    """Use the existing bounded repair mechanism for invalid grounded completions."""
    if run.grounding is not None and value.final_result is not None:
        try:
            validate_grounded_answer(run, value.final_result, results)
        except ValueError as exc:
            raise ModelOutputValidationError(str(exc)) from exc


def validate_grounded_answer(
    run: AgentRun, value: dict[str, JsonValue], results: tuple[ToolResult, ...]
) -> dict[str, JsonValue]:
    """Bind citations to this active plan and distinguish tool facts from guidance."""
    if run.grounding is None:
        return value
    answer = GroundedAnswer.model_validate(value)
    retrievals = tuple(result.retrieval for result in results if result.retrieval is not None)
    if not retrievals:
        raise ValueError("grounded completion requires retrieval in the active plan")
    for retrieval in retrievals:
        if (retrieval.feature_key, retrieval.corpus_id) != (
            run.feature_key,
            run.grounding.corpus_id,
        ):
            raise ValueError("retrieval scope differs from this run")
    # The most recent retrieval is authoritative; repeated retrieval cannot revive a
    # withdrawn chunk from an earlier response in the same plan.
    latest = retrievals[-1]
    citations = {citation.citation_id: citation for citation in latest.citations}
    for citation in citations.values():
        if (citation.feature_key, citation.corpus_id, citation.corpus_version) != (
            run.feature_key,
            run.grounding.corpus_id,
            latest.corpus_version,
        ):
            raise ValueError("citation scope or version differs from retrieval")
    tool_ids = {
        result.call_id
        for result in results
        if result.outcome is ToolOutcome.SUCCEEDED and result.retrieval is None
    }
    used: set[str] = set()
    supported_tool_facts = False
    for claim in answer.findings:
        if not set(claim.citation_ids).issubset(citations):
            raise ValueError("claim references evidence that was not retrieved")
        if not set(claim.tool_call_ids).issubset(tool_ids):
            raise ValueError("claim references an unsuccessful or unrelated tool call")
        used.update(claim.citation_ids)
        supported_tool_facts |= claim.kind == "tool_fact"
    insufficient = latest.status != "ready" or not citations or answer.confidence == "insufficient"
    if insufficient:
        if latest.status == "ready" and not answer.evidence_gaps:
            raise ValueError("insufficient answers must explain the missing relevant context")
        if any(claim.kind == "guidance" for claim in answer.findings):
            raise ValueError("insufficient answers cannot assert grounded guidance findings")
        # An insufficient response can retain current tool facts, but cannot imply that
        # document context exists. The server owns the confidence and missing-context text.
        answer = answer.evolve(
            confidence="insufficient",
            confidence_reason="Relevant document context is unavailable or insufficient.",
            summary=(
                answer.summary
                if run.prompt_set == "default.v9" and supported_tool_facts
                else "Insufficient context to provide a grounded explanation."
            ),
            evidence_gaps=tuple(dict.fromkeys((latest.detail, *answer.evidence_gaps)))[:10],
        )
    elif not used and not (run.prompt_set == "default.v9" and supported_tool_facts):
        raise ValueError("grounded explanation must cite at least one retrieved passage")
    else:
        confidence, reason = assess_confidence(answer, citations)
        answer = answer.evolve(confidence=confidence, confidence_reason=reason)
    payload = cast(dict[str, JsonValue], answer.model_dump(mode="json"))
    payload["citations"] = [citations[key].model_dump(mode="json") for key in sorted(used)]
    payload["grounding_status"] = (
        "insufficient_context" if insufficient and latest.status == "ready" else latest.status
    )
    payload["corpus_version"] = latest.corpus_version
    return payload


def assess_confidence(
    answer: GroundedAnswer, citations: dict[str, EvidenceCitation]
) -> tuple[str, str]:
    """Derive a supported answer's confidence from its evidence, not model self-report.

    Only the model can judge that passages are stale or conflict, so its ``low`` is kept.
    Otherwise the category follows the recorded evidence:

    - high needs no reported gaps, every guidance finding citing a strongly matching
      passage, and at least two independent supports (distinct documents or tool calls);
    - reported evidence gaps, weakly matching guidance or a single support give moderate;
    - low is kept only when the model reports stale or conflicting evidence.
    """
    guidance = [claim for claim in answer.findings if claim.kind == "guidance"]
    documents = {
        citations[identifier].document_id for claim in guidance for identifier in claim.citation_ids
    }
    tool_calls = {
        identifier
        for claim in answer.findings
        if claim.kind == "tool_fact"
        for identifier in claim.tool_call_ids
    }
    weakest = min(
        (
            max(citations[identifier].score for identifier in claim.citation_ids)
            for claim in guidance
        ),
        default=1.0,
    )
    supports = len(documents) + len(tool_calls)
    parts = []
    if documents:
        parts.append(f"{len(documents)} cited guidance document{'s' * (len(documents) != 1)}")
    if tool_calls:
        parts.append(f"{len(tool_calls)} current record check{'s' * (len(tool_calls) != 1)}")
    basis = "Based on " + " and ".join(parts) if parts else "No supporting evidence was cited"

    if answer.confidence == "low":
        return "low", answer.confidence_reason
    if answer.evidence_gaps:
        count = len(answer.evidence_gaps)
        return "moderate", f"{basis}; the answer notes {count} evidence gap{'s' * (count != 1)}."
    if weakest < STRONG_MATCH_SCORE:
        return "moderate", f"{basis}; some cited guidance only partly matches the question."
    if supports < 2:
        return "moderate", f"{basis}; a single source supports the answer."
    return "high", f"{basis}, each closely matching the question, with no evidence gaps."
