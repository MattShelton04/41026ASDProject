"""Deterministic protocol, authentication and owning-tool boundary checks."""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.memory import create_connected_server_and_client_session
from mcp_server import create_app, create_server
from mcp_server.observability import JsonLogFormatter
from shared_tool_runtime import HttpToolBinding, HttpToolExecutor, ToolCatalog
from shared_tool_runtime.invocation import INVOCATION_META_KEY, sign_invocation

from shared_contracts import ApprovalStatus, ToolCall

TOKEN = "deterministic-test-service-token-123456"
FEATURE = "student-1-propertyscope-data-platform"


def tool_lines(caplog: pytest.LogCaptureFixture) -> list[dict[str, object]]:
    """MCP boundary records rendered by the production formatter, as the host log sees them."""
    formatter = JsonLogFormatter()
    return [
        json.loads(formatter.format(record))
        for record in caplog.records
        if getattr(record, "event", None) == "mcp.tool_call.completed"
    ]


def catalog() -> ToolCatalog:
    return ToolCatalog.model_validate(
        {
            "services": [{"service": "feature-api", "base_url": "http://127.0.0.1:5200"}],
            "tools": [
                {
                    "definition": {
                        "name": f"test.{name}.v1",
                        "version": "v1",
                        "feature_key": FEATURE,
                        "description": "A deterministic boundary test",
                        "input_schema": {
                            "type": "object",
                            "properties": {"value": {"type": "integer"}},
                            "required": ["value"],
                            "additionalProperties": False,
                        },
                        "output_schema": {
                            "type": "object",
                            "properties": {"value": {"type": "integer"}},
                            "required": ["value"],
                            "additionalProperties": False,
                        },
                        "side_effect": effect,
                    },
                    "service": "feature-api",
                    "path": f"/tools/{name}",
                }
                for name, effect in [
                    ("read", "read_only"),
                    ("write", "reversible_write"),
                    ("delete", "destructive_write"),
                ]
            ],
        }
    )


def call(name: str = "read", approval: ApprovalStatus = ApprovalStatus.NOT_REQUIRED) -> ToolCall:
    return ToolCall(
        id=uuid4(),
        run_id=uuid4(),
        step_id=uuid4(),
        request_id="test-correlation",
        tool_name=f"test.{name}.v1",
        tool_version="v1",
        arguments={"value": 7},
        approval_status=approval,
        idempotency_key="deterministic-write" if name != "read" else None,
    )


def executor(requests: list[httpx.Request]) -> HttpToolExecutor:
    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=json.loads(request.content))

    return HttpToolExecutor(
        service_base_urls={"feature-api": "http://127.0.0.1:5200"},
        bindings=[
            HttpToolBinding(
                tool_name=entry.definition.name,
                tool_version="v1",
                service="feature-api",
                method="POST",
                path=entry.path,
            )
            for entry in catalog().tools
        ],
        client=httpx.Client(transport=httpx.MockTransport(handle)),
    )


def metadata(invocation: ToolCall, **kwargs: object) -> dict[str, str]:
    return {
        INVOCATION_META_KEY: sign_invocation(
            invocation,
            feature_key=str(kwargs.get("feature_key", FEATURE)),
            service_token=str(kwargs.get("token", TOKEN)),
            timeout_ms=10_000,
            now=kwargs.get("now"),  # type: ignore[arg-type]
        )
    }


