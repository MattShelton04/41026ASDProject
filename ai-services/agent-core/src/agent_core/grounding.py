"""Deterministic validation of grounded claims; no network or model authority."""

from typing import cast

from pydantic import JsonValue

from agent_core.errors import ModelOutputValidationError
from shared_contracts import Adaptation, AgentRun, ToolOutcome, ToolResult
from shared_contracts.grounding import GroundedAnswer


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
    for claim in answer.findings:
        if not set(claim.citation_ids).issubset(citations):
            raise ValueError("claim references evidence that was not retrieved")
        if not set(claim.tool_call_ids).issubset(tool_ids):
            raise ValueError("claim references an unsuccessful or unrelated tool call")
        used.update(claim.citation_ids)
    if latest.status != "ready" or not citations:
        # An insufficient response can retain current tool facts, but cannot imply that
        # document context exists. The server owns the confidence and missing-context text.
        answer = answer.evolve(
            confidence="insufficient",
            confidence_reason="Relevant document context is unavailable or insufficient.",
            summary="Insufficient context to provide a grounded explanation.",
            evidence_gaps=tuple(dict.fromkeys((latest.detail, *answer.evidence_gaps)))[:10],
        )
    elif not used:
        raise ValueError("grounded explanation must cite at least one retrieved passage")
    elif answer.confidence == "high":
        # Retrieved project guidance plus tool references establishes identifiable support,
        # not verified semantic entailment. Keep the category conservative.
        answer = answer.evolve(
            confidence="moderate",
            confidence_reason="Sources are identified; claim support still needs human verification.",
        )
    payload = cast(dict[str, JsonValue], answer.model_dump(mode="json"))
    payload["citations"] = [citations[key].model_dump(mode="json") for key in sorted(used)]
    payload["grounding_status"] = latest.status
    payload["corpus_version"] = latest.corpus_version
    return payload
