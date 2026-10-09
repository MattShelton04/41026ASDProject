"""Dependency graph for the AI-mode application factory."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from agent_core import (
    AgentRunner,
    Clock,
    IdGenerator,
    LLMProvider,
    RecoveryDisposition,
    RunQueue,
    RunStore,
    ToolExecutor,
    ToolRegistry,
)
from ai_mode.adapters.mcp_tools import McpToolExecutor
from ai_mode.adapters.retrieval import RetrievalToolExecutor, retrieval_definition
from ai_mode.adapters.system import SystemClock, UUID4Generator
from ai_mode.configuration import ConfigurationError, Settings
from ai_mode.knowledge import KnowledgeClient
from ai_mode.operations import RunReader
from ai_mode.persistence import SQLiteRunStore
from ai_mode.prompts import PromptRegistry, RegistryPromptBuilder
from ai_mode.providers import build_provider, configured_model_registry
from ai_mode.queue import SerialRunQueue
from ai_mode.tool_catalog import build_tool_runtime, load_tool_catalogs
from shared_contracts import (
    ModelRegistry,
    ToolCall,
    ToolDefinition,
    ToolError,
    ToolOutcome,
    ToolResult,
)
from shared_contracts.grounding import RETRIEVAL_TOOL


class UnconfiguredToolExecutor(ToolExecutor):
    """Defensive adapter used until feature-owned HTTP tools are registered."""

    def execute(
        self,
        call: ToolCall,
        definition: ToolDefinition,
        *,
        timeout_ms: int,
    ) -> ToolResult:
        return ToolResult(
            call_id=call.id,
            outcome=ToolOutcome.FAILED,
            error=ToolError(
                code="tool_executor_unconfigured",
                message="No feature tool executor is configured",
            ),
            duration_ms=0,
            retryable=False,
        )


@dataclass(slots=True)
class AppServices:
    """Injected runtime dependencies used by routes and the background worker."""

    store: RunStore
    provider: LLMProvider
    queue: RunQueue
    clock: Clock
    ids: IdGenerator
    default_model_profile: str
    model_registry: ModelRegistry | None = None
    run_reader: RunReader | None = None
    closeables: tuple[object, ...] = ()
    rag_corpora: tuple[tuple[str, str], ...] = ()
    mcp_enabled: bool = False
    knowledge: KnowledgeClient | None = None

    def close(self) -> None:
        """Best-effort cleanup of owned queues, clients, and providers."""
        for resource in self.closeables:
            close = getattr(resource, "close", None)
            if callable(close):
                close()


def build_services(settings: Settings) -> AppServices:
    """Build the default dependency graph without contacting the model provider."""
    store = SQLiteRunStore(settings.database_path)
    store.initialize()
    model_registry, default_model_profile = configured_model_registry(settings)
    provider = build_provider(
        settings,
        registry=model_registry,
        readiness_profile=default_model_profile,
    )
    clock = SystemClock()
    ids = UUID4Generator()
    prompt_root = Path(__file__).resolve().parent / "prompt_assets"
    registry = PromptRegistry(prompt_root)
    prompt_builder = RegistryPromptBuilder(registry)
    prompt_builder.validate_declared()
    catalog_paths = settings.configured_tool_catalog_paths
    definitions: tuple[ToolDefinition, ...] = ()
    shared_tools: tuple[str, ...] = ()
    if not catalog_paths:
        tools = ToolRegistry(())
        tool_executor: ToolExecutor = UnconfiguredToolExecutor()
    else:
        catalog = load_tool_catalogs(catalog_paths)
        definitions = tuple(item.definition for item in catalog.tools)
        shared_tools = catalog.shared_tools
        tools, tool_executor = build_tool_runtime(
            catalog,
            max_request_bytes=settings.max_tool_request_bytes,
            max_response_bytes=settings.max_tool_response_bytes,
        )
    if settings.mcp_enabled:
        if settings.mcp_service_token is None:
            raise ConfigurationError("Enabled local AI services require a 32-character token")
        close = getattr(tool_executor, "close", None)
        if callable(close):
            close()
        tool_executor = McpToolExecutor(
            base_url=settings.mcp_server_url,
            service_token=settings.mcp_service_token,
            max_response_bytes=settings.max_tool_response_bytes,
        )
    retrieval_executor = None
    knowledge = None
    if settings.rag_enabled:
        if settings.rag_service_token is None:
            raise ConfigurationError("Enabled local AI services require a 32-character token")
        tools = ToolRegistry(
            (*definitions, retrieval_definition()), shared_tools=(*shared_tools, RETRIEVAL_TOOL)
        )
        retrieval_executor = RetrievalToolExecutor(
            tool_executor,
            store,
            base_url=settings.rag_server_url,
            service_token=settings.rag_service_token,
        )
        tool_executor = retrieval_executor
        knowledge = KnowledgeClient(
            base_url=settings.rag_server_url, service_token=settings.rag_service_token
        )
    runner = AgentRunner(
        store=store,
        provider=provider,
        prompt_builder=prompt_builder,
        tools=tools,
        tool_executor=tool_executor,
        clock=clock,
        ids=ids,
        grounding_verifier=retrieval_executor,
    )

    def discover_resumable() -> Iterable[UUID]:
        for detail in store.list_resumable():
            decision = runner.recover_interrupted(detail)
            if decision.disposition is RecoveryDisposition.REENQUEUE:
                yield decision.run.id

    queue = SerialRunQueue(
        runner.run_until_blocked,
        discover=discover_resumable,
        capacity=settings.queue_capacity,
        reconcile_interval_seconds=settings.queue_reconcile_interval_seconds,
    )
    return AppServices(
        store=store,
        provider=provider,
        queue=queue,
        clock=clock,
        ids=ids,
        model_registry=model_registry,
        run_reader=store,
        default_model_profile=default_model_profile,
        closeables=(queue, tool_executor, provider, knowledge),
        rag_corpora=settings.rag_corpora if settings.rag_enabled else (),
        mcp_enabled=settings.mcp_enabled,
        knowledge=knowledge,
    )