def test_sdk_discovers_original_schemas_resources_and_preserves_result() -> None:
    requests: list[httpx.Request] = []
    server = create_server(catalog(), service_token=TOKEN, executor=executor(requests))

    async def scenario() -> None:
        async with create_connected_server_and_client_session(server) as session:
            tools = (await session.list_tools()).tools
            assert len(tools) == 3
            assert tools[0].inputSchema == catalog().tools[0].definition.input_schema
            assert tools[0].annotations.readOnlyHint
            resources = (await session.list_resources()).resources
            resource = await session.read_resource(resources[0].uri)
            assert "feature-api" not in resource.model_dump_json()
            invocation = call()
            result = await session.call_tool(
                invocation.tool_name, invocation.arguments, meta=metadata(invocation)
            )
            assert not result.isError
            assert result.structuredContent == {"value": 7}
            assert result.meta["propertyscope/tool-result"]["call_id"] == str(invocation.id)
            assert requests[0].headers["X-Agent-Run-ID"] == str(invocation.run_id)
            assert requests[0].headers["X-Request-ID"] == "test-correlation"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("failure", "reason", "verified"),
    [
        ("missing", "missing_invocation", False),
        ("wrong-feature", "scope_mismatch", True),
        ("wrong-token", "invalid_invocation", False),
        ("expired", "invalid_invocation", False),
        ("changed-args", "invalid_invocation", False),
        ("wrong-tool", "invalid_invocation", False),
        ("invalid-args", "invalid_arguments", True),
        ("approval", "policy_denied", True),
    ],
)
def test_sdk_rejects_invalid_context_before_http(
    failure: str, reason: str, verified: bool, caplog: pytest.LogCaptureFixture
) -> None:
    requests: list[httpx.Request] = []
    server = create_server(catalog(), service_token=TOKEN, executor=executor(requests))
    invocation = call("delete" if failure == "approval" else "read")
    signed = metadata(invocation)
    args = invocation.arguments
    name = invocation.tool_name
    if failure == "missing":
        signed = {}
    elif failure == "wrong-feature":
        signed = metadata(invocation, feature_key="student-2")
    elif failure == "wrong-token":
        signed = metadata(invocation, token=TOKEN[::-1])
    elif failure == "expired":
        signed = metadata(invocation, now=1.0)
    elif failure == "changed-args":
        args = {"value": 9}
    elif failure == "wrong-tool":
        name = "test.write.v1"
    elif failure == "invalid-args":
        invocation = invocation.model_copy(update={"arguments": {"value": "secret-invalid"}})
        signed, args = metadata(invocation), invocation.arguments

    async def scenario() -> None:
        async with create_connected_server_and_client_session(server) as session:
            result = await session.call_tool(name, args, meta=signed)
            assert result.isError
            assert "secret-invalid" not in result.model_dump_json()

    with caplog.at_level(logging.INFO, logger="mcp_server"):
        asyncio.run(scenario())
    assert requests == []
    [line] = tool_lines(caplog)
    assert (line["level"], line["outcome"], line["error_code"]) == ("warning", "rejected", reason)
    assert line["tool_name"] == name
    # Correlation comes only from a verified signature, never from unverified metadata.
    assert line["request_id"] == ("test-correlation" if verified else None)
    signed_feature = "student-2" if failure == "wrong-feature" else FEATURE
    assert line["feature_key"] == (signed_feature if verified else None)
    rendered = json.dumps(line)
    for secret in ("secret-invalid", TOKEN, TOKEN[::-1], *signed.values()):
        assert secret not in rendered
    assert '"value"' not in rendered


def test_mutation_replay_is_rejected_and_approved_mutation_reaches_owner(
    caplog: pytest.LogCaptureFixture,
) -> None:
    requests: list[httpx.Request] = []
    server = create_server(catalog(), service_token=TOKEN, executor=executor(requests))

    async def scenario() -> None:
        async with create_connected_server_and_client_session(server) as session:
            invocation = call("delete", ApprovalStatus.APPROVED)
            signed = metadata(invocation)
            assert not (
                await session.call_tool(invocation.tool_name, invocation.arguments, meta=signed)
            ).isError
            assert (
                await session.call_tool(invocation.tool_name, invocation.arguments, meta=signed)
            ).isError

    with caplog.at_level(logging.INFO, logger="mcp_server"):
        asyncio.run(scenario())
    assert len(requests) == 1
    assert requests[0].headers["Idempotency-Key"] == "deterministic-write"
    accepted, replayed = tool_lines(caplog)
    assert (accepted["outcome"], replayed["outcome"]) == ("success", "rejected")
    assert replayed["error_code"] == "replay_rejected"
    assert replayed["tool_call_id"] == accepted["tool_call_id"]
    assert "deterministic-write" not in json.dumps([accepted, replayed])


