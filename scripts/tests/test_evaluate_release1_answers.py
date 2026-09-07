"""Provider evaluation must retain failures and distinguish fixture from live evidence."""

from typing import Any

from scripts.evaluate_release1_answers import evaluate_answer, fixture_facts

from agent_core import ModelMetrics, ProviderHealth
from agent_core.ports import StructuredModelRequest, StructuredModelResult


class FixedAnswerProvider:
    def __init__(self, final: dict[str, Any]) -> None:
        self.final = final

    def health(self) -> ProviderHealth:
        return ProviderHealth(reachable=True, detail="Deterministic unit fixture")

    def generate_structured(self, request: StructuredModelRequest) -> StructuredModelResult:
        return StructuredModelResult(
            provider="fixture",
            model="no-real-model",
            metrics=ModelMetrics(total_duration_ms=0, prompt_tokens=10, output_tokens=5),
            content={
                "decision": "complete",
                "justification": "Bounded supplied evidence was considered.",
                "final_result": self.final,
            },
        )


def _case() -> dict[str, Any]:
    return {
        "id": "absent-astronomy",
        "query": "What is the orbital period of Kepler-186f?",
        "retrieval_seconds": 0.0,
        "retrieval": {
            "feature_key": "student-1-propertyscope-data-platform",
            "corpus_id": "operator-guidance",
            "status": "no_match",
            "corpus_version": "a" * 64,
            "citations": [],
            "detail": "No relevant context.",
        },
    }


def _insufficient() -> dict[str, Any]:
    return {
        "summary": "Insufficient context.",
        "findings": [],
        "confidence": "insufficient",
        "confidence_reason": "No astronomy evidence was supplied.",
        "evidence_gaps": ["No orbital observation."],
        "next_step": "Use an appropriate source.",
        "safety_boundary": "No mutation authorized or executed.",
    }


def test_evaluation_records_actual_usage_and_validated_insufficient_answer() -> None:
    result = evaluate_answer(_case(), FixedAnswerProvider(_insufficient()), "fixture", "rag")
    assert result["status"] == "completed"
    assert result["final_result"]["confidence"] == "insufficient"
    assert result["final_result"]["citations"] == []
    assert result["invocations"][0]["metrics"]["prompt_tokens"] == 10
    assert result["invocations"][0]["prompt_version"] == "v8"
    assert result["tool_results"][0]["content"]["evidence_kind"] == "fixture"
    assert result["claim_support_review"] == "requires_human_review"


def test_forged_answer_retains_both_failed_attempts_instead_of_claiming_success() -> None:
    final = _insufficient()
    final["confidence"] = "moderate"
    final["findings"] = [
        {"text": "Fabricated fact", "kind": "guidance", "citation_ids": ["invented-id"]}
    ]
    result = evaluate_answer(_case(), FixedAnswerProvider(final), "fixture", "rag")
    assert result["status"] == "failed"
    assert result["final_result"] is None
    assert len(result["invocations"]) == 2
    assert result["invocations"][1]["repair_attempt"] == 1
    assert result["error_type"] == "ModelOutputValidationError"


def test_tool_only_baseline_uses_existing_prompt_without_adding_retrieved_evidence() -> None:
    result = evaluate_answer(
        _case(), FixedAnswerProvider({"summary": "No evidence supplied."}), "fixture", "tool_only"
    )
    assert result["status"] == "completed"
    assert result["prompt_set"] == "default.v7"
    assert len(result["tool_results"]) == 1
    assert result["tool_results"][0]["retrieval"] is None
    partial = fixture_facts("injection-request")
    assert partial["complete"] is False
    assert partial["human_approval"] == "not_granted"
