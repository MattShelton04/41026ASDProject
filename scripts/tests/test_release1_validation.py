"""Network-free named-mode coverage; live evidence is produced only by the CLI."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from scripts import dev
from scripts.release1_validation import (
    CORPUS,
    FEATURE,
    execute_validation,
    resolve_corpus,
    resolve_mcp_tool,
    validate,
)

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


def _definition(
    name: str,
    *,
    feature: str = FEATURE,
    side_effect: SideEffectClass = SideEffectClass.READ_ONLY,
    required: list[str] | None = None,
    requires_approval: bool = False,
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        version="v1",
        feature_key=feature,
        description="Bounded validation fixture.",
        input_schema={
            "type": "object",
            "properties": {},
            **({"required": required} if required else {}),
        },
        output_schema={"type": "object", "properties": {}},
        side_effect=side_effect,
        requires_approval=requires_approval,
    )


def _catalogue(tmp_path: Path, definitions: list[ToolDefinition]) -> tuple[Path, ...]:
    payload = {
        "schema_version": 1,
        "services": [{"service": "fixture-backend", "base_url": "http://127.0.0.1:9"}],
        "tools": [
            {
                "definition": definition.model_dump(mode="json"),
                "service": "fixture-backend",
                "path": f"/{definition.name}",
                "method": "POST",
            }
            for definition in definitions
        ],
    }
    path = tmp_path / "catalogue.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return (path,)


def test_auto_selected_tool_is_read_only_and_argument_free(tmp_path: Path) -> None:
    paths = _catalogue(
        tmp_path,
        [
            _definition("needs.args.v1", required=["case_id"]),
            _definition("writes.v1", side_effect=SideEffectClass.DESTRUCTIVE_WRITE),
            _definition("safe.v1"),
        ],
    )

    assert resolve_mcp_tool(paths, FEATURE, None).name == "safe.v1"


def test_auto_selection_never_returns_a_write_tool(tmp_path: Path) -> None:
    """A named validation must not dispatch a write against the running local backend."""
    paths = _catalogue(
        tmp_path, [_definition("writes.v1", side_effect=SideEffectClass.REVERSIBLE_WRITE)]
    )

    with pytest.raises(RuntimeError, match="no argument-free read-only tool"):
        resolve_mcp_tool(paths, FEATURE, None)


def test_named_tool_is_held_to_the_same_guard(tmp_path: Path) -> None:
    """--tool must not bypass the rule the auto path enforces."""
    paths = _catalogue(
        tmp_path,
        [
            _definition("writes.v1", side_effect=SideEffectClass.DESTRUCTIVE_WRITE),
            _definition("approves.v1", requires_approval=True),
            _definition("needs.args.v1", required=["case_id"]),
        ],
    )

    for name in ("writes.v1", "approves.v1", "needs.args.v1"):
        with pytest.raises(RuntimeError, match="not usable for validation"):
            resolve_mcp_tool(paths, FEATURE, name)


def test_unknown_feature_and_tool_are_reported_distinctly(tmp_path: Path) -> None:
    paths = _catalogue(tmp_path, [_definition("safe.v1")])

    with pytest.raises(RuntimeError, match="no registered tools"):
        resolve_mcp_tool(paths, "student-9-absent", None)
    with pytest.raises(RuntimeError, match="does not register the tool"):
        resolve_mcp_tool(paths, FEATURE, "absent.v1")


def test_corpus_resolves_from_the_features_own_manifest() -> None:
    assert resolve_corpus(FEATURE) == CORPUS


def test_feature_without_a_corpus_is_told_what_to_declare() -> None:
    # Any enabled feature that has not yet adopted RAG; features adopt independently.
    with pytest.raises(RuntimeError, match=r"declare ai\.rag_corpus"):
        resolve_corpus("student-4-due-diligence")


def test_unknown_feature_is_rejected() -> None:
    with pytest.raises(RuntimeError, match="not an enabled feature"):
        resolve_corpus("student-9-absent")