def test_successful_call_logs_verified_correlation_without_arguments_or_results(
    caplog: pytest.LogCaptureFixture,
) -> None:
    requests: list[httpx.Request] = []
    server = create_server(catalog(), service_token=TOKEN, executor=executor(requests))
    invocation = call().model_copy(update={"arguments": {"value": 424242}})
    signed = metadata(invocation)

    async def scenario() -> None:
        async with create_connected_server_and_client_session(server) as session:
            result = await session.call_tool(
                invocation.tool_name, invocation.arguments, meta=signed
            )
            assert result.structuredContent == {"value": 424242}

    with caplog.at_level(logging.INFO, logger="mcp_server"):
        asyncio.run(scenario())
    [line] = tool_lines(caplog)
    assert line["event"] == "mcp.tool_call.completed"
    assert line["service"] == "mcp-server"
    assert line["level"] == "info"
    assert line["request_id"] == "test-correlation"
    assert line["run_id"] == str(invocation.run_id)
    assert line["step_id"] == str(invocation.step_id)
    assert line["tool_call_id"] == str(invocation.id)
    assert line["feature_key"] == FEATURE
    assert (line["tool_name"], line["tool_version"]) == ("test.read.v1", "v1")
    assert (line["outcome"], line["tool_outcome"], line["error_code"]) == (
        "success",
        "succeeded",
        None,
    )
    assert line["retryable"] is False
    assert isinstance(line["duration_ms"], int) and line["duration_ms"] >= 0
    rendered = json.dumps(line)
    for secret in ("424242", TOKEN, signed[INVOCATION_META_KEY]):
        assert secret not in rendered


def test_unknown_tool_rejection_does_not_echo_the_requested_name(
    caplog: pytest.LogCaptureFixture,
) -> None:
    server = create_server(catalog(), service_token=TOKEN, executor=executor([]))

    async def scenario() -> None:
        async with create_connected_server_and_client_session(server) as session:
            result = await session.call_tool("attacker-chosen-name", {"value": 1})
            assert result.isError

    with caplog.at_level(logging.INFO, logger="mcp_server"):
        asyncio.run(scenario())
    [line] = tool_lines(caplog)
    assert (line["outcome"], line["error_code"]) == ("rejected", "unknown_tool")
    assert "tool_name" not in line and line["request_id"] is None
    assert "attacker-chosen-name" not in json.dumps(line)


