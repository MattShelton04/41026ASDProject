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
from ai_mode.persistence import SQLiteRunStore
from ai_mode.prompts import PromptRegistry, RegistryPromptBuilder
from ai_mode.providers import build_ollama_provider, configured_model_registry
from ai_mode.queue import SerialRunQueue
from ai_mode.tool_catalog import build_tool_runtime, load_tool_catalog
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
    model_registry: ModelRegistry | None = None
    default_model_profile: str = "local-standard.v1"
    closeables: tuple[object, ...] = ()

    def close(self) -> None:
        """Best-effort cleanup of owned queues, clients, and providers."""
        for resource in self.closeables:
            close = getattr(resource, "close", None)
            if callable(close):
                close()


def build_services(settings: Settings) -> AppServices:
    """Build the default Release 0 dependency graph without contacting Ollama."""
    store = SQLiteRunStore(settings.database_path)
    store.initialize()
    model_registry, default_model_profile = configured_model_registry(settings)
    provider = build_ollama_provider(
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
    if settings.tool_catalog_path is None:
        tools = ToolRegistry(())
        tool_executor: ToolExecutor = UnconfiguredToolExecutor()
    else:
        tools, tool_executor = build_tool_runtime(
            load_tool_catalog(settings.tool_catalog_path),
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

    queue = SerialRunQueue(runner.run_until_blocked, discover=discover_resumable)
    return AppServices(
        store=store,
        provider=provider,
        queue=queue,
        clock=clock,
        ids=ids,
        model_registry=model_registry,
        default_model_profile=default_model_profile,
        closeables=(queue, tool_executor, provider),
    )
