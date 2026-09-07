"""Official SDK server projecting approved feature tools onto Streamable HTTP."""

from __future__ import annotations

import hmac
import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial
from typing import Any

import anyio
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyUrl
from shared_tool_runtime import HttpToolExecutor, ToolCatalog, build_http_executor
from shared_tool_runtime.invocation import (
    INVOCATION_META_KEY,
    authorize_invocation,
    validate_service_token,
    verify_invocation,
)
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from shared_contracts import SideEffectClass, ToolOutcome

RESULT_META_KEY = "propertyscope/tool-result"
CATALOG_URI = "propertyscope://tools/catalog"


def create_server(
    catalog: ToolCatalog, *, service_token: str, executor: HttpToolExecutor
) -> Server[Any, Any]:
    """Create the SDK application; callers own transport and executor lifetimes."""
    validate_service_token(service_token)
    server: Server[Any, Any] = Server("propertyscope-tools", version="1.0.0")
    definitions = {entry.definition.name: entry.definition for entry in catalog.tools}
    for definition in definitions.values():
        if not definition.name.endswith(f".{definition.version}"):
            raise ValueError("tool names must end with their immutable version")
        Draft202012Validator.check_schema(definition.input_schema)
        Draft202012Validator.check_schema(definition.output_schema)
    if (
        len(set(catalog.shared_tools)) != len(catalog.shared_tools)
        or any(
            name not in definitions or definitions[name].feature_key != "shared"
            for name in catalog.shared_tools
        )
        or any(
            definition.feature_key == "shared" and definition.name not in catalog.shared_tools
            for definition in definitions.values()
        )
    ):
        raise ValueError("shared tools require explicit unique approval")
    consumed: dict[str, float] = {}

    @server.list_tools()  # type: ignore[no-untyped-call,untyped-decorator]
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name=definition.name,
                description=definition.description,
                inputSchema=definition.input_schema,
                outputSchema=definition.output_schema,
                annotations=types.ToolAnnotations(
                    readOnlyHint=definition.side_effect is SideEffectClass.READ_ONLY,
                    destructiveHint=definition.side_effect is SideEffectClass.DESTRUCTIVE_WRITE,
                    idempotentHint=definition.side_effect is SideEffectClass.READ_ONLY,
                    openWorldHint=False,
                ),
            )
            for definition in definitions.values()
        ]

    @server.list_resources()  # type: ignore[no-untyped-call,untyped-decorator]
    async def list_resources() -> list[types.Resource]:
        return [
            types.Resource(
                uri=AnyUrl(CATALOG_URI),
                name="Approved feature tool catalogue",
                description="Public tool definitions without service origins, secrets or records",
                mimeType="application/json",
            )
        ]

    @server.read_resource()  # type: ignore[no-untyped-call,untyped-decorator]
    async def read_resource(uri: AnyUrl) -> list[ReadResourceContents]:
        if str(uri) != CATALOG_URI:
            raise ValueError("resource is not registered")
        return [
            ReadResourceContents(
                content=json.dumps(
                    {
                        "schema_version": 1,
                        "tools": [
                            definition.model_dump(mode="json")
                            for definition in definitions.values()
                        ],
                    }
                ),
                mime_type="application/json",
            )
        ]

    # Validate here so protocol failures cannot expose argument values via SDK error strings.
    @server.call_tool(validate_input=False)  # type: ignore[untyped-decorator]
    async def call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        try:
            definition = definitions[name]
            metadata = server.request_context.meta
            signed = (metadata.model_extra or {}).get(INVOCATION_META_KEY) if metadata else None
            if not isinstance(signed, str):
                raise ValueError("signed invocation context is required")
            context = verify_invocation(
                signed, service_token=service_token, tool_name=name, arguments=arguments
            )
            if (
                context.feature_key != definition.feature_key and name not in catalog.shared_tools
            ) or context.call.tool_version != definition.version:
                raise ValueError("tool scope mismatch")
            Draft202012Validator(definition.input_schema, format_checker=FormatChecker()).validate(
                arguments
            )
            call = context.call.model_copy(update={"arguments": arguments})
            authorize_invocation(call, definition)
            now = time.time()
            # Consumption happens before yielding, so concurrent repeats cannot dispatch twice.
            if definition.side_effect is not SideEffectClass.READ_ONLY:
                for identity, expiry in tuple(consumed.items()):
                    if expiry <= now:
                        del consumed[identity]
                identity = str(call.id)
                if identity in consumed or len(consumed) >= 10_000:
                    raise ValueError("mutation invocation replay rejected")
                consumed[identity] = context.deadline
            timeout_ms = min(definition.timeout_ms, int((context.deadline - now) * 1000))
            if timeout_ms <= 0:
                raise ValueError("invocation deadline exceeded")
        except (KeyError, ValueError, ValidationError):
            return types.CallToolResult(
                content=[types.TextContent(type="text", text="Tool invocation rejected")],
                isError=True,
            )
        result = await anyio.to_thread.run_sync(
            partial(executor.execute, call, definition, timeout_ms=timeout_ms)
        )
        return types.CallToolResult(
            content=[types.TextContent(type="text", text="Tool invocation completed")],
            structuredContent=result.content,
            isError=result.outcome is not ToolOutcome.SUCCEEDED,
            _meta={RESULT_META_KEY: result.model_dump(mode="json", exclude={"content"})},
        )

    return server


class ServiceAuthentication:
    """Authenticate every protocol request before its body reaches the SDK."""

    def __init__(self, app: Any, service_token: str) -> None:
        self.app = app
        self._authorization = f"Bearer {service_token}".encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = [value for key, value in scope["headers"] if key == b"authorization"]
            if len(headers) != 1 or not hmac.compare_digest(headers[0], self._authorization):
                await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)


class ProtocolEndpoint:
    """Keep Starlette's endpoint dispatch in ASGI mode instead of Request mode."""

    def __init__(self, manager: StreamableHTTPSessionManager) -> None:
        self.manager = manager

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.manager.handle_request(scope, receive, send)


def create_app(
    catalog: ToolCatalog,
    *,
    service_token: str,
    executor: HttpToolExecutor | None = None,
    allowed_hosts: tuple[str, ...] = ("127.0.0.1:*", "localhost:*", "[::1]:*"),
) -> Starlette:
    """Compose a local ASGI service with explicitly bounded protocol origins."""
    owned_executor = executor is None
    selected_executor = executor or build_http_executor(catalog)
    server = create_server(catalog, service_token=service_token, executor=selected_executor)
    manager = StreamableHTTPSessionManager(
        server,
        stateless=True,
        json_response=True,
        max_request_body_size=300_000,
        security_settings=TransportSecuritySettings(
            allowed_hosts=list(allowed_hosts),
            allowed_origins=["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"],
        ),
    )

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        try:
            async with manager.run():
                yield
        finally:
            if owned_executor:
                selected_executor.close()

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ready", "registered_tools": len(catalog.tools)})

    app = Starlette(routes=[Route("/health", health)], lifespan=lifespan)
    app.router.routes.append(
        Route("/mcp", ProtocolEndpoint(manager), methods=["GET", "POST", "DELETE"])
    )
    app.add_middleware(ServiceAuthentication, service_token=service_token)
    return app
