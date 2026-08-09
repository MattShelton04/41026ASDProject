"""Real-HTTP integration proof for the shared tool and feature boundaries."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import Thread
from uuid import UUID, uuid4

import httpx
from flask import Flask
from werkzeug.serving import BaseWSGIServer, WSGIRequestHandler, make_server

from agent_core import (
    AgentRunner,
    ModelMessage,
    ModelMetrics,
    ModelRole,
    StructuredModelRequest,
    StructuredModelResult,
    ToolRegistry,
    create_run,
)
from ai_mode.adapters.http_tools import HttpToolBinding, HttpToolExecutor
from ai_mode.persistence import SQLiteRunStore
from ai_mode.tool_catalog import load_tool_catalog
from integration_test_feature import (
    IntegrationRecordStore,
    create_backend_app,
    create_database_app,
)
from shared_contracts import (
    IDEMPOTENCY_KEY_HEADER,
    AgentRun,
    AgentRunRequest,
    Observation,
    Plan,
    RunStatus,
    ToolDefinition,
    ToolResult,
)
from shared_testkit import ScriptedLLMProvider, assert_problem_detail

NOW = datetime(2026, 8, 1, tzinfo=UTC)
CATALOG_PATH = Path(__file__).parents[1] / "tool-catalog.yaml"


class _QuietRequestHandler(WSGIRequestHandler):
    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        pass


@contextmanager
def _serve(app: Flask) -> Iterator[str]:
    server: BaseWSGIServer = make_server(
        "127.0.0.1",
        0,
        app,
        threaded=True,
        request_handler=_QuietRequestHandler,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


class _Clock:
    def now(self) -> datetime:
        return NOW


class _Ids:
    def new(self) -> UUID:
        return uuid4()


class _PromptBuilder:
    def build_plan_request(
        self,
        run: AgentRun,
        definitions: tuple[ToolDefinition, ...],
    ) -> StructuredModelRequest:
        assert [definition.name for definition in definitions] == [
            "integration_test.records.search.v1",
            "integration_test.records.inspect.v1",
            "integration_test.records.dependencies.v1",
            "integration_test.records.create.v1",
        ]
        return self._request(run, ModelRole.PLANNER)

    def build_adaptation_request(
        self,
        run: AgentRun,
        plan: Plan,
        tool_result: ToolResult,
        observation: Observation,
        tool_results: tuple[ToolResult, ...],
    ) -> StructuredModelRequest:
        assert len(tool_results) == len(plan.actions)
        return self._request(run, ModelRole.ADAPTER)

    @staticmethod
    def _request(run: AgentRun, role: ModelRole) -> StructuredModelRequest:
        return StructuredModelRequest(
            run_id=run.id,
            role=role,
            model_profile=run.model_profile,
            messages=(ModelMessage(role="system", content="Deterministic integration test"),),
            output_schema={},
            prompt_id=role.value,
            prompt_version="v1",
            prompt_hash="a" * 64,
            rendered_input_hash="b" * 64,
        )


def _tool_definitions() -> tuple[ToolDefinition, ...]:
    return tuple(registration.definition for registration in load_tool_catalog(CATALOG_PATH).tools)


def _model_result(content: dict[str, object]) -> StructuredModelResult:
    return StructuredModelResult(
        content=content,
        provider="scripted",
        model="fake",
        metrics=ModelMetrics(total_duration_ms=1),
    )


def test_tool_catalog_bindings_match_backend_routes() -> None:
    catalog = load_tool_catalog(CATALOG_PATH)
    app = create_backend_app("http://database.invalid")
    exposed = {
        (rule.rule, method)
        for rule in app.url_map.iter_rules()
        for method in rule.methods
        if method not in {"HEAD", "OPTIONS"}
    }
    registered = {(tool.path, tool.method) for tool in catalog.tools}

    assert registered <= exposed


def test_long_horizon_agent_loop_calls_three_feature_tools(tmp_path: Path) -> None:
    feature_store = IntegrationRecordStore(tmp_path / "feature.sqlite3")
    feature_store.initialize()
    with (
        _serve(create_database_app(feature_store)) as database_url,
        _serve(create_backend_app(database_url)) as backend_url,
    ):
        definitions = _tool_definitions()
        executor = HttpToolExecutor(
            service_base_urls={"integration-test-backend": backend_url},
            bindings=[
                HttpToolBinding(
                    tool_name=definition.name,
                    tool_version=definition.version,
                    service="integration-test-backend",
                    method="POST",
                    path=next(
                        registration.path
                        for registration in load_tool_catalog(CATALOG_PATH).tools
                        if registration.definition.name == definition.name
                    ),
                )
                for definition in definitions
            ],
        )
        state_store = SQLiteRunStore(tmp_path / "agent-state.sqlite3")
        state_store.initialize()
        run = create_run(
            AgentRunRequest(
                feature_key="student-1-integration-test",
                objective=(
                    "Audit Reference record 03 by searching for it, inspecting it, "
                    "and checking every direct dependency"
                ),
            ),
            run_id=uuid4(),
            request_id="integration-request",
            now=NOW,
        )
        state_store.create(run)
        provider = ScriptedLLMProvider(
            [
                _model_result(
                    {
                        "goal": "Count seeded records",
                        "actions": [
                            {
                                "sequence": 1,
                                "tool_name": "integration_test.records.search.v1",
                                "arguments": {"query": "Reference record"},
                                "purpose": "Search through the feature backend",
                            },
                            {
                                "sequence": 2,
                                "tool_name": "integration_test.records.inspect.v1",
                                "arguments": {"title": "Reference record 03"},
                                "purpose": "Inspect priority and summary",
                            },
                            {
                                "sequence": 3,
                                "tool_name": "integration_test.records.dependencies.v1",
                                "arguments": {"title": "Reference record 03"},
                                "purpose": "Verify dependency status",
                            },
                        ],
                        "success_criteria": [
                            "The target record is found",
                            "Its priority and summary are inspected",
                            "Every direct dependency status is reported",
                        ],
                        "risk_level": "low",
                        "assumptions": [],
                    }
                ),
                _model_result(
                    {
                        "decision": "complete",
                        "justification": "All dependency evidence is available",
                        "final_result": {
                            "record": "Reference record 03",
                            "priority": 3,
                            "dependency_count": 2,
                            "all_dependencies_active": True,
                        },
                    }
                ),
            ]
        )
        runner = AgentRunner(
            store=state_store,
            provider=provider,
            prompt_builder=_PromptBuilder(),
            tools=ToolRegistry(definitions),
            tool_executor=executor,
            clock=_Clock(),
            ids=_Ids(),
        )

        result = runner.run_until_blocked(run.id)
        executor.close()

    assert result.status is RunStatus.SUCCEEDED
    assert result.final_result == {
        "record": "Reference record 03",
        "priority": 3,
        "dependency_count": 2,
        "all_dependencies_active": True,
    }
    detail = state_store.get(run.id)
    assert detail is not None
    assert [step.phase.value for step in detail.steps] == [
        "plan",
        "act",
        "observe",
        "adapt",
        "act",
        "observe",
        "adapt",
        "act",
        "observe",
        "adapt",
    ]
    assert result.iteration_count == 3
    assert result.tool_call_count == 3
    assert len(state_store.list_events(run.id)) == 18


def test_record_detail_and_dependency_tools_return_richer_evidence(tmp_path: Path) -> None:
    feature_store = IntegrationRecordStore(tmp_path / "feature.sqlite3")
    feature_store.initialize()
    with (
        _serve(create_database_app(feature_store)) as database_url,
        _serve(create_backend_app(database_url)) as backend_url,
        httpx.Client(base_url=backend_url) as client,
    ):
        ready = client.get("/health/ready")
        detail = client.post(
            "/api/v1/tools/records.inspect.v1",
            json={"title": "Reference record 03"},
            headers={"X-Request-ID": "fixture-detail"},
        )
        dependencies = client.post(
            "/api/v1/tools/records.dependencies.v1",
            json={"title": "Reference record 03"},
            headers={"X-Request-ID": "fixture-dependencies"},
        )
        missing = client.post(
            "/api/v1/tools/records.inspect.v1",
            json={"title": "Missing record"},
        )
        missing_dependencies = client.post(
            "/api/v1/tools/records.dependencies.v1",
            json={"title": "Missing record"},
        )
        invalid_detail = client.post("/api/v1/tools/records.inspect.v1", json={})
        invalid_dependencies = client.post("/api/v1/tools/records.dependencies.v1", json={})

    assert ready.status_code == 200
    assert ready.json() == {"status": "healthy"}
    assert detail.status_code == 200
    assert detail.json()["record"] == {
        "id": 3,
        "title": "Reference record 03",
        "status": "active",
        "summary": "Deterministic evidence item 03 for integration testing.",
        "priority": 3,
    }
    assert dependencies.status_code == 200
    assert dependencies.json()["count"] == 2
    assert dependencies.json()["all_active"] is True
    assert [item["title"] for item in dependencies.json()["items"]] == [
        "Reference record 01",
        "Reference record 02",
    ]
    assert missing.status_code == 404
    assert_problem_detail(missing.json(), status=404, code="record_not_found")
    assert missing.headers["content-type"].startswith("application/problem+json")
    assert missing_dependencies.status_code == 404
    assert_problem_detail(missing_dependencies.json(), status=404, code="record_not_found")
    assert invalid_detail.status_code == 422
    assert_problem_detail(invalid_detail.json(), status=422, code="invalid_arguments")
    assert invalid_dependencies.status_code == 422
    assert_problem_detail(invalid_dependencies.json(), status=422, code="invalid_arguments")


def test_console_assets_expose_safe_trace_and_long_horizon_controls() -> None:
    frontend = CATALOG_PATH.parent / "frontend"
    document = (frontend / "index.html").read_text(encoding="utf-8")
    script = (frontend / "app.js").read_text(encoding="utf-8")
    proxy = (frontend / "nginx.conf").read_text(encoding="utf-8")

    assert 'id="conversation"' in document
    assert 'id="event-feed"' in document
    assert 'id="run-metadata"' in document
    assert "Longer-horizon dependency audit" in document
    assert "Raw safe run detail" in document
    assert "jsonRequest(`${currentLocation}/events?after=${cursor}&limit=200`)" in script
    assert "traceparent: newTraceparent()" in script
    assert "renderInvocation(article, step.output.model_invocation)" in script
    assert "signature === lastRenderedDetailSignature" in script
    assert 'querySelectorAll("details[open][data-state-key]")' in script
    assert "events.body.items.length > 0 || !currentRun" in script
    assert "proxy_set_header X-Request-ID $correlation_request_id" in proxy


def test_mutation_replay_has_one_effect_and_reports_operation_status(tmp_path: Path) -> None:
    feature_store = IntegrationRecordStore(tmp_path / "feature.sqlite3")
    feature_store.initialize()
    with (
        _serve(create_database_app(feature_store)) as database_url,
        _serve(create_backend_app(database_url)) as backend_url,
        httpx.Client(base_url=backend_url) as client,
    ):
        operation_key = f"{uuid4()}:call:{uuid4()}"
        headers = {IDEMPOTENCY_KEY_HEADER: operation_key}
        first = client.post(
            "/api/v1/tools/records.create.v1",
            json={"title": "Created once"},
            headers=headers,
        )
        replay = client.post(
            "/api/v1/tools/records.create.v1",
            json={"title": "Created once"},
            headers=headers,
        )
        conflict = client.post(
            "/api/v1/tools/records.create.v1",
            json={"title": "Different arguments"},
            headers=headers,
        )
        applied = client.get(f"/api/v1/tool-operations/{operation_key}")
        missing_key = f"{uuid4()}:call:{uuid4()}"
        missing = client.get(f"/api/v1/tool-operations/{missing_key}")
        unknown = client.get("/api/v1/tool-operations/not-a-call-key")
        concurrent_key = f"{uuid4()}:call:{uuid4()}"

        def create_concurrently(_: int) -> httpx.Response:
            return httpx.post(
                f"{backend_url}/api/v1/tools/records.create.v1",
                json={"title": "Concurrent single effect"},
                headers={IDEMPOTENCY_KEY_HEADER: concurrent_key},
                timeout=2,
            )

        with ThreadPoolExecutor(max_workers=5) as pool:
            concurrent_results = list(pool.map(create_concurrently, range(5)))

    assert first.status_code == 201
    assert replay.status_code == 200
    assert first.json()["created"] is True
    assert replay.json()["created"] is False
    assert replay.json()["record"] == first.json()["record"]
    assert conflict.status_code == 409
    assert applied.json()["status"] == "applied"
    assert missing.json() == {"status": "not_applied"}
    assert unknown.json() == {"status": "unknown"}
    assert len(feature_store.search("Created once")) == 1
    assert sorted(response.status_code for response in concurrent_results) == [
        200,
        200,
        200,
        200,
        201,
    ]
    assert sum(response.json()["created"] for response in concurrent_results) == 1
    assert len(feature_store.search("Concurrent single effect")) == 1
