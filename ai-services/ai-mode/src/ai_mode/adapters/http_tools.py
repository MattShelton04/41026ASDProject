"""Safe HTTP transport adapter for allowlisted feature-owned tools."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from time import monotonic
from typing import Literal
from urllib.parse import urlsplit

import httpx
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

from agent_core import ToolExecutor
from ai_mode.configuration import (
    DEFAULT_MAX_TOOL_REQUEST_BYTES,
    DEFAULT_MAX_TOOL_RESPONSE_BYTES,
)
from shared_contracts import (
    AGENT_RUN_ID_HEADER,
    IDEMPOTENCY_KEY_HEADER,
    REQUEST_ID_HEADER,
    TRACEPARENT_HEADER,
    ToolCall,
    ToolDefinition,
    ToolError,
    ToolOutcome,
    ToolResult,
)

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class HttpToolBinding:
    """Non-model-controlled transport details for one immutable tool version."""

    tool_name: str
    tool_version: str
    service: str
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str


class HttpToolExecutor(ToolExecutor):
    """Invoke only fixed service identities and return bounded, typed results."""

    def __init__(
        self,
        *,
        service_base_urls: Mapping[str, str],
        bindings: Iterable[HttpToolBinding],
        max_request_bytes: int = DEFAULT_MAX_TOOL_REQUEST_BYTES,
        max_response_bytes: int = DEFAULT_MAX_TOOL_RESPONSE_BYTES,
        client: httpx.Client | None = None,
    ) -> None:
        if max_request_bytes < 1 or max_response_bytes < 1:
            raise ValueError("HTTP tool size limits must be positive")
        self._origins = {
            service: _validated_origin(service, base_url)
            for service, base_url in service_base_urls.items()
        }
        resolved: dict[tuple[str, str], HttpToolBinding] = {}
        for binding in bindings:
            key = (binding.tool_name, binding.tool_version)
            if key in resolved:
                raise ValueError(
                    f"duplicate HTTP binding: {binding.tool_name}@{binding.tool_version}"
                )
            if binding.service not in self._origins:
                raise ValueError(f"HTTP binding uses unknown service: {binding.service}")
            _validate_binding_path(binding.path)
            resolved[key] = binding
        self._bindings = resolved
        self._max_request_bytes = max_request_bytes
        self._max_response_bytes = max_response_bytes
        self._client = client or httpx.Client(follow_redirects=False)
        self._owns_client = client is None

    def close(self) -> None:
        """Release the owned connection pool during application shutdown."""
        if self._owns_client:
            self._client.close()

    def execute(
        self,
        call: ToolCall,
        definition: ToolDefinition,
        *,
        timeout_ms: int,
    ) -> ToolResult:
        """Dispatch a validated call without accepting any model-provided URL."""
        started = monotonic()
        binding = self._bindings.get((call.tool_name, call.tool_version))
        if (
            binding is None
            or definition.name != call.tool_name
            or definition.version != call.tool_version
        ):
            return self._failure(
                call, started, "tool_binding_mismatch", "Tool binding is unavailable"
            )

        payload = json.dumps(
            call.arguments,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        if len(payload) > self._max_request_bytes:
            return self._failure(
                call,
                started,
                "tool_request_too_large",
                "Tool request exceeds the configured size limit",
            )

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            REQUEST_ID_HEADER: call.request_id,
            AGENT_RUN_ID_HEADER: str(call.run_id),
        }
        if call.traceparent is not None:
            headers[TRACEPARENT_HEADER] = call.traceparent
        if call.idempotency_key is not None:
            headers[IDEMPOTENCY_KEY_HEADER] = call.idempotency_key

        url = f"{self._origins[binding.service]}{binding.path}"
        evidence = (f"service:{binding.service}",)
        try:
            with self._client.stream(
                binding.method,
                url,
                content=payload,
                headers=headers,
                timeout=timeout_ms / 1_000,
            ) as response:
                status_evidence = (*evidence, f"status:{response.status_code}")
                if response.is_redirect:
                    return self._failure(
                        call,
                        started,
                        "tool_redirect_rejected",
                        "Tool service redirects are not allowed",
                        evidence=status_evidence,
                    )
                if response.status_code >= 400:
                    return self._status_failure(
                        call, started, response.status_code, status_evidence
                    )
                media_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                if media_type != "application/json":
                    return self._failure(
                        call,
                        started,
                        "tool_media_type_invalid",
                        "Tool response must use application/json",
                        evidence=status_evidence,
                    )
                raw = self._read_bounded(response)
        except httpx.TimeoutException:
            return self._failure(
                call,
                started,
                "tool_timeout",
                "Tool request timed out",
                outcome=ToolOutcome.TIMED_OUT,
                retryable=True,
                evidence=evidence,
            )
        except httpx.TransportError:
            return self._failure(
                call,
                started,
                "tool_unavailable",
                "Tool service is unavailable",
                retryable=True,
                evidence=evidence,
            )
        except _ResponseTooLargeError:
            return self._failure(
                call,
                started,
                "tool_response_too_large",
                "Tool response exceeds the configured size limit",
                evidence=evidence,
            )

        try:
            content = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._failure(
                call,
                started,
                "tool_response_invalid_json",
                "Tool response is not valid JSON",
                evidence=status_evidence,
            )
        if not isinstance(content, dict):
            return self._failure(
                call,
                started,
                "tool_response_invalid",
                "Tool response must be a JSON object",
                evidence=status_evidence,
            )
        try:
            Draft202012Validator(
                definition.output_schema,
                format_checker=FormatChecker(),
            ).validate(content)
        except ValidationError:
            return self._failure(
                call,
                started,
                "invalid_tool_output",
                "Tool response failed its registered schema",
                evidence=status_evidence,
            )
        result = ToolResult(
            call_id=call.id,
            outcome=ToolOutcome.SUCCEEDED,
            content=content,
            duration_ms=_elapsed_ms(started),
            evidence_references=status_evidence,
        )
        _log_tool_result(call, result)
        return result

    def _read_bounded(self, response: httpx.Response) -> bytes:
        content_length = response.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > self._max_response_bytes:
                    raise _ResponseTooLargeError
            except ValueError:
                raise _ResponseTooLargeError from None
        chunks: list[bytes] = []
        size = 0
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > self._max_response_bytes:
                raise _ResponseTooLargeError
            chunks.append(chunk)
        return b"".join(chunks)

    @staticmethod
    def _status_failure(
        call: ToolCall,
        started: float,
        status: int,
        evidence: tuple[str, ...],
    ) -> ToolResult:
        if status == 409:
            return HttpToolExecutor._failure(
                call, started, "tool_conflict", "Tool request conflicted", evidence=evidence
            )
        retryable = status in {408, 425, 429} or status >= 500
        code = "tool_unavailable" if status >= 500 else "tool_request_rejected"
        message = "Tool service is unavailable" if status >= 500 else "Tool request was rejected"
        return HttpToolExecutor._failure(
            call,
            started,
            code,
            message,
            retryable=retryable,
            evidence=evidence,
        )

    @staticmethod
    def _failure(
        call: ToolCall,
        started: float,
        code: str,
        message: str,
        *,
        outcome: ToolOutcome = ToolOutcome.FAILED,
        retryable: bool = False,
        evidence: tuple[str, ...] = (),
    ) -> ToolResult:
        result = ToolResult(
            call_id=call.id,
            outcome=outcome,
            error=ToolError(code=code, message=message),
            duration_ms=_elapsed_ms(started),
            retryable=retryable,
            evidence_references=evidence,
        )
        _log_tool_result(call, result)
        return result


class _ResponseTooLargeError(Exception):
    pass


def _log_tool_result(call: ToolCall, result: ToolResult) -> None:
    LOGGER.log(
        logging.INFO if result.outcome is ToolOutcome.SUCCEEDED else logging.WARNING,
        "Feature tool call completed",
        extra={
            "event": "agent.tool.completed",
            "request_id": call.request_id,
            "run_id": call.run_id,
            "step_id": call.step_id,
            "tool_call_id": call.id,
            "tool_name": call.tool_name,
            "tool_version": call.tool_version,
            "outcome": result.outcome,
            "duration_ms": result.duration_ms,
            "error_code": result.error.code if result.error is not None else None,
            "retryable": result.retryable,
        },
    )


def _validated_origin(service: str, base_url: str) -> str:
    parsed = urlsplit(base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"service {service} must use a fixed HTTP(S) origin without credentials")
    return base_url.rstrip("/")


def _validate_binding_path(path: str) -> None:
    parsed = urlsplit(path)
    if (
        not path.startswith("/")
        or path.startswith("//")
        or parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or ".." in parsed.path.split("/")
    ):
        raise ValueError(f"tool binding path is unsafe: {path}")


def _elapsed_ms(started: float) -> int:
    return max(0, round((monotonic() - started) * 1_000))
