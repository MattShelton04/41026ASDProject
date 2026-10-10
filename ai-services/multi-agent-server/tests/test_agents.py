"""Model-backed agents: schema validation, bounded retries, policy checks and fallback."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from agent_core import (
    ModelMetrics,
    ModelProviderError,
    ModelRole,
    StructuredModelResult,
)
from multi_agent_server.agents import AgentSettings
from multi_agent_server.service import WorkflowService
from shared_contracts.multi_agent import (
    AuditEvent,
    FindingOutcome,
    FindingSeverity,
    HumanDecisionKind,
    WorkflowRunRequest,
    WorkflowState,
)
from shared_testkit import ScriptedLLMProvider

RECORD_ID = "8c0d7e0e-4a3b-4c55-9a62-0d7c5f0f9a11"
Factory = Callable[..., WorkflowService]


def result(content: dict[str, Any]) -> StructuredModelResult:
    return StructuredModelResult(
        content=content,
        provider="openai",
        model="gpt-test",
        provider_request_id="req_1",
        metrics=ModelMetrics(total_duration_ms=5, prompt_tokens=10, output_tokens=5),
    )


PLAN = {
    "summary": "Model plan",
    "steps": [
        {
            "id": "record",
            "title": "Record",
            "purpose": "Read it",
            "tool": "example.record.v1",
            "arguments": {"record_id": RECORD_ID},
        },
        {
            "id": "quality",
            "title": "Quality",
            "purpose": "Read quality",
            "tool": "example.quality.v1",
            "arguments": {"record_id": RECORD_ID},
            "expected_evidence": "zero failures",
        },
    ],
    "evidence_needed": ["record summary", "quality results"],
}
WORK = {
    "summary": "Model work",
    "steps": [{"step_id": "record", "findings": ["item_count is 10"]}],
}
REVIEW = {
    "summary": "Model review",
    "recommendation": "approve",
    "findings": [
        {
            "severity": "low",
            "message": "Status is only candidate",
            "recommendation": "Note it",
            "step_ids": ["record", "ghost"],
            "evidence_ids": ["ev-record-r1", "ev-ghost"],
        },
        {"severity": "info", "message": "Looks complete", "recommendation": "None"},
    ],
}


def run_with(service_factory: Factory, outcomes: list[Any], **settings: Any) -> Any:
    provider = ScriptedLLMProvider(outcomes)
    service = service_factory(
        provider=provider, mode="model", agent_settings=AgentSettings(**settings)
    )
    run = service.create_run(
        WorkflowRunRequest(template_id="example-readiness-review", input={"record_id": RECORD_ID}),
        request_id="req-model",
    )
    return run, provider, service


def test_model_outputs_are_validated_and_attributed(service_factory: Factory) -> None:
    run, provider, service = run_with(service_factory, [result(PLAN), result(WORK), result(REVIEW)])

    assert run.state is WorkflowState.AWAITING_HUMAN
    assert run.provider_mode == "model"
    assert run.plan.summary == "Model plan"
    assert run.plan.produced_by.provider == "openai"
    assert run.plan.steps[1].expected_evidence == "zero failures"
    assert [request.role for request in provider.requests] == [
        ModelRole.PLANNER,
        ModelRole.ADAPTER,
        ModelRole.REVIEWER,
    ]
    assert {request.prompt_id for request in provider.requests} == {
        "planner",
        "worker",
        "reviewer",
    }
    assert all(request.model_profile == "test-profile" for request in provider.requests)
    worker = {step.step_id: step for step in run.worker_output.steps}
    assert worker["record"].findings == ("item_count is 10",)
    assert worker["quality"].findings == ("The Worker reported no findings for this step.",)
    model_findings = [f for f in run.review.findings if f.source == "model"]
    assert model_findings[0].step_ids == ("record",)
    assert model_findings[0].evidence_ids == ("ev-record-r1",)
    assert model_findings[1].outcome is FindingOutcome.PASS
    invocation = next(
        entry
        for entry in service.history(run.id).audit
        if entry.event is AuditEvent.MODEL_INVOCATION
    )
    assert invocation.detail["model"] == "gpt-test"
    assert invocation.detail["prompt_tokens"] == 10


def test_invalid_model_output_is_retried_then_accepted(service_factory: Factory) -> None:
    run, provider, service = run_with(
        service_factory,
        [result({"summary": "missing steps"}), result(PLAN), result(WORK), result(REVIEW)],
    )

    assert run.plan.produced_by.invocations == 2
    assert provider.requests[1].repair_attempt == 1
    outcomes = [
        entry.detail["outcome"]
        for entry in service.history(run.id).audit
        if entry.event is AuditEvent.MODEL_INVOCATION
    ]
    assert outcomes[:2] == ["invalid_output", "succeeded"]
    # Every attempt is announced before it runs, so a live view can show what it waits on.
    planner_events = [
        (entry.event, entry.detail.get("attempt"))
        for entry in service.history(run.id).audit
        if entry.role.value == "planner"
        and entry.event in {AuditEvent.MODEL_STARTED, AuditEvent.MODEL_INVOCATION}
    ]
    assert planner_events == [
        (AuditEvent.MODEL_STARTED, 1),
        (AuditEvent.MODEL_INVOCATION, 1),
        (AuditEvent.MODEL_STARTED, 2),
        (AuditEvent.MODEL_INVOCATION, 2),
    ]
    started = next(e for e in service.history(run.id).audit if e.event is AuditEvent.MODEL_STARTED)
    assert started.detail == {
        "attempt": 1,
        "model_profile": "test-profile",
        "prompt_id": "planner",
        "prompt_version": "v1",
        "repair_attempt": 0,
    }


@pytest.mark.parametrize(
    "bad_plan",
    [
        {**PLAN, "steps": [{**PLAN["steps"][0], "tool": "example.publish.v1"}, PLAN["steps"][1]]},
        {**PLAN, "steps": [PLAN["steps"][0]]},
        {**PLAN, "steps": [PLAN["steps"][0], PLAN["steps"][0], PLAN["steps"][1]]},
        {
            **PLAN,
            "steps": [{**PLAN["steps"][0], "arguments": {"record_id": "nope"}}, PLAN["steps"][1]],
        },
        {**PLAN, "evidence_needed": [" "]},
    ],
)
def test_policy_violations_fall_back_to_the_deterministic_planner(
    service_factory: Factory, bad_plan: dict[str, Any]
) -> None:
    run, _, service = run_with(
        service_factory, [result(bad_plan), result(bad_plan), result(WORK), result(REVIEW)]
    )

    assert run.plan.produced_by.fallback is True
    assert run.plan.produced_by.provider == "deterministic"
    assert run.plan.produced_by.invocations == 2
    assert [step.tool for step in run.plan.steps] == ["example.record.v1", "example.quality.v1"]
    assert AuditEvent.MODEL_FALLBACK in [entry.event for entry in service.history(run.id).audit]


def test_retryable_provider_errors_are_bounded(service_factory: Factory) -> None:
    retryable = ModelProviderError("busy", code="rate_limited", retryable=True)
    run, provider, _ = run_with(
        service_factory, [retryable, retryable, result(WORK), result(REVIEW)]
    )
    assert run.plan.produced_by.fallback is True
    assert provider.remaining_outcomes == 0


def test_non_retryable_errors_fall_back_immediately(service_factory: Factory) -> None:
    fatal = ModelProviderError("no key", code="model_credentials_missing", retryable=False)
    run, provider, _ = run_with(service_factory, [fatal, fatal, fatal], model_attempts=3)
    assert run.state is WorkflowState.AWAITING_HUMAN
    assert len(provider.requests) == 3  # one per agent, each then falls back
    assert run.review.produced_by.fallback is True


def test_unexpected_provider_exceptions_are_contained(service_factory: Factory) -> None:
    run, _, _ = run_with(service_factory, [RuntimeError("sdk bug"), result(WORK), result(REVIEW)])
    assert run.plan.produced_by.fallback is True


def test_disabled_fallback_fails_the_run_with_a_structured_error(
    service_factory: Factory,
) -> None:
    fatal = ModelProviderError("down", code="provider_down", retryable=False)
    run, _, service = run_with(service_factory, [fatal], fallback="fail")

    assert run.state is WorkflowState.FAILED
    assert run.error.code == "planner_output_unavailable"
    assert run.error.stage.value == "planner"
    assert run.stages[0].status == "failed"
    assert service.history(run.id).audit[-1].event is AuditEvent.RUN_FAILED


def test_worker_rejects_findings_for_unknown_steps(service_factory: Factory) -> None:
    unknown = {"summary": "x", "steps": [{"step_id": "ghost", "findings": ["?"]}]}
    run, _, _ = run_with(
        service_factory, [result(PLAN), result(unknown), result(unknown), result(REVIEW)]
    )
    assert run.worker_output.produced_by.fallback is True


def test_model_cannot_approve_over_a_failed_high_check(service_factory: Factory) -> None:
    import json
    from pathlib import Path

    from multi_agent_server.tools import FixtureToolGateway
    from shared_contracts import ToolDefinition

    payload = json.loads(
        (Path(__file__).parent / "fixtures" / "tools.json").read_text(encoding="utf-8")
    )
    definitions = [ToolDefinition.model_validate(entry["definition"]) for entry in payload["tools"]]
    gateway = FixtureToolGateway(
        definitions,
        {
            "example.record.v1": {"id": RECORD_ID, "item_count": 0},
            "example.quality.v1": {"checks": [{}], "failed": 0},
        },
    )
    provider = ScriptedLLMProvider([result(PLAN), result(WORK), result(REVIEW)])
    service = service_factory(provider=provider, mode="model", gateway=gateway)

    run = service.create_run(
        WorkflowRunRequest(template_id="example-readiness-review", input={"record_id": RECORD_ID}),
        request_id="r",
    )

    assert run.review.recommendation is HumanDecisionKind.CORRECT
    assert "Recommendation changed to correct" in run.review.summary
    failed = [f for f in run.review.findings if f.outcome is FindingOutcome.FAIL]
    assert any(f.severity is FindingSeverity.HIGH and f.source == "check" for f in failed)


def test_agent_settings_bounds() -> None:
    from multi_agent_server.agents import StructuredCaller
    from multi_agent_server.prompts import PromptRegistry
    from multi_agent_server.providers import DeterministicProvider

    with pytest.raises(ValueError, match="between 1 and 3"):
        StructuredCaller(
            DeterministicProvider(),
            mode="model",
            model_profile="p",
            settings=AgentSettings(model_attempts=4),
            prompts=PromptRegistry(),
        )
