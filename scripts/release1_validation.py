"""Named local Release 1 validations using the shared runner and real service transports.

The provider deliberately scripts the two model decisions. It copies actual retrieved
evidence, never invents citations, and is not a live-provider or semantic-quality demo.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from pydantic import JsonValue

from agent_core import (
    AgentRunner,
    ModelMetrics,
    ProviderHealth,
    StructuredModelRequest,
    StructuredModelResult,
    ToolExecutor,
    ToolRegistry,
    create_run,
)
from ai_mode.adapters.mcp_tools import McpToolExecutor
from ai_mode.adapters.retrieval import RetrievalToolExecutor, retrieval_definition
from ai_mode.adapters.system import SystemClock, UUID4Generator
from ai_mode.persistence import SQLiteRunStore
from ai_mode.prompts import PromptRegistry, RegistryPromptBuilder
from ai_mode.services import UnconfiguredToolExecutor
from ai_mode.tool_catalog import load_tool_catalogs
from scripts.devtools import host_runtime
from scripts.devtools.config import REPOSITORY_ROOT
from shared_contracts import (
    AgentRunRequest,
    RunStatus,
    SideEffectClass,
    ToolDefinition,
    ToolOutcome,
)
from shared_contracts.deployment import DeploymentProjectionV1
from shared_contracts.grounding import RETRIEVAL_TOOL, GroundingRequest

Mode = Literal["mcp", "rag"]
FEATURE = "student-1-propertyscope-data-platform"
CORPUS = "operator-guidance"
QUERY = "What review and approval are required before publishing a dataset release?"


def _enabled_projection() -> DeploymentProjectionV1:
    return DeploymentProjectionV1.model_validate_json(
        (REPOSITORY_ROOT / "deployment/enabled-features.v1.json").read_text(encoding="utf-8")
    )


def resolve_corpus(feature: str) -> str:
    """Return the corpus the given feature registered in its own manifest."""
    for enabled in _enabled_projection().features:
        if enabled.feature_key != feature:
            continue
        if enabled.ai is None or enabled.ai.rag_corpus_id is None:
            raise RuntimeError(
                f"{feature} has not registered a RAG corpus; declare ai.rag_corpus and "
                "ai.rag_corpus_id in its feature.yaml, then ingest the manifest"
            )
        return enabled.ai.rag_corpus_id
    raise RuntimeError(f"{feature} is not an enabled feature")


def _validation_callable(definition: ToolDefinition) -> bool:
    """A validation tool must be safe to call and need no model-supplied arguments.

    The deterministic planner sends an empty argument object, so any required input makes
    the call fail validation. Restricting to unapproved read-only tools keeps a named
    validation from dispatching a write against the running local backend.
    """
    return (
        definition.side_effect is SideEffectClass.READ_ONLY
        and not definition.requires_approval
        and not definition.input_schema.get("required")
    )


def resolve_mcp_tool(
    catalog_paths: Sequence[Path], feature: str, tool: str | None
) -> ToolDefinition:
    """Pick a registered read-only tool this validation can call with no arguments.

    Owners without one can register a no-argument read-only capabilities tool as Feature 1
    does. An explicit ``tool`` must satisfy the same rule: the guard exists to keep the
    loop from dispatching a write, so naming a tool does not bypass it.
    """
    owned = [
        item.definition
        for item in load_tool_catalogs(tuple(catalog_paths)).tools
        if item.definition.feature_key == feature
    ]
    if not owned:
        raise RuntimeError(f"{feature} has no registered tools in the running host catalogue")
    if tool is not None:
        for definition in owned:
            if definition.name != tool:
                continue
            if not _validation_callable(definition):
                raise RuntimeError(
                    f"{tool} is not usable for validation; it must be read-only, need no "
                    "approval, and have no required inputs"
                )
            return definition
        raise RuntimeError(f"{feature} does not register the tool {tool}")
    for definition in owned:
        if _validation_callable(definition):
            return definition
    raise RuntimeError(
        f"{feature} registers no argument-free read-only tool; add one, as Feature 1's "
        "platform.capabilities.v1 does, or pass --tool with one"
    )


class ValidationProvider:
    """Make repeatable decisions while retaining real tool and retrieval evidence."""

    def __init__(self, store: SQLiteRunStore, tool: str, query: str) -> None:
        self.store, self.tool, self.query = store, tool, query

    def health(self) -> ProviderHealth:
        return ProviderHealth(reachable=True, detail="Deterministic validation decisions")

    def generate_structured(self, request: StructuredModelRequest) -> StructuredModelResult:
        if request.role.value == "planner":
            content: dict[str, JsonValue] = {
                "goal": "Validate the registered local service through the shared agent loop",
                "actions": [
                    {
                        "sequence": 1,
                        "tool_name": self.tool,
                        "arguments": {"query": self.query} if self.tool == RETRIEVAL_TOOL else {},
                        "purpose": "Read bounded validation evidence",
                    }
                ],
                "success_criteria": ["The registered local service returns structured evidence"],
                "risk_level": "low",
                "assumptions": [],
            }
        else:
            detail = self.store.get(request.run_id)
            if detail is None:
                raise RuntimeError("Validation run was not persisted")
            results = [
                result for step in detail.steps for result in AgentRunner._step_tool_results(step)
            ]
            retrievals = [result.retrieval for result in results if result.retrieval is not None]
            final: dict[str, JsonValue] = {
                "summary": "Registered MCP tool returned structured evidence."
            }
            if retrievals:
                latest = retrievals[-1]
                ready = latest.status == "ready"
                final = {
                    "summary": "Retrieved project guidance." if ready else "Insufficient context.",
                    "findings": [
                        {
                            "text": citation.excerpt[:1500],
                            "kind": "guidance",
                            "citation_ids": [citation.citation_id],
                        }
                        for citation in latest.citations[:1]
                    ],
                    "confidence": "moderate" if ready else "insufficient",
                    "confidence_reason": "Extractive validation; review source support.",
                    "evidence_gaps": [],
                    "next_step": "Review the linked source before acting.",
                    "safety_boundary": "Read-only guidance validation; no publication or approval.",
                }
            if any(result.outcome is not ToolOutcome.SUCCEEDED for result in results):
                content = {"decision": "fail", "justification": "The validation tool failed"}
            else:
                content = {
                    "decision": "complete",
                    "justification": "Validation evidence was observed",
                    "final_result": final,
                }
        return StructuredModelResult(
            content=content,
            provider="deterministic-validation",
            model="extractive-validation.v1",
            metrics=ModelMetrics(total_duration_ms=0),
        )


def execute_validation(
    mode: Mode,
    store: SQLiteRunStore,
    definition: ToolDefinition,
    executor: ToolExecutor,
    *,
    query: str = QUERY,
    corpus: str = CORPUS,
    feature: str = FEATURE,
) -> dict[str, JsonValue]:
    """Run all four production phases; injection keeps the unit suite network-free."""
    clock, ids = SystemClock(), UUID4Generator()
    request = AgentRunRequest(
        feature_key=feature,
        objective=query if mode == "rag" else "Validate local MCP tool dispatch",
        grounding=GroundingRequest(corpus_id=corpus) if mode == "rag" else None,
        prompt_set="default.v8",
        tool_allowlist=(definition.name,),
    )
    run = create_run(
        request, run_id=ids.new(), request_id=f"r1-{mode}-{ids.new()}", now=clock.now()
    )
    store.create(run)
    prompt_root = REPOSITORY_ROOT / "ai-services/ai-mode/src/ai_mode/prompt_assets"
    runner = AgentRunner(
        store=store,
        provider=ValidationProvider(store, definition.name, query),
        prompt_builder=RegistryPromptBuilder(PromptRegistry(prompt_root)),
        tools=ToolRegistry((definition,), shared_tools=(RETRIEVAL_TOOL,) if mode == "rag" else ()),
        tool_executor=executor,
        clock=clock,
        ids=ids,
        grounding_verifier=executor if isinstance(executor, RetrievalToolExecutor) else None,
    )
    finished = runner.run_until_blocked(run.id)
    detail = store.get(run.id)
    if detail is None:
        raise RuntimeError(f"validation run {run.id} was not stored")
    results = [result for step in detail.steps for result in AgentRunner._step_tool_results(step)]
    phases = [step.phase.value for step in detail.steps]
    passed = (
        finished.status is RunStatus.SUCCEEDED
        and phases == ["plan", "act", "observe", "adapt"]
        and bool(results)
        and all(result.outcome is ToolOutcome.SUCCEEDED for result in results)
    )
    # An unavailable dependency must not be reported as a successful RAG validation.
    if mode == "rag":
        passed = passed and any(
            result.retrieval is not None
            and result.retrieval.status in {"ready", "no_match", "empty"}
            for result in results
        )
    return {
        "schema_version": "1.0",
        "mode": mode,
        "feature_key": feature,
        "tool_name": definition.name,
        "corpus_id": corpus if mode == "rag" else None,
        "passed": passed,
        "decision_provider": "deterministic-validation",
        "transport": "live-local-services",
        "evidence_boundary": (
            "Production runner and local services; deterministic model decisions, "
            "not provider answer quality."
        ),
        "run_id": str(run.id),
        "request_id": run.request_id,
        "status": finished.status.value,
        "phases": list(phases),
        "tool_results": [result.model_dump(mode="json") for result in results],
        "final_result": finished.final_result,
        "error": finished.error.model_dump(mode="json") if finished.error else None,
    }


def validate(
    mode: Mode,
    environment: Mapping[str, str],
    *,
    output: Path | None = None,
    query: str = QUERY,
    corpus: str | None = None,
    feature: str = FEATURE,
    tool: str | None = None,
) -> dict[str, JsonValue]:
    """Use already running services, without restarting or editing their durable stores."""
    if environment.get("CI", "").lower() in {"true", "1"}:
        raise RuntimeError("Live MCP/RAG validation is local-only; CI uses injected test doubles")
    resolved = host_runtime.prepare_environment(environment, mode=mode)
    # Only a grounded run needs a scope; MCP validation must not require a registered corpus.
    resolved_corpus = CORPUS
    if mode == "rag":
        resolved_corpus = corpus if corpus is not None else resolve_corpus(feature)
    with TemporaryDirectory(prefix="propertyscope-r1-validation-") as directory:
        store = SQLiteRunStore(Path(directory) / "validation.sqlite3")
        store.initialize()
        executor: ToolExecutor
        if mode == "mcp":
            definition = resolve_mcp_tool(
                tuple(Path(path) for path in resolved["AI_MODE_TOOL_CATALOG_PATHS"].split(",")),
                feature,
                tool,
            )
            executor = McpToolExecutor(
                base_url=resolved["MCP_SERVER_URL"], service_token=resolved["MCP_SERVICE_TOKEN"]
            )
        else:
            definition = retrieval_definition()
            executor = RetrievalToolExecutor(
                UnconfiguredToolExecutor(),
                store,
                base_url=resolved["RAG_SERVER_URL"],
                service_token=resolved["RAG_SERVICE_TOKEN"],
            )
        try:
            evidence = execute_validation(
                mode,
                store,
                definition,
                executor,
                query=query,
                corpus=resolved_corpus,
                feature=feature,
            )
        finally:
            executor.close()
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    return evidence
