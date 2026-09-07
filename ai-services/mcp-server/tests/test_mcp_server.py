"""Deterministic protocol, authentication and owning-tool boundary checks."""

import asyncio
import json
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.memory import create_connected_server_and_client_session
from mcp_server import create_app, create_server
from shared_tool_runtime import HttpToolBinding, HttpToolExecutor, ToolCatalog
from shared_tool_runtime.invocation import INVOCATION_META_KEY, sign_invocation

from shared_contracts import ApprovalStatus, ToolCall

TOKEN = "deterministic-test-service-token-123456"
FEATURE = "student-1-propertyscope-data-platform"


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
    "failure",
    [
        "missing",
        "wrong-feature",
        "wrong-token",
        "expired",
        "changed-args",
        "wrong-tool",
        "invalid-args",
        "approval",
    ],
)
def test_sdk_rejects_invalid_context_before_http(failure: str) -> None:
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

    asyncio.run(scenario())
    assert requests == []


def test_mutation_replay_is_rejected_and_approved_mutation_reaches_owner() -> None:
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

    asyncio.run(scenario())
    assert len(requests) == 1
    assert requests[0].headers["Idempotency-Key"] == "deterministic-write"


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


def test_client_policy_and_deadline_fail_before_transport() -> None:
    from ai_mode.adapters.mcp_tools import McpToolExecutor

    client = McpToolExecutor(base_url="http://127.0.0.1:5011", service_token=TOKEN)
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
