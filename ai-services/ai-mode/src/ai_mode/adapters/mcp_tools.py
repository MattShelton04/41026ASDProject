"""Bounded official MCP client for already-authorized orchestrator tool calls."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from time import monotonic
from typing import Any
from urllib.parse import urlsplit

import httpx
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from shared_tool_runtime.http import HttpToolExecutor
from shared_tool_runtime.invocation import (
    INVOCATION_META_KEY,
    authorize_invocation,
    sign_invocation,
    validate_service_token,
)

from shared_contracts import ToolCall, ToolDefinition, ToolOutcome, ToolResult

RESULT_META_KEY = "propertyscope/tool-result"


class _BoundedStream(httpx.AsyncByteStream):
    def __init__(self, stream: httpx.AsyncByteStream, limit: int) -> None:
        self._stream = stream
        self._limit = limit

    async def __aiter__(self) -> AsyncIterator[bytes]:
        size = 0
        async for chunk in self._stream:
            size += len(chunk)
            if size > self._limit:
                raise ValueError("MCP response exceeds configured size limit")
            yield chunk

    async def aclose(self) -> None:
        await self._stream.aclose()


class _BoundedTransport(httpx.AsyncHTTPTransport):
    def __init__(self, limit: int) -> None:
        super().__init__(retries=0)
        self._limit = limit

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await super().handle_async_request(request)
        assert isinstance(response.stream, httpx.AsyncByteStream)
        response.stream = _BoundedStream(response.stream, self._limit)
        return response


class McpToolExecutor:
    """Make one signed MCP call; never retry or fall back to direct HTTP."""

    def __init__(
        self,
        *,
        base_url: str,
        service_token: str,
        max_response_bytes: int = 1_048_576,
        max_request_bytes: int = 262_144,
        feature_key: str | None = None,
    ) -> None:
        validate_service_token(service_token)
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/", "/mcp"}
        ):
            raise ValueError("MCP must use an allowlisted loopback HTTP endpoint")
        if max_response_bytes < 1 or max_request_bytes < 1:
            raise ValueError("MCP message limits must be positive")
        self._url = base_url.rstrip("/")
        if not self._url.endswith("/mcp"):
            self._url += "/mcp"
        self._token = service_token
        self._max_response_bytes = max_response_bytes
        self._max_request_bytes = max_request_bytes
        self._feature_key = feature_key

    def close(self) -> None:
        """Connections are scoped to each invocation, so no pool survives a call."""

    def execute(self, call: ToolCall, definition: ToolDefinition, *, timeout_ms: int) -> ToolResult:
        """Preserve the complete ToolResult envelope and original invocation correlation."""
        started = monotonic()
        try:
            if call.tool_name != definition.name or call.tool_version != definition.version:
                raise ValueError("tool definition mismatch")
            if len(call.model_dump_json().encode()) > self._max_request_bytes:
                raise ValueError("tool request exceeds configured size limit")
            authorize_invocation(call, definition)
            Draft202012Validator(definition.input_schema, format_checker=FormatChecker()).validate(
                call.arguments
            )
            if timeout_ms <= 0:
                raise TimeoutError
            timeout_ms = min(timeout_ms, definition.timeout_ms)
            return asyncio.run(self._execute(call, definition, timeout_ms=timeout_ms))
        except TimeoutError:
            return HttpToolExecutor._failure(
                call,
                started,
                "mcp_timeout",
                "MCP tool request timed out",
                outcome=ToolOutcome.TIMED_OUT,
            )
        except (ValueError, ValidationError):
            return HttpToolExecutor._failure(
                call, started, "mcp_request_rejected", "MCP tool request or response was rejected"
            )
        except Exception:
            # SDK task groups wrap network and protocol failures in ExceptionGroup.
            # Never leak response bodies, credentials or internal exception text to models.
            return HttpToolExecutor._failure(
                call, started, "mcp_unavailable", "MCP tool service is unavailable"
            )

    async def _execute(
        self, call: ToolCall, definition: ToolDefinition, *, timeout_ms: int
    ) -> ToolResult:
        signed = sign_invocation(
            call,
            feature_key=self._feature_key or definition.feature_key,
            service_token=self._token,
            timeout_ms=timeout_ms,
        )

        async with asyncio.timeout(timeout_ms / 1000):
            async with httpx.AsyncClient(
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=httpx.Timeout(timeout_ms / 1000),
                follow_redirects=False,
                trust_env=False,
                transport=_BoundedTransport(self._max_response_bytes),
            ) as http_client:
                async with streamable_http_client(
                    self._url,
                    http_client=http_client,
                    terminate_on_close=False,
                ) as (reader, writer, _):
                    async with ClientSession(reader, writer) as session:
                        await session.initialize()
                        response = await session.call_tool(
                            call.tool_name,
                            call.arguments,
                            read_timeout_seconds=timedelta(milliseconds=timeout_ms),
                            meta={INVOCATION_META_KEY: signed},
                        )
        meta: dict[str, Any] = response.meta or {}
        envelope = meta.get(RESULT_META_KEY)
        if not isinstance(envelope, dict) or "content" in envelope:
            raise ValueError("MCP response has no valid invocation envelope")
        result = ToolResult.model_validate(
            {**envelope, "content": response.structuredContent or {}}
        )
        if result.call_id != call.id or response.isError == (
            result.outcome is ToolOutcome.SUCCEEDED
        ):
            raise ValueError("MCP response invocation correlation conflicts")
        if result.outcome is ToolOutcome.SUCCEEDED:
            Draft202012Validator(definition.output_schema, format_checker=FormatChecker()).validate(
                result.content
            )
        return result