def test_feature_failure_and_executor_crash_are_logged_as_failures(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def unavailable(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "owner secret detail"})

    failing = HttpToolExecutor(
        service_base_urls={"feature-api": "http://127.0.0.1:5200"},
        bindings=[
            HttpToolBinding(
                tool_name="test.read.v1",
                tool_version="v1",
                service="feature-api",
                method="POST",
                path="/tools/read",
            )
        ],
        client=httpx.Client(transport=httpx.MockTransport(unavailable)),
    )

    class CrashingExecutor:
        def execute(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("executor crash mentioning secret-argument")

    async def scenario(server: object) -> None:
        async with create_connected_server_and_client_session(server) as session:  # type: ignore[arg-type]
            invocation = call()
            result = await session.call_tool(
                invocation.tool_name, invocation.arguments, meta=metadata(invocation)
            )
            assert result.isError

    with caplog.at_level(logging.INFO, logger="mcp_server"):
        asyncio.run(scenario(create_server(catalog(), service_token=TOKEN, executor=failing)))
        asyncio.run(
            scenario(
                create_server(
                    catalog(),
                    service_token=TOKEN,
                    executor=CrashingExecutor(),  # type: ignore[arg-type]
                )
            )
        )
    failed, crashed = tool_lines(caplog)
    assert (failed["level"], failed["outcome"], failed["tool_outcome"]) == (
        "warning",
        "failure",
        "failed",
    )
    assert failed["error_code"] is not None and failed["request_id"] == "test-correlation"
    assert (crashed["level"], crashed["outcome"], crashed["error_code"]) == (
        "error",
        "failure",
        "executor_error",
    )
    assert crashed["exception_type"] == "RuntimeError"
    rendered = json.dumps([failed, crashed])
    assert "owner secret detail" not in rendered and "secret-argument" not in rendered


def test_entrypoint_configures_json_stdout_logging(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import mcp_server.__main__ as entrypoint
    from mcp_server.observability import LOGGER_NAMES, log_level_from_environment

    served: dict[str, object] = {}
    monkeypatch.setenv("MCP_SERVICE_TOKEN", TOKEN)
    monkeypatch.setenv("MCP_TOOL_CATALOG_PATHS", " catalog-a.json , ")
    monkeypatch.setenv("MCP_LOG_LEVEL", "info")
    monkeypatch.setattr(entrypoint, "load_tool_catalogs", lambda paths: catalog())
    monkeypatch.setattr(
        entrypoint.uvicorn, "run", lambda app, **options: served.update(app=app, **options)
    )
    entrypoint.main()
    assert served["port"] == 5011 and served["host"] == "127.0.0.1"
    for name in LOGGER_NAMES:
        assert logging.getLogger(name).propagate is False
    logging.getLogger("shared_tool_runtime.http").info(
        "Feature tool call completed", extra={"request_id": "local-deploy-runtime"}
    )
    [line] = [json.loads(text) for text in capsys.readouterr().out.splitlines()]
    assert (line["service"], line["request_id"]) == ("mcp-server", "local-deploy-runtime")
    monkeypatch.setenv("MCP_LOG_LEVEL", "chatty")
    with pytest.raises(ValueError, match="MCP_LOG_LEVEL"):
        log_level_from_environment()
    monkeypatch.setenv("MCP_HOST", "0.0.0.0")  # noqa: S104 - asserting the loopback refusal
    with pytest.raises(ValueError, match="loopback"):
        entrypoint.main()


def test_asgi_authentication_and_sdk_streamable_protocol_without_network() -> None:
    requests: list[httpx.Request] = []
    app = create_app(catalog(), service_token=TOKEN, executor=executor(requests))

    async def scenario() -> None:
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:5011"
            ) as client,
        ):
            assert (await client.get("/health")).status_code == 401
            assert (
                await client.get("/health", headers={"Authorization": "Bearer wrong"})
            ).status_code == 401
            client.headers["Authorization"] = f"Bearer {TOKEN}"
            assert (await client.get("/health")).json() == {
                "status": "ready",
                "registered_tools": 3,
            }
            assert (await client.post("/mcp", content=b"x" * 300_001)).status_code == 413
            async with (
                streamable_http_client(
                    "http://127.0.0.1:5011/mcp", http_client=client, terminate_on_close=False
                ) as (reader, writer, _),
                ClientSession(reader, writer) as session,
            ):
                await session.initialize()
                assert len((await session.list_tools()).tools) == 3
                invocation = call()
                result = await session.call_tool(
                    invocation.tool_name, invocation.arguments, meta=metadata(invocation)
                )
                assert result.structuredContent == {"value": 7}

    asyncio.run(scenario())


