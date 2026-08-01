"""Tests for the default dependency graph and defensive tool adapter."""

from pathlib import Path
from uuid import uuid4

from ai_mode.configuration import Settings
from ai_mode.queue import SerialRunQueue
from ai_mode.services import UnconfiguredToolExecutor, build_services
from shared_contracts import ApprovalStatus, SideEffectClass, ToolCall, ToolDefinition


def test_default_services_initialize_without_contacting_ollama(tmp_path: Path) -> None:
    services = build_services(
        Settings(
            database_path=tmp_path / "state.sqlite3",
            ollama_base_url="http://ollama.invalid",
            ollama_model="qwen2.5:0.5b",
            ollama_timeout_seconds=1,
            ollama_keep_alive="5m",
            max_model_response_bytes=100_000,
        )
    )

    assert services.store.health().ready is True
    assert services.clock.now().tzinfo is not None
    assert services.ids.new() != services.ids.new()
    assert isinstance(services.queue, SerialRunQueue)
    services.queue.close()
    services.provider.close()  # type: ignore[attr-defined]


def test_unconfigured_tool_executor_returns_safe_terminal_result() -> None:
    run_id = uuid4()
    step_id = uuid4()
    call = ToolCall(
        id=uuid4(),
        run_id=run_id,
        step_id=step_id,
        tool_name="student_1.records.search.v1",
        tool_version="v1",
        approval_status=ApprovalStatus.NOT_REQUIRED,
    )
    definition = ToolDefinition(
        name=call.tool_name,
        version="v1",
        description="Search records",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        side_effect=SideEffectClass.READ_ONLY,
    )

    result = UnconfiguredToolExecutor().execute(call, definition, timeout_ms=1_000)

    assert result.outcome.value == "failed"
    assert result.error is not None
    assert result.error.code == "tool_executor_unconfigured"
