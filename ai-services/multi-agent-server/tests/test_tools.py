"""The Worker reaches tools only through the template allowlist and read-only policy."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from shared_tool_runtime import ToolCatalog

from multi_agent_server.templates import load_template
from multi_agent_server.tools import (
    CatalogToolGateway,
    FixtureToolGateway,
    TemplateToolbox,
    ToolRejectedError,
    UnavailableToolGateway,
    bounded_excerpt,
)
from shared_contracts import (
    ToolCall,
    ToolDefinition,
    ToolError,
    ToolOutcome,
    ToolResult,
)
from shared_contracts.multi_agent import (
    MAX_EVIDENCE_EXCERPT_BYTES,
    EvidenceOutcome,
    PlanStep,
    WorkflowTemplate,
)

FIXTURES = Path(__file__).parent / "fixtures"
RECORD_ID = "8c0d7e0e-4a3b-4c55-9a62-0d7c5f0f9a11"


def definition(name: str, **changes: Any) -> ToolDefinition:
    values: dict[str, Any] = {
        "name": name,
        "version": "v1",
        "feature_key": "example-feature",
        "description": "d",
        "input_schema": {
            "type": "object",
            "properties": {"record_id": {"type": "string", "format": "uuid"}},
            "additionalProperties": False,
        },
        "output_schema": {"type": "object"},
        "side_effect": "read_only",
    }
    values.update(changes)
    return ToolDefinition.model_validate(values)


@pytest.fixture
def template() -> WorkflowTemplate:
    return load_template(FIXTURES / "workflow.yaml")


def step(tool: str = "example.record.v1", **arguments: Any) -> PlanStep:
    return PlanStep(
        id="record",
        index=1,
        title="t",
        purpose="p",
        tool=tool,
        arguments=arguments or {"record_id": RECORD_ID},
    )


def toolbox(template: WorkflowTemplate, *definitions: ToolDefinition) -> TemplateToolbox:
    return TemplateToolbox(
        template, FixtureToolGateway(definitions, {item.name: {"ok": True} for item in definitions})
    )


@pytest.mark.parametrize(
    ("tool", "definitions", "code"),
    [
        ("example.publish.v1", [], "tool_not_allowlisted"),
        ("example.record.v1", [], "tool_not_registered"),
        (
            "example.record.v1",
            [definition("example.record.v1", side_effect="destructive_write")],
            "tool_not_read_only",
        ),
        (
            "example.record.v1",
            [definition("example.record.v1", requires_approval=True)],
            "tool_not_read_only",
        ),
        (
            "example.record.v1",
            [definition("example.record.v1", feature_key="someone-else")],
            "tool_not_read_only",
        ),
    ],
)
def test_authorise_rejects_tools_outside_policy(
    template: WorkflowTemplate, tool: str, definitions: list[ToolDefinition], code: str
) -> None:
    with pytest.raises(ToolRejectedError) as error:
        toolbox(template, *definitions).authorise(tool)
    assert error.value.code == code


def test_shared_tools_are_allowed(template: WorkflowTemplate) -> None:
    shared = definition("example.record.v1", feature_key="shared")
    assert toolbox(template, shared).authorise("example.record.v1") == shared


def test_invoke_records_rejections_as_evidence_without_calling(template: WorkflowTemplate) -> None:
    gateway = FixtureToolGateway([definition("example.record.v1")], {"example.record.v1": {}})
    box = TemplateToolbox(template, gateway)

    rejected = box.invoke(
        run_id=uuid4(), request_id="r", round_number=1, step=step("example.record.v1", x=1)
    )

    assert rejected.evidence.outcome is EvidenceOutcome.REJECTED
    assert rejected.evidence.error_code == "tool_arguments_invalid"
    assert gateway.calls == []


def test_invoke_returns_digest_and_full_content(template: WorkflowTemplate) -> None:
    gateway = FixtureToolGateway.from_file(FIXTURES / "tools.json")
    box = TemplateToolbox(template, gateway)
    run_id = uuid4()

    invocation = box.invoke(run_id=run_id, request_id="req-1", round_number=2, step=step())

    evidence = invocation.evidence
    assert evidence.id == "ev-record-r2"
    assert evidence.outcome is EvidenceOutcome.SUCCEEDED
    assert evidence.transport == "fake"
    assert invocation.content["item_count"] == 10
    assert evidence.excerpt == invocation.content
    call = gateway.calls[0]
    assert call.run_id == run_id
    assert call.request_id == "req-1"
    assert call.approval_status.value == "not_required"


def test_invoke_turns_gateway_failures_into_failed_evidence(template: WorkflowTemplate) -> None:
    class Exploding(FixtureToolGateway):
        def execute(self, call: ToolCall, definition: ToolDefinition) -> ToolResult:
            raise RuntimeError("adapter bug")

    box = TemplateToolbox(template, Exploding([definition("example.record.v1")], {}))
    evidence = box.invoke(run_id=uuid4(), request_id="r", round_number=1, step=step()).evidence
    assert evidence.outcome is EvidenceOutcome.FAILED
    assert evidence.error_code == "tool_gateway_error"


def test_fixture_errors_and_unavailable_gateway(template: WorkflowTemplate, tmp_path: Path) -> None:
    fixture = tmp_path / "tools.json"
    fixture.write_text(
        json.dumps(
            {
                "tools": [
                    {
                        "definition": definition("example.record.v1").model_dump(mode="json"),
                        "error": {"code": "not_found", "message": "No such record"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    failing = FixtureToolGateway.from_file(fixture)
    evidence = (
        TemplateToolbox(template, failing)
        .invoke(run_id=uuid4(), request_id="r", round_number=1, step=step())
        .evidence
    )
    assert (evidence.outcome, evidence.error_code) == (EvidenceOutcome.FAILED, "not_found")
    assert failing.health() == (True, "1 fixture tools")

    unavailable = UnavailableToolGateway([definition("example.record.v1")], reason="offline")
    evidence = (
        TemplateToolbox(template, unavailable)
        .invoke(run_id=uuid4(), request_id="r", round_number=1, step=step())
        .evidence
    )
    assert evidence.error_code == "tools_unavailable"
    assert evidence.transport == "none"
    assert unavailable.health() == (False, "offline")

    fixture.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="tools list"):
        FixtureToolGateway.from_file(fixture)


def test_catalog_gateway_delegates_to_its_executor(template: WorkflowTemplate) -> None:
    calls: list[tuple[ToolCall, int]] = []

    class Executor:
        def execute(
            self, call: ToolCall, definition: ToolDefinition, *, timeout_ms: int
        ) -> ToolResult:
            calls.append((call, timeout_ms))
            return ToolResult(
                call_id=call.id,
                outcome=ToolOutcome.FAILED,
                error=ToolError(code="mcp_unavailable", message="down"),
                duration_ms=5,
            )

    catalog = ToolCatalog.model_validate(
        {
            "services": [{"service": "svc", "base_url": "http://127.0.0.1:1"}],
            "tools": [
                {
                    "definition": definition("example.record.v1", timeout_ms=1500).model_dump(
                        mode="json"
                    ),
                    "service": "svc",
                    "method": "POST",
                    "path": "/tools/record",
                }
            ],
        }
    )
    gateway = CatalogToolGateway(catalog, Executor(), transport="mcp")
    assert gateway.health() == (True, "1 catalogued tools via mcp")
    evidence = (
        TemplateToolbox(template, gateway)
        .invoke(run_id=uuid4(), request_id="r", round_number=1, step=step())
        .evidence
    )
    assert evidence.transport == "mcp"
    assert evidence.error_code == "mcp_unavailable"
    assert calls[0][1] == 1500


def test_descriptors_and_static_template_issues(template: WorkflowTemplate) -> None:
    box = toolbox(
        template,
        definition(
            "example.record.v1",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        ),
        definition("example.quality.v1", side_effect="reversible_write"),
    )

    descriptors = {item.name: item for item in box.descriptors()}
    issues = box.template_issues()

    assert descriptors["example.record.v1"].available is True
    assert descriptors["example.quality.v1"].available is False
    assert any("only read_only" in issue for issue in issues)
    assert any("unknown example.record.v1 arguments: record_id" in issue for issue in issues)
    assert toolbox(template).template_issues() == [
        "allowed tool example.record.v1 is not registered in any tool catalogue",
        "allowed tool example.quality.v1 is not registered in any tool catalogue",
    ]


def test_bounded_excerpt_shrinks_large_results() -> None:
    small = {"a": 1}
    assert bounded_excerpt(small) == (small, False)
    large = {"items": [{"text": "x" * 2000, "n": index} for index in range(50)], "count": 50}
    excerpt, truncated = bounded_excerpt(large)
    assert truncated is True
    assert excerpt["count"] == 50
    assert len(json.dumps(excerpt)) <= MAX_EVIDENCE_EXCERPT_BYTES
    huge = {f"k{index}": "y" * 400 for index in range(200)}
    excerpt, truncated = bounded_excerpt(huge)
    assert truncated is True
    assert "note" in excerpt
    deep: dict[str, Any] = {"v": "z" * 20000}
    for _ in range(8):
        deep = {"d": deep}
    excerpt, truncated = bounded_excerpt(deep)
    assert truncated is True
