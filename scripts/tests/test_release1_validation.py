"""Network-free named-mode coverage; live evidence is produced only by the CLI."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from scripts import dev
from scripts.release1_validation import CORPUS, FEATURE, execute_validation, validate

from ai_mode.adapters.retrieval import retrieval_definition
from ai_mode.persistence import SQLiteRunStore
from shared_contracts import (
    SideEffectClass,
    ToolCall,
    ToolDefinition,
    ToolError,
    ToolOutcome,
    ToolResult,
)
from shared_contracts.retrieval import EvidenceCitation, RetrievalResponse


class RetrievalDouble:
    def __init__(self, status: str) -> None:
        self.status = status

    def execute(self, call: ToolCall, definition: ToolDefinition, *, timeout_ms: int) -> ToolResult:
        citation = EvidenceCitation(
            citation_id="validation-citation",
            feature_key=FEATURE,
            corpus_id=CORPUS,
            corpus_version="a" * 64,
            document_id="guidance",
            chunk_id="chunk-1",
            title="Publication guide",
            source_uri="https://example.org/guide",
            content_hash="b" * 64,
            location="section 1",
            ingested_at=datetime.now(UTC),
            evidence_kind="fixture",
            excerpt="Publication requires explicit human review.",
            score=0.9,
        )
        retrieval = RetrievalResponse.model_validate(
            {
                "feature_key": FEATURE,
                "corpus_id": CORPUS,
                "status": self.status,
                "corpus_version": "a" * 64,
                "citations": [citation] if self.status == "ready" else [],
                "detail": "Deterministic test boundary",
            }
        )
        return ToolResult(
            call_id=call.id,
            outcome=ToolOutcome.SUCCEEDED,
            content={"status": self.status, "detail": retrieval.detail},
            retrieval=retrieval,
            duration_ms=0,
        )


@pytest.mark.parametrize(
    "status,passed", [("ready", True), ("no_match", True), ("unavailable", False)]
)
def test_rag_mode_runs_four_phases_and_does_not_mask_outage(
    tmp_path: Path, status: str, passed: bool
) -> None:
    store = SQLiteRunStore(tmp_path / "validation.sqlite3")
    store.initialize()
    result = execute_validation("rag", store, retrieval_definition(), RetrievalDouble(status))
    assert result["passed"] is passed, result
    assert result["phases"] == ["plan", "act", "observe", "adapt"]
    final = result["final_result"]
    assert isinstance(final, dict)
    assert final["grounding_status"] == status
    assert final["confidence"] == ("moderate" if status == "ready" else "insufficient")
    if status == "ready":
        assert final["citations"]
    else:
        assert final["citations"] == []


def test_live_validation_refused_in_ci_before_touching_host_state() -> None:
    with pytest.raises(RuntimeError, match="local-only"):
        validate("mcp", {"CI": "true"})


@pytest.mark.parametrize("failed", [False, True])
def test_mcp_mode_requires_a_successful_structured_tool_result(
    tmp_path: Path, failed: bool
) -> None:
    class ToolDouble:
        def execute(
            self, call: ToolCall, definition: ToolDefinition, *, timeout_ms: int
        ) -> ToolResult:
            return ToolResult(
                call_id=call.id,
                outcome=ToolOutcome.FAILED if failed else ToolOutcome.SUCCEEDED,
                content={} if failed else {"validated": True},
                duration_ms=0,
                error=ToolError(code="mcp_unavailable", message="Service unavailable")
                if failed
                else None,
            )

    definition = ToolDefinition(
        name="platform.capabilities.v1",
        version="v1",
        feature_key=FEATURE,
        description="Test boundary",
        side_effect=SideEffectClass.READ_ONLY,
        input_schema={"type": "object", "additionalProperties": False},
        output_schema={
            "type": "object",
            "properties": {"validated": {"type": "boolean"}},
            "required": ["validated"],
        },
    )
    store = SQLiteRunStore(tmp_path / "validation.sqlite3")
    store.initialize()
    result = execute_validation("mcp", store, definition, ToolDouble())
    assert result["passed"] is not failed
    assert result["status"] == ("failed" if failed else "succeeded")
    assert result["phases"] == ["plan", "act", "observe", "adapt"]


def test_cli_validation_returns_failure_for_missing_service(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from scripts import release1_validation

    monkeypatch.setattr(dev, "DEFAULT_ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(release1_validation, "validate", lambda *args, **kwargs: {"passed": False})
    assert dev.main(["ai", "validate", "mcp"]) == 1
