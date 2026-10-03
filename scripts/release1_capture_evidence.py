"""Validate and allowlist public browser-capture evidence without retaining raw run payloads."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

RETRIEVAL = "context.retrieve.v1"


class CaptureError(RuntimeError):
    """The requested report scenario was not demonstrated by the public observations."""


def correlate_run(owning: Mapping[str, Any], shared: Mapping[str, Any]) -> Mapping[str, Any]:
    """Confirm a feature's safe projection and the durable shared run report the same outcome.

    Feature 5 deliberately removes orchestration configuration from its public response and
    translates feature-number wording into domain names. Compare identities and typed support
    fields, which its projection preserves, rather than requiring identical presentation text.
    """
    local, durable = _object(owning.get("run")), _object(shared.get("run"))
    for key in ("id", "status", "request_id"):
        if not local.get(key) or local[key] != durable.get(key):
            raise CaptureError("owning backend projection differs from the shared durable run")
    if local.get("feature_key") is not None and local["feature_key"] != durable.get("feature_key"):
        raise CaptureError("owning backend projection has a different feature")
    local_answer = _object(local.get("final_result"))
    shared_answer = _object(durable.get("final_result"))
    for key in ("confidence", "grounding_status", "corpus_version", "citations"):
        if local_answer.get(key) != shared_answer.get(key):
            raise CaptureError("owning backend answer support differs from the shared durable run")
    local_support = [
        (item.get("kind"), item.get("citation_ids"), item.get("tool_call_ids"))
        for item in _objects(local_answer.get("findings"))
    ]
    shared_support = [
        (item.get("kind"), item.get("citation_ids"), item.get("tool_call_ids"))
        for item in _objects(shared_answer.get("findings"))
    ]
    if local_support != shared_support:
        raise CaptureError("owning backend findings use different evidence")
    return shared


def _object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CaptureError("expected a public JSON object")
    return value


def _objects(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise CaptureError("expected a public object list")
    return value


def _tool_pairs(detail: Mapping[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for step in _objects(detail.get("steps")):
        calls = _object(step.get("input", {})).get("tool_calls")
        results = _object(step.get("output", {})).get("tool_results")
        if calls is None:
            single = step.get("input", {}).get("tool_call")
            calls = [] if single is None else [single]
        if results is None:
            single = step.get("output", {}).get("tool_result")
            results = [] if single is None else [single]
        for call in _objects(calls):
            result = next(
                (item for item in _objects(results) if item.get("call_id") == call.get("id")), None
            )
            if result is None:
                raise CaptureError("recorded tool call has no matching result")
            if result.get("outcome") != "succeeded":
                raise CaptureError("recorded tool call did not succeed")
            pairs.append((call, result))
    return pairs


def _ready(capabilities: Mapping[str, Any], feature: str) -> None:
    services = {item.get("id"): item for item in _objects(capabilities.get("services"))}
    if any(
        services.get(name, {}).get("status") != "ready" or not services.get(name, {}).get("enabled")
        for name in ("mcp", "rag")
    ):
        raise CaptureError("combined local MCP/RAG runtime is not ready")
    if feature not in capabilities.get("grounding_features", []):
        raise CaptureError("this feature has no registered grounding scope")


def verified_evidence(
    detail: Mapping[str, Any],
    *,
    feature_key: str,
    corpus_id: str,
    mode: str,
    expected_tool: str,
    run_id: str,
    capabilities: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify outcome, ownership, invocation transport and support before projecting safe fields.

    Inputs may include private model-output fields from the owning run read endpoint. They are
    examined in memory only. Returned fields are deliberately enumerated: no objectives, tool
    arguments/results, prompts, private reasoning, provider request IDs or user record text.
    """
    _ready(capabilities, feature_key)
    run = _object(detail.get("run"))
    if run.get("id") != run_id or run.get("feature_key") != feature_key:
        raise CaptureError("owning backend run ID/feature differs from the visible turn")
    if run.get("status") != "succeeded" or run.get("error"):
        raise CaptureError("owning backend run did not succeed")
    if _object(run.get("grounding")).get("corpus_id") != corpus_id:
        raise CaptureError("run uses a different corpus")
    final = _object(run.get("final_result"))
    if not isinstance(final.get("summary"), str) or not final["summary"].strip():
        raise CaptureError("successful run has no substantive answer")
    if final.get("confidence") not in {"high", "moderate", "low", "insufficient"} or not final.get(
        "confidence_reason"
    ):
        raise CaptureError("answer has no valid confidence category/reason")
    pairs = _tool_pairs(detail)
    retrievals = [
        result.get("retrieval") for call, result in pairs if call.get("tool_name") == RETRIEVAL
    ]
    if not retrievals:
        raise CaptureError("run has no recorded retrieval call")
    retrieval = _object(retrievals[-1])
    if (retrieval.get("feature_key"), retrieval.get("corpus_id")) != (feature_key, corpus_id):
        raise CaptureError("retrieval crossed its feature/corpus scope")
    version = retrieval.get("corpus_version")
    if not isinstance(version, str) or len(version) != 64 or final.get("corpus_version") != version:
        raise CaptureError("answer and retrieval corpus versions do not agree")
    # An unavailable service is a degradation test, not evidence of valid no-match handling.
    if retrieval.get("status") not in {"ready", "no_match"}:
        raise CaptureError("retrieval was unavailable rather than supported or a valid no-match")
    citations = _objects(final.get("citations"))
    findings = _objects(final.get("findings"))
    retrieved = {item.get("citation_id"): item for item in _objects(retrieval.get("citations"))}
    used_citations = {
        identifier for finding in findings for identifier in finding.get("citation_ids", [])
    }
    for citation in citations:
        if (
            citation.get("feature_key"),
            citation.get("corpus_id"),
            citation.get("corpus_version"),
        ) != (feature_key, corpus_id, version):
            raise CaptureError("citation feature/corpus/version differs")
        identifier = citation.get("citation_id")
        if (
            identifier not in retrieved
            or identifier not in used_citations
            or citation != retrieved[identifier]
        ):
            raise CaptureError("answer citation was not used or does not match retrieved evidence")
        if (
            not citation.get("excerpt")
            or not citation.get("source_uri")
            or not citation.get("content_hash")
        ):
            raise CaptureError("citation lacks inspectable source metadata")
    if mode == "rag":
        if (
            retrieval.get("status") != "ready"
            or final.get("confidence") == "insufficient"
            or not citations
        ):
            raise CaptureError("supported RAG scenario has no grounded cited answer")
        if not any(
            item.get("kind") == "guidance" and item.get("citation_ids") for item in findings
        ):
            raise CaptureError("supported RAG scenario contains no cited guidance finding")
    elif mode == "insufficient":
        if (
            final.get("confidence") != "insufficient"
            or final.get("grounding_status") not in {"no_match", "insufficient_context"}
            or not final.get("evidence_gaps")
        ):
            raise CaptureError("unsupported question did not produce explicit insufficient context")
        if citations or any(item.get("kind") == "guidance" for item in findings):
            raise CaptureError("insufficient answer asserted unsupported guidance")
    elif mode == "mcp":
        matches = [
            (call, result)
            for call, result in pairs
            if call.get("tool_name") == expected_tool
            and "transport:mcp" in result.get("evidence_references", [])
        ]
        if not matches or not any(
            isinstance(result.get("content"), dict) and result["content"] for _, result in matches
        ):
            raise CaptureError("expected successful structured tool result through MCP is absent")
        supported = {
            identifier
            for finding in findings
            if finding.get("kind") == "tool_fact"
            for identifier in finding.get("tool_call_ids", [])
        }
        if not any(call.get("id") in supported for call, _ in matches):
            raise CaptureError("MCP result does not support any visible answer finding")
    else:
        raise CaptureError("unknown capture evidence mode")
    tools = [
        {
            "call_id": call.get("id"),
            "tool_name": call.get("tool_name"),
            "tool_version": call.get("tool_version"),
            "outcome": result.get("outcome"),
            "transport": "rag"
            if call.get("tool_name") == RETRIEVAL
            else "mcp"
            if "transport:mcp" in result.get("evidence_references", [])
            else "unverified",
        }
        for call, result in pairs
    ]
    models = []
    for step in _objects(detail.get("steps")):
        invocation = step.get("output", {}).get("model_invocation")
        if isinstance(invocation, dict):
            models.append(
                {
                    key: invocation.get(key)
                    for key in ("provider", "model", "prompt_id", "prompt_version", "prompt_hash")
                }
            )
    return {
        "feature_key": feature_key,
        "run_id": run_id,
        "request_id": run.get("request_id"),
        "run_created_at": run.get("created_at"),
        "status": "succeeded",
        "model_profile": run.get("model_profile"),
        "prompt_set": run.get("prompt_set"),
        "models": models,
        "tools": tools,
        "corpus_id": corpus_id,
        "corpus_version": version,
        "retrieval_status": retrieval["status"],
        "grounding_status": final.get("grounding_status"),
        "confidence": final["confidence"],
        "citation_count": len(citations),
        "evidence_gap_count": len(final.get("evidence_gaps", [])),
        "citations": [
            {
                key: item.get(key)
                for key in (
                    "citation_id",
                    "document_id",
                    "chunk_id",
                    "title",
                    "source_uri",
                    "source_date",
                    "content_hash",
                    "score",
                )
            }
            for item in citations
        ],
    }
