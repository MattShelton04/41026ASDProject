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
from ai_mode.adapters.system import SystemClock, UUID4Generator
from ai_mode.configuration import Settings
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
    if not catalog_paths:
        tools = ToolRegistry(())
        tool_executor: ToolExecutor = UnconfiguredToolExecutor()
    else:
        tools, tool_executor = build_tool_runtime(
            load_tool_catalogs(catalog_paths),
            max_request_bytes=settings.max_tool_request_bytes,
            max_response_bytes=settings.max_tool_response_bytes,
        )
    runner = AgentRunner(
        store=store,
        provider=provider,
        prompt_builder=prompt_builder,
        tools=tools,
        tool_executor=tool_executor,
        clock=clock,
        ids=ids,
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
        closeables=(queue, tool_executor, provider),
    )
