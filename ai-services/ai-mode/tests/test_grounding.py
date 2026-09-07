"""R1 grounding through persisted orchestration and authenticated retrieval boundaries."""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from agent_core import AgentRunner, ModelMetrics, ModelRole, ToolRegistry, create_run
from agent_core.grounding import validate_grounded_answer
from agent_core.ports import StructuredModelRequest, StructuredModelResult
from ai_mode.adapters.retrieval import RetrievalToolExecutor, retrieval_definition
from ai_mode.adapters.system import SystemClock, UUID4Generator
from ai_mode.configuration import ConfigurationError, Settings
from ai_mode.persistence import SQLiteRunStore
from ai_mode.prompts import PromptRegistry, RegistryPromptBuilder, _project_tool_result
from ai_mode.services import UnconfiguredToolExecutor
from shared_contracts import AgentRunRequest, ApprovalStatus, ToolCall, ToolOutcome, ToolResult
from shared_contracts.grounding import GroundingRequest
from shared_contracts.retrieval import CorpusVersion, EvidenceCitation, RetrievalResponse

FEATURE = "student-1-propertyscope-data-platform"
CORPUS = "operator-guidance"
NOW = datetime(2026, 9, 7, tzinfo=UTC)


def citation() -> EvidenceCitation:
    return EvidenceCitation(
        citation_id="evidence-1",
        feature_key=FEATURE,
        corpus_id=CORPUS,
        corpus_version="a" * 64,
        document_id="publication",
        chunk_id="chunk-1",
        title="Publication guide",
        source_uri="https://example.org/guidance",
        content_hash="b" * 64,
        location="lines 1-3",
        ingested_at=NOW,
        source_date=NOW.date(),
        evidence_kind="project_guidance",
        excerpt="Only human review can approve publication. Missing evidence is not zero.",
        score=0.8,
    )


def retrieval(status: str = "ready") -> RetrievalResponse:
    return RetrievalResponse.model_validate(
        {
            "feature_key": FEATURE,
            "corpus_id": CORPUS,
            "corpus_version": "a" * 64,
            "status": status,
            "citations": [citation().model_dump()] if status == "ready" else [],
            "detail": "Relevant project guidance." if status == "ready" else "No relevant context.",
        }
    )


def answer() -> dict:
    return {
        "summary": "Publication requires human review.",
        "findings": [
            {
                "text": "Human review is required.",
                "kind": "guidance",
                "citation_ids": ["evidence-1"],
                "tool_call_ids": [],
            }
        ],
        "confidence": "high",
        "confidence_reason": "The guidance describes publication.",
        "evidence_gaps": [],
        "next_step": "Inspect the candidate before review.",
        "safety_boundary": "No publication was approved.",
    }


def setup_run(tmp_path: Path):
    store = SQLiteRunStore(tmp_path / "state.sqlite3")
    store.initialize()
    run = create_run(
        AgentRunRequest(
            feature_key=FEATURE,
            objective="Explain publication review",
            prompt_set="default.v8",
            grounding=GroundingRequest(corpus_id=CORPUS),
        ),
        run_id=uuid4(),
        request_id="grounding-test",
        now=datetime.now(UTC),
    )
    store.create(run)
    return store, run


def test_grounding_binds_guidance_and_live_facts(tmp_path: Path):
    _, run = setup_run(tmp_path)
    fact = ToolResult(
        call_id=uuid4(),
        outcome=ToolOutcome.SUCCEEDED,
        duration_ms=1,
        content={"status": "candidate"},
    )
    source = ToolResult(
        call_id=uuid4(), outcome=ToolOutcome.SUCCEEDED, duration_ms=1, retrieval=retrieval()
    )
    value = answer()
    value["findings"].append(
        {
            "text": "The release is a candidate.",
            "kind": "tool_fact",
            "citation_ids": [],
            "tool_call_ids": [str(fact.call_id)],
        }
    )
    final = validate_grounded_answer(run, value, (fact, source))
    assert final["confidence"] == "moderate"
    assert final["citations"][0]["citation_id"] == "evidence-1"
    value["findings"][1]["tool_call_ids"] = [str(uuid4())]
    with pytest.raises(ValueError, match="unrelated tool"):
        validate_grounded_answer(run, value, (fact, source))


