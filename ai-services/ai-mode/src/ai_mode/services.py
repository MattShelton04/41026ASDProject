"""Dependency graph for the AI-mode application factory."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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
from ai_mode.adapters.ollama import OllamaModelProfile, OllamaProvider
from ai_mode.adapters.system import SystemClock, UUID4Generator
from ai_mode.configuration import Settings
from ai_mode.persistence import SQLiteRunStore
from ai_mode.prompts import PromptRegistry, RegistryPromptBuilder
from ai_mode.queue import SerialRunQueue
from shared_contracts import ToolCall, ToolDefinition, ToolError, ToolOutcome, ToolResult


class UnconfiguredToolExecutor(ToolExecutor):
    """Defensive adapter used until feature-owned HTTP tools are registered."""

    def execute(self, call: ToolCall, definition: ToolDefinition) -> ToolResult:
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


def build_services(settings: Settings) -> AppServices:
    """Build the default Release 0 dependency graph without contacting Ollama."""
    store = SQLiteRunStore(settings.database_path)
    store.initialize()
    provider = OllamaProvider(
        base_url=settings.ollama_base_url,
        profiles={
            "local-small.v1": OllamaModelProfile(
                model=settings.ollama_model,
                keep_alive=settings.ollama_keep_alive,
            )
        },
        timeout_seconds=settings.ollama_timeout_seconds,
        max_response_bytes=settings.max_model_response_bytes,
    )
    clock = SystemClock()
    ids = UUID4Generator()
    prompt_root = Path(__file__).resolve().parent / "prompt_assets"
    registry = PromptRegistry(prompt_root)
    registry.load("planner", "v1")
    registry.load("adapter", "v1")
    runner = AgentRunner(
        store=store,
        provider=provider,
        prompt_builder=RegistryPromptBuilder(registry),
        tools=ToolRegistry(()),
        tool_executor=UnconfiguredToolExecutor(),
        clock=clock,
        ids=ids,
    )
    resumable_ids = tuple(
        decision.run.id
        for detail in store.list_resumable()
        if (decision := runner.recover_interrupted(detail)).disposition
        is RecoveryDisposition.REENQUEUE
    )
    queue = SerialRunQueue(runner.run_until_blocked)
    for run_id in resumable_ids:
        queue.enqueue(run_id)
    return AppServices(store=store, provider=provider, queue=queue, clock=clock, ids=ids)
