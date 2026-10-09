"""Model provider selection for the three agents.

Every agent call goes through the provider-neutral ``agent_core.LLMProvider`` port. Two
implementations exist:

* :class:`DeterministicProvider` makes no model call. It derives a plan from the template's
  steps, Worker findings from the actual tool results and a Reviewer summary from the evaluated
  checks. Tests, CI and ``--offline`` runs use it, and the model path falls back to it.
* The model provider is AI-mode's existing OpenAI-compatible adapter and model registry
  (``ai_mode.providers.build_provider``), configured from the same environment AI-mode uses
  (ADR-047). The worker role uses the registry's ``adapter`` model.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from pydantic import JsonValue

from agent_core import (
    LLMProvider,
    ModelMetrics,
    ModelProviderError,
    ModelRole,
    ProviderHealth,
    StructuredModelRequest,
    StructuredModelResult,
)

DETERMINISTIC_PROVIDER = "deterministic"
DETERMINISTIC_MODEL = "deterministic-rules-v1"
DETERMINISTIC_PROFILE = "deterministic"
OFFLINE_CREDENTIAL = "offline-local-development-only"
ProviderMode = Literal["deterministic", "model"]
AGENT_MODEL_ROLES: dict[str, ModelRole] = {
    "planner": ModelRole.PLANNER,
    "worker": ModelRole.ADAPTER,
    "reviewer": ModelRole.REVIEWER,
}


@dataclass(frozen=True, slots=True)
class ProviderSelection:
    """The provider the agents use and how it was chosen."""

    provider: LLMProvider
    mode: ProviderMode
    model_profile: str
    detail: str


class DeterministicProvider:
    """Rule-based structured output computed only from the request's JSON context."""

    def generate_structured(self, request: StructuredModelRequest) -> StructuredModelResult:
        """Return the role's output; the agent validates it exactly like model output."""
        try:
            payload = json.loads(request.messages[-1].content)
        except (json.JSONDecodeError, IndexError) as exc:
            raise ModelProviderError(
                "deterministic provider requires a JSON context message",
                code="deterministic_context_invalid",
                retryable=False,
            ) from exc
        builders = {
            "planner": _plan,
            "worker": _work,
            "reviewer": _review,
        }
        builder = builders.get(request.prompt_id)
        if builder is None or not isinstance(payload, dict):
            raise ModelProviderError(
                f"deterministic provider has no rules for {request.prompt_id}",
                code="deterministic_role_unsupported",
                retryable=False,
            )
        return StructuredModelResult(
            content=builder(payload),
            provider=DETERMINISTIC_PROVIDER,
            model=DETERMINISTIC_MODEL,
            metrics=ModelMetrics(total_duration_ms=0),
        )

    def health(self) -> ProviderHealth:
        """The deterministic provider is always available."""
        return ProviderHealth(reachable=True, detail="Deterministic provider; no model calls")


