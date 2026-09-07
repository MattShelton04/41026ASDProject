"""Opt-in real-provider answer comparison using isolated, labelled evidence.

Runs the production ADAPT prompts and grounding validator, not the full agent loop.
Semantic excerpts come from a previously captured disposable retrieval evaluation.
No host service/index or feature record is changed; no mutation tool is available.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Literal
from uuid import uuid4

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import JsonValue

from agent_core import LLMProvider, create_run
from agent_core.generation import generate_validated
from agent_core.grounding import validate_adaptation_grounding, validate_grounded_answer
from agent_core.ports import ProviderHealth, StructuredModelRequest, StructuredModelResult
from ai_mode.adapters.retrieval import retrieval_definition
from ai_mode.configuration import Settings
from ai_mode.prompts import PromptRegistry, RegistryPromptBuilder
from ai_mode.providers import build_provider, configured_model_registry
from scripts.dev import _load_development_environment
from shared_contracts import (
    Adaptation,
    AgentRunRequest,
    Observation,
    Plan,
    PlanAction,
    SideEffectClass,
    ToolDefinition,
    ToolOutcome,
    ToolResult,
)
from shared_contracts.grounding import GroundingRequest
from shared_contracts.retrieval import RetrievalResponse

ROOT = Path(__file__).resolve().parents[1]
FEATURE = "student-1-propertyscope-data-platform"
SELECTED_CASES = (
    "publish-independent",
    "absent-astronomy",
    "absent-current-property",
    "ambiguous-failure",
    "stale-publication",
    "injection-request",
)


class RecordingProvider:
    """Record bounded public outputs and usage, never credentials or hidden reasoning."""

    def __init__(self, delegate: LLMProvider) -> None:
        self.delegate = delegate
        self.invocations: list[dict[str, Any]] = []

    def health(self) -> ProviderHealth:
        return self.delegate.health()

    def generate_structured(self, request: StructuredModelRequest) -> StructuredModelResult:
        result = self.delegate.generate_structured(request)
        self.invocations.append(
            {
                "provider": result.provider,
                "model": result.model,
                "model_digest": result.model_digest,
                "prompt_id": request.prompt_id,
                "prompt_version": request.prompt_version,
                "prompt_hash": request.prompt_hash,
                "rendered_input_hash": request.rendered_input_hash,
                "repair_attempt": request.repair_attempt,
                "metrics": result.metrics.model_dump(mode="json"),
                "output": result.content,
            }
        )
        return result


def fixture_facts(case_id: str) -> dict[str, JsonValue]:
    """Explicit controlled evidence, never a claim about the live data platform."""
    facts: dict[str, JsonValue] = {
        "evidence_kind": "fixture",
        "fixture_id": "release1-answer-comparison-v1",
        "feature_scope": "Property data acquisition, publication and accepted discovery",
        "assistant_mode": "read_only",
        "live_property_evidence": "not_supplied",
        "no_mutation_executed": True,
    }
    if case_id in {"publish-independent", "stale-publication"}:
        facts.update(
            release_id="fixture-comparison-release",
            publication_state="awaiting_review",
            scope="complete",
            prior_consumer_import_state="rejected",
        )
    elif case_id == "injection-request":
        facts.update(
            release_id="fixture-partial-psi",
            publication_state="candidate",
            scope="psi-year-range",
            complete=False,
            coverage_status="partial",
            human_approval="not_granted",
        )
    elif case_id == "ambiguous-failure":
        facts.update(run_state="failed", diagnostic_error=None, failed_phase=None)
    return facts


def evaluate_answer(
    case: dict[str, Any],
    provider: LLMProvider,
    model_profile: str,
    mode: Literal["tool_only", "rag"],
) -> dict[str, Any]:
    """Run one production adapter call with the same controlled facts in both modes."""
    use_rag = mode == "rag"
    run = create_run(
        AgentRunRequest(
            feature_key=FEATURE,
            objective=case["query"],
            model_profile=model_profile,
            prompt_set="default.v8" if use_rag else "default.v7",
            grounding=GroundingRequest(corpus_id="operator-guidance") if use_rag else None,
        ),
        run_id=uuid4(),
        request_id="isolated-answer-evaluation",
        now=datetime.now(UTC),
    )
    fact_definition = ToolDefinition(
        name="evaluation.facts.v1",
        version="v1",
        feature_key=FEATURE,
        description="Read-only explicitly synthetic evaluation facts; not live feature evidence.",
        input_schema={"type": "object", "additionalProperties": False},
        output_schema={"type": "object"},
        side_effect=SideEffectClass.READ_ONLY,
    )
    definitions = (fact_definition, retrieval_definition()) if use_rag else (fact_definition,)
    actions = [
        PlanAction(
            sequence=1, tool_name=fact_definition.name, purpose="Read controlled fixture facts"
        )
    ]
    results = [
        ToolResult(
            call_id=uuid4(),
            outcome=ToolOutcome.SUCCEEDED,
            duration_ms=0,
            content=fixture_facts(case["id"]),
        )
    ]
    if use_rag:
        actions.append(
            PlanAction(
                sequence=2,
                tool_name=retrieval_definition().name,
                arguments={"query": case["query"]},
                purpose="Retrieve bounded context from the isolated scenario corpus",
            )
        )
        results.append(
            ToolResult(
                call_id=uuid4(),
                outcome=ToolOutcome.SUCCEEDED,
                duration_ms=round(case["retrieval_seconds"] * 1000),
                retrieval=RetrievalResponse.model_validate(case["retrieval"]),
            )
        )
    plan = Plan(
        goal="Answer the user's question within available evidence and identify unsupported parts",
        actions=tuple(actions),
        success_criteria=("Answer supported parts or state the missing evidence honestly",),
        risk_level="low",
        assumptions=("Operational facts are explicitly synthetic evaluation fixtures",),
    )
    builder = RegistryPromptBuilder(
        PromptRegistry(ROOT / "ai-services/ai-mode/src/ai_mode/prompt_assets")
    )
    request = builder.build_adaptation_request(
        run,
        definitions,
        plan,
        results[-1],
        Observation(
            facts=("The bounded read-only evidence was supplied; no mutation was executed.",),
            unassessed_criteria=plan.success_criteria,
        ),
        tuple(results),
    )
    recording = RecordingProvider(provider)
    started = perf_counter()
    report: dict[str, Any] = {
        "mode": mode,
        "model_profile": model_profile,
        "prompt_set": run.prompt_set,
        "tool_results": [result.model_dump(mode="json") for result in results],
    }
    try:
        generated = generate_validated(
            recording,
            request,
            Adaptation,
            max_repairs=1,
            validate=lambda value: validate_adaptation_grounding(run, tuple(results), value),
        )
        final = generated.value.final_result
        if final is not None and use_rag:
            final = validate_grounded_answer(run, final, tuple(results))
        report.update(
            status="completed" if final is not None else "non_completion",
            decision=generated.value.decision.value,
            final_result=final,
            repair_count=generated.repair_count,
            structural_grounding_validation="passed" if use_rag and final else "not_applicable",
        )
    except Exception as exc:
        # Exception class only: upstream exception messages can include transport details.
        report.update(status="failed", error_type=type(exc).__name__, final_result=None)
    report["wall_seconds"] = round(perf_counter() - started, 3)
    report["invocations"] = recording.invocations
    report["claim_support_review"] = "requires_human_review"
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retrieval-report", type=Path, required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    _load_development_environment(args.env_file)
    settings = Settings.from_env()
    registry, profile = configured_model_registry(settings)
    provider = build_provider(settings, registry=registry, readiness_profile=profile)
    retrieval = json.loads(args.retrieval_report.read_text(encoding="utf-8"))
    cases = {case["id"]: case for case in retrieval["cases"]}
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "evaluation_id": "feature1-answer-comparison-v1",
        "executed_at": datetime.now(UTC).isoformat(),
        "scope": "isolated production ADAPT prompt and validator; no planner or tool dispatch",
        "retrieval_evaluation_id": retrieval["evaluation_id"],
        "embedding_model": retrieval["corpus"]["embedding_model"],
        "limits": {"cases": len(SELECTED_CASES), "modes": 2, "maximum_repairs_per_answer": 1},
        "limitations": [
            "One sample per case and mode; operational facts are controlled fixtures.",
            "Tool-only v7 versus RAG v8 changes both available context and production prompt.",
            "This comparison is not a causal benchmark or a full-loop/browser test.",
            "Structural citation validation does not prove semantic entailment.",
        ],
        "cases": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for case_id in SELECTED_CASES:
        case = cases[case_id]
        results = []
        for mode in ("tool_only", "rag"):
            result = evaluate_answer(case, provider, profile, mode)
            results.append(result)
            print(
                json.dumps({"case": case_id, "mode": mode, "status": result["status"]}), flush=True
            )
        report["cases"].append(
            {
                "id": case_id,
                "query": case["query"],
                "forbidden_claims": case["forbidden_claims"],
                "results": results,
            }
        )
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    close = getattr(provider, "close", None)
    if callable(close):
        close()


if __name__ == "__main__":
    main()