def test_orchestrator_client_round_trip_over_inprocess_sdk(monkeypatch) -> None:
    from ai_mode.adapters import mcp_tools

    requests: list[httpx.Request] = []
    app = create_app(catalog(), service_token=TOKEN, executor=executor(requests))

    @asynccontextmanager
    async def transport(url, *, http_client, terminate_on_close):
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), headers=http_client.headers
            ) as client,
            streamable_http_client(
                url, http_client=client, terminate_on_close=terminate_on_close
            ) as streams,
        ):
            yield streams

    monkeypatch.setattr(mcp_tools, "streamable_http_client", transport)
    client = mcp_tools.McpToolExecutor(base_url="http://127.0.0.1:5011", service_token=TOKEN)
    invocation = call()
    result = client.execute(invocation, catalog().tools[0].definition, timeout_ms=10000)
    assert result.call_id == invocation.id
    assert result.content == {"value": 7}
    assert result.outcome == "succeeded"
    assert "transport:mcp" in result.evidence_references
    assert len(requests) == 1
    client.close()


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1",
        "http://outside.example",
        "http://user:secret@localhost",
        "http://localhost/arbitrary",
    ],
)
def test_client_rejects_unapproved_endpoint(url: str) -> None:
    from ai_mode.adapters.mcp_tools import McpToolExecutor

    with pytest.raises(ValueError, match="loopback"):
        McpToolExecutor(base_url=url, service_token=TOKEN)


def test_client_rejects_container_service_origins() -> None:
    from ai_mode.adapters.mcp_tools import McpToolExecutor

    for rejected in (
        "http://mcp-server:5011/mcp",
        "http://host.docker.internal:5011/mcp",
        "http://mcp-server.attacker.test:5011/mcp",
    ):
        with pytest.raises(ValueError, match="allowlisted loopback"):
            McpToolExecutor(base_url=rejected, service_token=TOKEN)
    McpToolExecutor(base_url="http://127.0.0.1:5011/mcp", service_token=TOKEN).close()


@pytest.mark.parametrize("compose", [False, True])
def test_transport_compose_host_is_explicit_and_keeps_origin_protection(compose: bool) -> None:
    options = {"allowed_hosts": ("mcp-server:5011",)} if compose else {}
    app = create_app(catalog(), service_token=TOKEN, executor=executor([]), **options)

    async def scenario() -> None:
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://mcp-server:5011",
                headers={
                    "Authorization": f"Bearer {TOKEN}",
                    "Accept": "application/json, text/event-stream",
                },
            ) as client,
        ):
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            }
            assert (await client.post("/mcp", json=payload)).status_code == (
                200 if compose else 421
            )
            assert (
                await client.post("/mcp", json=payload, headers={"Host": "attacker.example"})
            ).status_code == 421
            if compose:
                assert (
                    await client.post(
                        "/mcp", json=payload, headers={"Origin": "https://attacker.example"}
                    )
                ).status_code == 403

    asyncio.run(scenario())


def test_client_policy_and_deadline_fail_before_transport() -> None:
    from ai_mode.adapters.mcp_tools import McpToolExecutor

    client = McpToolExecutor(base_url="http://127.0.0.1:5011", service_token=TOKEN)
    rejected = client.execute(call("delete"), catalog().tools[2].definition, timeout_ms=1000)
    assert "transport:mcp" not in rejected.evidence_references
    assert (
        client.execute(call("delete"), catalog().tools[2].definition, timeout_ms=1000).error.code
        == "mcp_request_rejected"
    )
    assert (
        client.execute(call(), catalog().tools[0].definition, timeout_ms=0).outcome == "timed_out"
    )
    assert (
        client.execute(call("write"), catalog().tools[0].definition, timeout_ms=1000).error.code
        == "mcp_request_rejected"
    )


def test_client_rejects_oversized_response_stream() -> None:
    from ai_mode.adapters.mcp_tools import _BoundedStream

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"123"
            yield b"456"

    async def scenario() -> None:
        stream = _BoundedStream(Stream(), 5)
        with pytest.raises(ValueError, match="size limit"):
            async for _ in stream:
                pass
        await stream.aclose()

    asyncio.run(scenario())