def _plan(payload: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    template = payload.get("template")
    if not isinstance(template, dict):
        raise TypeError("expected isinstance(template, dict)")
    steps = template.get("steps")
    if not isinstance(steps, list):
        raise TypeError("expected isinstance(steps, list)")
    planned: list[JsonValue] = []
    evidence: list[JsonValue] = []
    for step in steps:
        if not isinstance(step, dict):
            raise TypeError("expected isinstance(step, dict)")
        planned.append(
            {
                "id": step["id"],
                "title": step["title"],
                "purpose": step["purpose"],
                "tool": step["tool"],
                "arguments": step.get("arguments", {}),
                "required": step.get("required", True),
                "expected_evidence": f"The {step['tool']} result for: {step['title']}",
            }
        )
        evidence.append(f"{step['title']} (via {step['tool']})")
    summary = (
        f"Gather {len(planned)} piece(s) of evidence with allowlisted read-only tools for "
        f"'{template.get('title')}'. Objective: {template.get('objective')}"
    )
    return {"summary": summary[:4000], "steps": planned, "evidence_needed": evidence}


def _work(payload: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    evidence = payload.get("evidence")
    if not isinstance(evidence, list):
        raise TypeError("expected isinstance(evidence, list)")
    steps: list[JsonValue] = []
    succeeded = 0
    for entry in evidence:
        if not isinstance(entry, dict):
            raise TypeError("expected isinstance(entry, dict)")
        if entry.get("outcome") == "succeeded":
            succeeded += 1
            excerpt = entry.get("excerpt")
            findings = describe_result(excerpt if isinstance(excerpt, dict) else {})
            findings.insert(
                0, f"{entry['tool_name']} returned evidence ({entry['result_digest']})."
            )
        else:
            findings = [
                f"No evidence: {entry['tool_name']} {entry.get('outcome')} "
                f"({entry.get('error_code')}: {entry.get('error_message')})."
            ]
        bounded: list[JsonValue] = [*findings[:5]]
        steps.append({"step_id": entry["step_id"], "findings": bounded})
    summary = f"Gathered evidence for {succeeded} of {len(evidence)} planned step(s)."
    note = payload.get("correction_note")
    if isinstance(note, str) and note:
        summary += f" Re-run after the human reviewer's correction: {note}"
    return {"summary": summary[:4000], "steps": steps}


def _review(payload: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    results = payload.get("check_results")
    if not isinstance(results, list):
        raise TypeError("expected isinstance(results, list)")
    failed = [
        result for result in results if isinstance(result, dict) and result["outcome"] == "fail"
    ]
    summary = f"{len(results) - len(failed)} of {len(results)} reviewer check(s) passed."
    if failed:
        summary += " Failed: " + "; ".join(
            f"{result['check_id']} ({result['severity']})" for result in failed
        )
        summary += "."
    note = payload.get("correction_note")
    if isinstance(note, str) and note:
        summary += f" Reviewed after the human correction: {note}"
    recommendation = payload.get("deterministic_recommendation")
    return {"summary": summary[:4000], "recommendation": recommendation, "findings": []}


def describe_result(content: Mapping[str, JsonValue]) -> list[str]:
    """Short factual statements about a tool result's top-level fields."""
    findings: list[str] = []
    for key, value in list(content.items())[:8]:
        if isinstance(value, list):
            findings.append(f"{key}: {len(value)} item(s).")
        elif isinstance(value, dict):
            findings.append(f"{key}: object with {len(value)} field(s).")
        else:
            text = json.dumps(value, ensure_ascii=False)
            findings.append(f"{key} = {text if len(text) <= 200 else text[:197] + '...'}.")
    return findings or ["The tool returned an empty result."]


def _configured_credential(environment: Mapping[str, str]) -> bool:
    from ai_mode.configuration import Settings

    settings = Settings.from_env(environment)
    credential = (
        settings.gemini_api_key if settings.llm_provider == "gemini" else settings.openai_api_key
    )
    return bool(credential) and credential != OFFLINE_CREDENTIAL


def select_provider(
    environment: Mapping[str, str], *, requested: Literal["auto", "deterministic", "model"]
) -> ProviderSelection:
    """Choose the agents' provider; ``auto`` uses a model only when a real key is configured."""
    if requested == "deterministic":
        return ProviderSelection(
            DeterministicProvider(),
            "deterministic",
            DETERMINISTIC_PROFILE,
            "deterministic provider selected explicitly",
        )
    if requested == "auto":
        try:
            available = _configured_credential(environment)
        except ValueError:
            available = False
        if not available:
            return ProviderSelection(
                DeterministicProvider(),
                "deterministic",
                DETERMINISTIC_PROFILE,
                "no model credential configured; deterministic provider in use",
            )
    from ai_mode.configuration import Settings
    from ai_mode.providers import build_provider, configured_model_registry

    settings = Settings.from_env(environment)
    registry, profile = configured_model_registry(settings)
    provider = build_provider(settings, registry=registry, readiness_profile=profile)
    configured = environment.get("MULTI_AGENT_MODEL_PROFILE", "").strip() or profile
    if registry.profile(configured) is None:
        raise ValueError(f"MULTI_AGENT_MODEL_PROFILE is not registered: {configured}")
    return ProviderSelection(
        provider, "model", configured, f"{settings.llm_provider} via AI-mode model registry"
    )