@pytest.mark.parametrize("fault", ["forged", "wrong_scope", "no_retrieval", "no_citation"])
def test_unsupported_grounding_rejected(tmp_path: Path, fault: str):
    _, run = setup_run(tmp_path)
    value = answer()
    result = ToolResult(
        call_id=uuid4(), outcome=ToolOutcome.SUCCEEDED, duration_ms=0, retrieval=retrieval()
    )
    if fault == "forged":
        value["findings"][0]["citation_ids"] = ["not-returned"]
    if fault == "wrong_scope":
        run = run.evolve(feature_key="student-2-feature")
    if fault == "no_citation":
        value["findings"] = []
    with pytest.raises(ValueError):
        validate_grounded_answer(run, value, () if fault == "no_retrieval" else (result,))


@pytest.mark.parametrize("status", ["empty", "no_match", "unavailable"])
def test_no_context_forces_insufficient(tmp_path: Path, status: str):
    _, run = setup_run(tmp_path)
    result = ToolResult(
        call_id=uuid4(), outcome=ToolOutcome.SUCCEEDED, duration_ms=0, retrieval=retrieval(status)
    )
    value = answer()
    value["findings"] = []
    final = validate_grounded_answer(run, value, (result,))
    assert final["confidence"] == "insufficient"
    assert final["summary"].startswith("Insufficient context")
    assert final["citations"] == []


def test_material_gaps_limit_confidence(tmp_path: Path):
    _, run = setup_run(tmp_path)
    value = answer()
    value["evidence_gaps"] = ["Current release unavailable"]
    result = ToolResult(
        call_id=uuid4(), outcome=ToolOutcome.SUCCEEDED, duration_ms=0, retrieval=retrieval()
    )
    assert validate_grounded_answer(run, value, (result,))["confidence"] == "low"


def test_similar_but_irrelevant_context_can_be_insufficient(tmp_path: Path):
    _, run = setup_run(tmp_path)
    value = answer()
    value.update(confidence="insufficient", findings=[], evidence_gaps=["No astronomy context."])
    result = ToolResult(
        call_id=uuid4(), outcome=ToolOutcome.SUCCEEDED, duration_ms=0, retrieval=retrieval()
    )
    final = validate_grounded_answer(run, value, (result,))
    assert final["grounding_status"] == "insufficient_context"
    assert final["citations"] == []


class GuidedProvider:
    """Construct output from exposed evidence, exercising the actual four-phase runner."""

    def generate_structured(self, request: StructuredModelRequest) -> StructuredModelResult:
        if request.role == ModelRole.PLANNER:
            content = {
                "goal": "Explain publication",
                "actions": [
                    {
                        "sequence": 1,
                        "tool_name": "context.retrieve.v1",
                        "arguments": {"query": "publication review"},
                        "purpose": "Read guidance",
                    }
                ],
                "success_criteria": ["Explain review"],
                "risk_level": "low",
                "assumptions": [],
            }
        else:
            data = json.loads(request.messages[1].content.split("\n", 1)[1])
            assert data["completed_actions"][0]["tool_result"]["retrieval"]["citations"]
            content = {
                "decision": "complete",
                "justification": "Source identifies review.",
                "final_result": answer(),
            }
        return StructuredModelResult(
            content=content,
            provider="fixture",
            model="scripted",
            metrics=ModelMetrics(total_duration_ms=1),
        )


