"""Release 2 evidence review runs: HTTP scope, the bundle tool and the completion contract."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from flask import Flask

from agent_core import ModelRole, create_run
from ai_mode.prompts import PromptRegistry, RegistryPromptBuilder
from ai_mode.release_review import (
    ReviewCompletionValidator,
    ReviewEvidenceToolExecutor,
    bundle_for,
    is_review_run,
    project_bundle,
    review_evidence_definition,
)
from ai_mode.services import AppServices
from shared_contracts import (
    AgentRun,
    AgentRunRequest,
    ApprovalStatus,
    SideEffectClass,
    ToolCall,
    ToolDefinition,
    ToolOutcome,
    ToolResult,
)
from shared_contracts.evidence_review import (
    REVIEW_EVIDENCE_TOOL,
    REVIEW_FEATURE_KEY,
    EvidenceReviewBundle,
)
from shared_testkit import assert_problem_detail

PROMPT_ROOT = Path(__file__).resolve().parents[1] / "src" / "ai_mode" / "prompt_assets"
NOW = datetime(2026, 10, 20, tzinfo=UTC)


def _bundle(mode: str = "testing", *, failed: bool = True) -> EvidenceReviewBundle:
    return EvidenceReviewBundle.model_validate(
        {
            "mode": mode,
            "inputs": [
                {
                    "path": "security/pre-commit-report.md",
                    "status": "read",
                    "sha256": "a" * 64,
                    "bytes": 120,
                },
                {"path": "ci/student-1.md", "status": "missing", "detail": "file not found"},
            ],
            "checks": [
                {
                    "id": "security.report",
                    "title": "Report covers all scans",
                    "status": "passed",
                    "detail": "All three scans named.",
                    "evidence_refs": ["security/pre-commit-report.md"],
                },
                {
                    "id": "ci.student-1.run",
                    "title": "CI evidence links the run",
                    "status": "failed" if failed else "passed",
                    "detail": "Evidence gap: ci/student-1.md is missing.",
                    "evidence_refs": ["ci/student-1.md"],
                },
            ],
            "facts": {"students": 5},
        }
    )


def _request(bundle: EvidenceReviewBundle | None = None, **changes: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "feature_key": REVIEW_FEATURE_KEY,
        "objective": (bundle or _bundle()).model_dump_json(),
        "prompt_set": "review-testing.v1",
        "tool_allowlist": [REVIEW_EVIDENCE_TOOL],
        "title": "Release 2 testing evidence review",
    }
    payload.update(changes)
    return payload


def _run(**changes: Any) -> AgentRun:
    return create_run(
        AgentRunRequest.model_validate(_request(**changes)),
        run_id=uuid4(),
        request_id="review-request",
        now=NOW,
    )


def _output(**changes: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "summary": "One CI report is missing.",
        "findings": [
            {
                "severity": "high",
                "area": "ci",
                "message": "Student 1 CI evidence is missing.",
                "evidence_refs": ["ci.student-1.run", "ci/student-1.md#line-1"],
            }
        ],
        "risks": [
            {
                "severity": "medium",
                "description": "Endpoint regressions may go unnoticed.",
                "mitigation": "Collect the CI evidence before release.",
            }
        ],
        "recommendations": ["Re-run collect_ci_evidence for student-1."],
        "verdict": "fail",
    }
    payload.update(changes)
    return payload


def test_api_accepts_a_review_run_and_keeps_scopes_apart(
    app: Flask, app_services: AppServices
) -> None:
    client = app.test_client()

    accepted = client.post("/api/v1/agent-runs", json=_request())
    feature_borrowing = client.post(
        "/api/v1/agent-runs", json=_request(feature_key="student-1-feature")
    )
    loop_default = client.post(
        "/api/v1/agent-runs", json=_request(prompt_set="default.v7", tool_allowlist=None)
    )
    widened = client.post(
        "/api/v1/agent-runs",
        json=_request(tool_allowlist=[REVIEW_EVIDENCE_TOOL, "data.sources.v1"]),
    )
    not_a_bundle = client.post("/api/v1/agent-runs", json=_request(objective="Review it"))
    wrong_mode = client.post(
        "/api/v1/agent-runs", json=_request(objective=_bundle("cloud").model_dump_json())
    )

    assert accepted.status_code == 202
    stored = app_services.store.get(accepted.get_json()["id"])
    assert stored is not None
    assert stored.run.prompt_set == "review-testing.v1"
    for response, text in (
        (feature_borrowing, "available only"),
        (loop_default, "available only"),
        (widened, "allowlist exactly"),
        (not_a_bundle, "not a valid evidence bundle"),
        (wrong_mode, "does not match"),
    ):
        payload = response.get_json()
        assert_problem_detail(payload, status=422, code="review_scope_invalid")
        assert text in payload["detail"]


def test_bundle_tool_returns_a_compact_checklist_projection() -> None:
    run = _run()
    store = _Store(run)
    executor = ReviewEvidenceToolExecutor(_Delegate(), store)  # type: ignore[arg-type]

    result = executor.execute(_call(run), review_evidence_definition(), timeout_ms=1000)

    assert result.outcome is ToolOutcome.SUCCEEDED
    assert result.content["checklist_verdict"] == "fail"
    assert result.content["passed_checks"] == ["security.report"]
    assert result.content["failed_checks"] == [
        {
            "id": "ci.student-1.run",
            "required": True,
            "detail": "Evidence gap: ci/student-1.md is missing.",
            "evidence_refs": ["ci/student-1.md"],
        }
    ]
    assert result.content["counts"] == {
        "checks": 2,
        "failed": 1,
        "failed_required": 1,
        "inputs": 2,
        "inputs_unread": 1,
    }
    assert result.evidence_references == (f"security/pre-commit-report.md#sha256:{'a' * 64}",)


def test_bundle_tool_fails_closed_and_delegates_other_tools() -> None:
    feature_run = create_run(
        AgentRunRequest(feature_key="student-1-feature", objective="Find records"),
        run_id=uuid4(),
        request_id="feature",
        now=NOW,
    )
    delegate = _Delegate()
    executor = ReviewEvidenceToolExecutor(delegate, _Store(feature_run))  # type: ignore[arg-type]
    missing = ReviewEvidenceToolExecutor(delegate, _Store(None))  # type: ignore[arg-type]

    refused = executor.execute(_call(feature_run), review_evidence_definition(), timeout_ms=1)
    absent = missing.execute(_call(feature_run), review_evidence_definition(), timeout_ms=1)
    other = executor.execute(
        _call(feature_run, tool="data.sources.v1"), _definition(), timeout_ms=1
    )
    executor.close()

    assert refused.outcome is ToolOutcome.FAILED
    assert refused.error is not None and refused.error.code == "review_bundle_unavailable"
    assert absent.outcome is ToolOutcome.FAILED
    assert other.outcome is ToolOutcome.SUCCEEDED
    assert delegate.calls == ["data.sources.v1"]
    assert delegate.closed


def test_completion_validator_binds_the_review_to_its_bundle() -> None:
    validator = ReviewCompletionValidator()
    run = _run()

    validator.validate_completion(run, _output())
    with pytest.raises(ValueError, match="verdict"):
        validator.validate_completion(run, _output(verdict="pass_with_risks"))
    with pytest.raises(ValueError, match="not in the review bundle"):
        validator.validate_completion(
            run,
            _output(
                findings=[
                    {
                        "severity": "low",
                        "area": "ci",
                        "message": "Invented",
                        "evidence_refs": ["ci/student-9.md"],
                    }
                ]
            ),
        )
    with pytest.raises(ValueError):
        validator.validate_completion(run, {"summary": "No verdict"})
    feature_run = create_run(
        AgentRunRequest(feature_key="student-1-feature", objective="Find records"),
        run_id=uuid4(),
        request_id="feature",
        now=NOW,
    )
    validator.validate_completion(feature_run, {"anything": "goes"})
    assert not is_review_run(feature_run)
    with pytest.raises(ValueError, match="not an evidence review run"):
        bundle_for(feature_run)


def test_review_prompt_sets_use_the_review_planner_and_mode_reviewer() -> None:
    builder = RegistryPromptBuilder(PromptRegistry(PROMPT_ROOT))
    for mode in ("multi-agent", "testing", "cloud"):
        bundle = _bundle(mode)
        run = _run(objective=bundle.model_dump_json(), prompt_set=f"review-{mode}.v1")

        plan = builder.build_plan_request(run, (review_evidence_definition(),))

        assert plan.role is ModelRole.PLANNER
        assert (plan.prompt_id, plan.prompt_version) == ("review-planner", "v1")
        assert "review.evidence.v1" in plan.messages[0].content
        assert "untrusted" in plan.messages[1].content
    assert project_bundle(_bundle(failed=False))["checklist_verdict"] == "pass"


class _Store:
    def __init__(self, run: AgentRun | None) -> None:
        self.run = run

    def get(self, run_id: object) -> Any:
        if self.run is None:
            return None
        return type("Detail", (), {"run": self.run})()


class _Delegate:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.closed = False

    def execute(self, call: ToolCall, definition: ToolDefinition, *, timeout_ms: int) -> ToolResult:
        self.calls.append(call.tool_name)
        return ToolResult(call_id=call.id, outcome=ToolOutcome.SUCCEEDED, duration_ms=0)

    def close(self) -> None:
        self.closed = True


def _call(run: AgentRun, *, tool: str = REVIEW_EVIDENCE_TOOL) -> ToolCall:
    return ToolCall(
        id=uuid4(),
        run_id=run.id,
        step_id=uuid4(),
        tool_name=tool,
        tool_version="v1",
        approval_status=ApprovalStatus.NOT_REQUIRED,
    )


def _definition() -> ToolDefinition:
    return ToolDefinition(
        name="data.sources.v1",
        version="v1",
        feature_key="student-1-feature",
        description="List sources",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        side_effect=SideEffectClass.READ_ONLY,
    )
