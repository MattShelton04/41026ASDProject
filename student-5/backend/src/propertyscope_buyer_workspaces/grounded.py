"""Preserve shared grounded answers and their immutable citation metadata."""

from __future__ import annotations

import re
from typing import Any

from propertyscope_buyer_workspaces.integrations import IntegrationUnavailableError
from shared_contracts.grounding import GroundedAnswer
from shared_contracts.retrieval import EvidenceCitation


def domain_text(value: str) -> str:
    names = {
        "1": "Property discovery",
        "2": "Sales research",
        "3": "Suburb analytics",
        "4": "Due diligence",
    }
    return re.sub(r"\bfeature\s+([1-4])\b", lambda match: names[match[1]], value, flags=re.I)


def project_answer(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise IntegrationUnavailableError("Invalid answer")
    result = dict(value)
    if any(key in result for key in ("grounding_status", "confidence_reason", "citations")):
        try:
            answer = GroundedAnswer.model_validate(
                {key: result[key] for key in GroundedAnswer.model_fields if key in result}
            )
            citations = [
                EvidenceCitation.model_validate(item) for item in result.get("citations", [])
            ]
            status = result.get("grounding_status")
            version = result.get("corpus_version")
            if status not in {"ready", "no_match", "empty", "unavailable", "insufficient_context"}:
                raise ValueError("Invalid grounding status")
            if version is not None and (
                not isinstance(version, str) or not re.fullmatch(r"[a-f0-9]{64}", version)
            ):
                raise ValueError("Invalid corpus version")
            if len(citations) > 10 or any(
                item.feature_key != "student-5-buyer-journey"
                or item.corpus_id != "operator-guidance"
                or item.corpus_version != version
                for item in citations
            ):
                raise ValueError("Invalid citation scope")
            ids = {item.citation_id for item in citations}
            if len(ids) != len(citations) or any(
                not set(claim.citation_ids).issubset(ids) for claim in answer.findings
            ):
                raise ValueError("Unknown citation")
            if status != "ready" and (
                answer.confidence != "insufficient"
                or any(claim.kind == "guidance" for claim in answer.findings)
            ):
                raise ValueError("Unsupported grounding")
            result = answer.model_dump(mode="json")
            result.update(
                citations=[item.model_dump(mode="json") for item in citations],
                grounding_status=status,
                corpus_version=version,
            )
        except (ValueError, TypeError) as exc:
            raise IntegrationUnavailableError("Invalid grounded answer") from exc
    for key in (
        "summary",
        "next_step",
        "recommended_next_step",
        "safety_boundary",
        "safety_note",
        "confidence_reason",
    ):
        if isinstance(result.get(key), str):
            result[key] = domain_text(result[key])
    for key in ("limitations", "evidence_gaps", "suggested_next_actions", "findings"):
        if isinstance(result.get(key), list):
            result[key] = [
                domain_text(item)
                if isinstance(item, str)
                else {**item, "text": domain_text(item["text"])}
                if isinstance(item, dict) and isinstance(item.get("text"), str)
                else item
                for item in result[key]
            ]
    return result