def test_grounding_persists_complete_four_phase_run(tmp_path: Path):
    store, run = setup_run(tmp_path)
    headers_seen = []

    def respond(request: httpx.Request) -> httpx.Response:
        headers_seen.append(dict(request.headers))
        if request.method == "POST":
            payload = json.loads(request.content)
            assert payload["feature_key"] == FEATURE
            return httpx.Response(200, json=retrieval().model_dump(mode="json"))
        version = CorpusVersion(
            feature_key=FEATURE,
            corpus_id=CORPUS,
            corpus_version="a" * 64,
            document_count=1,
            chunk_count=1,
            embedding_model="fixture",
            embedding_dimensions=1,
            ingested_at=NOW,
        )
        return httpx.Response(200, json=version.model_dump(mode="json"))

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        executor = RetrievalToolExecutor(
            UnconfiguredToolExecutor(),
            store,
            base_url="http://127.0.0.1:5012",
            service_token="x" * 32,
            client=client,
        )
        prompt_root = Path(__file__).resolve().parents[1] / "src/ai_mode/prompt_assets"
        runner = AgentRunner(
            store=store,
            provider=GuidedProvider(),
            prompt_builder=RegistryPromptBuilder(PromptRegistry(prompt_root)),
            tools=ToolRegistry([retrieval_definition()], shared_tools=["context.retrieve.v1"]),
            tool_executor=executor,
            grounding_verifier=executor,
            clock=SystemClock(),
            ids=UUID4Generator(),
        )
        finished = runner.run_until_blocked(run.id)
    assert finished.status == "succeeded"
    assert finished.final_result["citations"][0]["source_uri"] == "https://example.org/guidance"
    restored = SQLiteRunStore(tmp_path / "state.sqlite3").get(run.id)
    assert restored.run == finished
    assert [step.phase.value for step in restored.steps] == ["plan", "act", "observe", "adapt"]
    assert finished.trusted_identifiers == ()
    assert all(value["authorization"] == "Bearer " + "x" * 32 for value in headers_seen)


@pytest.mark.parametrize("fault", ["timeout", "oversize", "wrong_scope", "redirect", "malformed"])
def test_retrieval_transport_degrades_safely(tmp_path: Path, fault: str):
    store, run = setup_run(tmp_path)

    def respond(request: httpx.Request) -> httpx.Response:
        if fault == "timeout":
            raise httpx.ReadTimeout("failure")
        if fault == "oversize":
            return httpx.Response(200, content=b"x" * 64001)
        if fault == "redirect":
            return httpx.Response(307, headers={"Location": "http://elsewhere"})
        if fault == "malformed":
            return httpx.Response(200, content=b"broken")
        return httpx.Response(
            200, json={"feature_key": "other", "corpus_id": CORPUS, "status": "empty"}
        )

    call = ToolCall(
        id=uuid4(),
        run_id=run.id,
        step_id=uuid4(),
        request_id="test",
        tool_name="context.retrieve.v1",
        tool_version="v1",
        arguments={"query": "publication"},
        approval_status=ApprovalStatus.NOT_REQUIRED,
    )
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        executor = RetrievalToolExecutor(
            UnconfiguredToolExecutor(),
            store,
            base_url="http://127.0.0.1:5012",
            service_token="x" * 32,
            client=client,
        )
        result = executor.execute(call, retrieval_definition(), timeout_ms=1000)
    assert result.retrieval.status == "unavailable"
    assert result.retrieval.citations == ()


def test_citation_projection_keeps_complete_evidence():
    result = ToolResult(
        call_id=uuid4(),
        outcome=ToolOutcome.SUCCEEDED,
        duration_ms=1,
        content={"large": "x" * 16000},
        retrieval=retrieval(),
    )
    projection = _project_tool_result(result)
    assert projection["retrieval"] == retrieval().model_dump(mode="json")
    assert len(json.dumps(projection["content"])) < 8500


@pytest.mark.parametrize("environment", ["cloud", "azure", "production"])
def test_cloud_cannot_enable_advanced_runtime(environment: str):
    with pytest.raises(ConfigurationError, match="local-only"):
        Settings(environment=environment, rag_enabled=True, rag_service_token="x" * 32)


def test_legacy_grounding_defaults_remain_readable(tmp_path: Path):
    _, run = setup_run(tmp_path)
    legacy = run.model_dump(mode="json")
    legacy.pop("grounding")
    old = type(run).model_validate(legacy)
    assert old.grounding is None
    assert validate_grounded_answer(old, {"summary": "Legacy answer"}, ()) == {
        "summary": "Legacy answer"
    }
