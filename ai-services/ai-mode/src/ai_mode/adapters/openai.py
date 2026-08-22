"""Production OpenAI Responses API adapter for structured model generation."""

from __future__ import annotations

import hashlib
import json
import logging
import random
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from threading import Lock
from time import monotonic, sleep
from typing import Any, NoReturn, cast
from uuid import uuid4

import httpx
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    DefaultHttpxClient,
    OpenAI,
    OpenAIError,
)

from agent_core import (
    LLMProvider,
    ModelMetrics,
    ModelProviderError,
    ModelRole,
    ProviderHealth,
    StructuredModelRequest,
    StructuredModelResult,
)
from shared_contracts import ModelReasoningEffort

LOGGER = logging.getLogger(__name__)
RETRYABLE_HTTP_STATUSES = frozenset({408, 409, 429, 500, 502, 503, 504})
CONTEXT_SAFETY_TOKENS = 1_024
MAX_RETRY_AFTER_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class OpenAIModelProfile:
    """Role-routed OpenAI model settings selected through a stable logical profile."""

    models: Mapping[ModelRole, str]
    maximum_output_tokens: int = 4_096
    context_tokens: int = 131_072
    reasoning_effort: ModelReasoningEffort = ModelReasoningEffort.LOW


class OpenAIProvider(LLMProvider):
    """Use the official SDK without leaking it through the provider-neutral port."""

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str,
        profiles: Mapping[str, OpenAIModelProfile],
        readiness_profiles: frozenset[str] | None = None,
        timeout_seconds: float,
        health_timeout_seconds: float = 2.0,
        health_cache_seconds: float = 60.0,
        max_retries: int = 2,
        max_response_bytes: int,
        prompt_cache_enabled: bool = True,
        client: OpenAI | httpx.Client | None = None,
        sleeper: Callable[[float], None] = sleep,
        clock: Callable[[], float] = monotonic,
        randomizer: Callable[[], float] = random.random,
    ) -> None:
        self._api_key = api_key
        self._profiles = dict(profiles)
        self._readiness_profiles = readiness_profiles or frozenset(self._profiles)
        if self._readiness_profiles - self._profiles.keys():
            raise ValueError("readiness profile is not registered")
        self._generation_timeout_seconds = timeout_seconds
        self._health_timeout_seconds = health_timeout_seconds
        self._health_cache_seconds = health_cache_seconds
        self._max_retries = max_retries
        self._max_response_bytes = max_response_bytes
        self._prompt_cache_enabled = prompt_cache_enabled
        self._sleeper = sleeper
        self._clock = clock
        self._randomizer = randomizer
        self._health_lock = Lock()
        self._health_cached_at: float | None = None
        self._health_cached_value: ProviderHealth | None = None
        self._owns_client = client is None
        if isinstance(client, httpx.Client):
            self._client = OpenAI(
                api_key=api_key or "not-configured",
                base_url=f"{str(client.base_url).rstrip('/')}/",
                timeout=httpx.Timeout(timeout_seconds),
                max_retries=0,
                http_client=client,
            )
        elif client is not None:
            self._client = client
        else:
            self._client = OpenAI(
                # Construction must remain possible for local/offline diagnostics. Calls are
                # rejected before dispatch when the real credential is absent.
                api_key=api_key or "not-configured",
                base_url=f"{base_url.rstrip('/')}/",
                timeout=httpx.Timeout(timeout_seconds),
                max_retries=0,
                default_headers={"User-Agent": "asd-ai-mode/0.1"},
                http_client=DefaultHttpxClient(
                    follow_redirects=False,
                    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
                ),
            )

    def generate_structured(self, request: StructuredModelRequest) -> StructuredModelResult:
        """Generate one JSON-Schema-guided response with safe metrics and failures."""
        profile, model = self._profile_for(request)
        if self._api_key is None:
            raise ModelProviderError(
                "OpenAI API credentials are not configured",
                code="model_credentials_missing",
                retryable=False,
            )
        payload = self._payload(request, profile, model=model)
        self._enforce_context_limit(request, profile, payload)
        started = self._clock()
        body, provider_request_id, retry_count = self._post_with_retries(
            payload,
            deadline_at=request.deadline_at,
            client_request_id=str(uuid4()),
        )
        total_duration_ms = max(0, int((self._clock() - started) * 1_000))
        content = self._structured_content(body, provider_request_id=provider_request_id)
        usage = body.get("usage")
        usage_object = usage if isinstance(usage, dict) else {}
        input_details = usage_object.get("input_tokens_details")
        output_details = usage_object.get("output_tokens_details")
        result = StructuredModelResult(
            content=content,
            provider="openai",
            model=_required_string(body, "model", fallback=model),
            provider_request_id=provider_request_id,
            metrics=ModelMetrics(
                total_duration_ms=total_duration_ms,
                prompt_tokens=_optional_nonnegative_int(usage_object.get("input_tokens")),
                output_tokens=_optional_nonnegative_int(usage_object.get("output_tokens")),
                cached_prompt_tokens=_nested_nonnegative_int(input_details, "cached_tokens"),
                cache_write_prompt_tokens=_nested_nonnegative_int(
                    input_details, "cache_write_tokens"
                ),
                reasoning_tokens=_nested_nonnegative_int(output_details, "reasoning_tokens"),
                retry_count=retry_count,
            ),
        )
        LOGGER.info(
            "Model invocation completed",
            extra={
                "event": "agent.model.completed",
                "run_id": request.run_id,
                "model": result.model,
                "model_profile": request.model_profile,
                "model_role": request.role,
                "outcome": "success",
                "duration_ms": result.metrics.total_duration_ms,
                "prompt_tokens": result.metrics.prompt_tokens,
                "output_tokens": result.metrics.output_tokens,
                "cached_prompt_tokens": result.metrics.cached_prompt_tokens,
                "cache_write_prompt_tokens": result.metrics.cache_write_prompt_tokens,
                "reasoning_tokens": result.metrics.reasoning_tokens,
                "retry_count": result.metrics.retry_count,
                "provider_request_id": result.provider_request_id,
                "repair_count": request.repair_attempt,
            },
        )
        return result

    def health(self) -> ProviderHealth:
        """Return a short-lived, thread-safe credential and selected-model readiness check."""
        if self._api_key is None:
            return ProviderHealth(
                reachable=False,
                detail="OpenAI API credentials are not configured",
            )
        with self._health_lock:
            now = self._clock()
            if (
                self._health_cached_value is not None
                and self._health_cached_at is not None
                and now - self._health_cached_at < self._health_cache_seconds
            ):
                return self._health_cached_value
            health = self._check_health()
            self._health_cached_at = now
            self._health_cached_value = health
            return health

    def close(self) -> None:
        """Close only a client created by this adapter."""
        if self._owns_client:
            self._client.close()

    def _check_health(self) -> ProviderHealth:
        models = {
            model
            for profile_name in self._readiness_profiles
            for model in self._profiles[profile_name].models.values()
        }
        try:
            for model in sorted(models):
                raw_create = cast(Any, self._client.models.with_streaming_response.retrieve)
                with raw_create(model, timeout=self._health_timeout_seconds) as response:
                    content = self._bounded_content(response)
                    body = self._decode_object(content, provider_request_id=response.request_id)
                    if body.get("id") != model:
                        return ProviderHealth(
                            reachable=False,
                            detail="OpenAI model readiness returned an invalid response",
                        )
            return ProviderHealth(reachable=True, detail="OpenAI and configured models are ready")
        except APIStatusError as exc:
            if exc.status_code in {401, 403, 404}:
                detail = "OpenAI authentication or model access failed"
            else:
                detail = f"OpenAI model readiness returned HTTP {exc.status_code}"
            return ProviderHealth(reachable=False, detail=detail)
        except (OpenAIError, ModelProviderError, ValueError, json.JSONDecodeError) as exc:
            return ProviderHealth(
                reachable=False,
                detail=f"OpenAI unavailable: {type(exc).__name__}",
            )

    def _profile_for(self, request: StructuredModelRequest) -> tuple[OpenAIModelProfile, str]:
        profile = self._profiles.get(request.model_profile)
        if profile is None:
            raise ModelProviderError(
                f"unknown model profile: {request.model_profile}",
                code="model_profile_not_found",
                retryable=False,
            )
        model = profile.models.get(request.role)
        if model is None:
            raise ModelProviderError(
                f"profile {request.model_profile} does not support {request.role.value}",
                code="model_role_not_supported",
                retryable=False,
            )
        if request.max_output_tokens > profile.maximum_output_tokens:
            raise ModelProviderError(
                f"requested output limit exceeds profile maximum {profile.maximum_output_tokens}",
                code="model_output_limit_exceeded",
                retryable=False,
            )
        return profile, model

    def _payload(
        self,
        request: StructuredModelRequest,
        profile: OpenAIModelProfile,
        *,
        model: str,
    ) -> dict[str, Any]:
        system_text = "\n\n".join(
            message.content for message in request.messages if message.role == "system"
        )
        input_messages: list[dict[str, Any]] = []
        payload: dict[str, Any] = {
            "model": model,
            "max_output_tokens": request.max_output_tokens,
            "reasoning": {"effort": profile.reasoning_effort.value},
            "store": False,
            "truncation": "disabled",
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": _schema_name(request),
                    "schema": request.output_schema,
                    "strict": False,
                }
            },
        }
        if system_text and self._prompt_cache_enabled:
            input_messages.append(
                {
                    "role": "developer",
                    "content": [
                        {
                            "type": "input_text",
                            "text": system_text,
                            "prompt_cache_breakpoint": {"mode": "explicit"},
                        }
                    ],
                }
            )
            payload["prompt_cache_key"] = _prompt_cache_key(request, model=model)
            payload["prompt_cache_options"] = {"mode": "explicit", "ttl": "30m"}
        elif system_text:
            payload["instructions"] = system_text
        input_messages.extend(
            {"role": message.role, "content": message.content}
            for message in request.messages
            if message.role != "system"
        )
        if not input_messages:
            input_messages.append(
                {"role": "user", "content": "Produce the requested structured response."}
            )
        payload["input"] = input_messages
        if profile.reasoning_effort is ModelReasoningEffort.NONE:
            payload["temperature"] = request.temperature
        return payload

    @staticmethod
    def _enforce_context_limit(
        request: StructuredModelRequest,
        profile: OpenAIModelProfile,
        payload: Mapping[str, Any],
    ) -> None:
        available_input_tokens = (
            profile.context_tokens - request.max_output_tokens - CONTEXT_SAFETY_TOKENS
        )
        serialized_bytes = len(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        # Each tokenizer token consumes at least one input byte, so this deliberately
        # under-utilises the window but guarantees no oversized request without a
        # provider-specific tokenizer or a second remote counting request.
        if available_input_tokens <= 0 or serialized_bytes > available_input_tokens:
            raise ModelProviderError(
                "Model request exceeds the configured context window",
                code="model_context_limit_exceeded",
                retryable=False,
            )

    def _post_with_retries(
        self,
        payload: Mapping[str, Any],
        *,
        deadline_at: datetime | None,
        client_request_id: str,
    ) -> tuple[dict[str, Any], str | None, int]:
        for attempt in range(self._max_retries + 1):
            try:
                raw_create = cast(Any, self._client.responses.with_streaming_response.create)
                with raw_create(
                    **payload,
                    extra_headers={"X-Client-Request-Id": client_request_id},
                    timeout=self._request_timeout(deadline_at),
                ) as response:
                    content = self._bounded_content(response)
                    body = self._decode_object(content, provider_request_id=response.request_id)
                    self._validate_response(body, provider_request_id=response.request_id)
                    return body, _safe_request_id(response.request_id), attempt
            except APITimeoutError as exc:
                if attempt >= self._max_retries:
                    self._raise_provider_error(
                        "OpenAI request timed out",
                        code="model_timeout",
                        retryable=True,
                        cause=exc,
                    )
                self._wait_to_retry(attempt=attempt, deadline_at=deadline_at)
            except APIConnectionError as exc:
                if attempt >= self._max_retries:
                    self._raise_provider_error(
                        "OpenAI is unavailable",
                        code="model_unavailable",
                        retryable=True,
                        cause=exc,
                    )
                self._wait_to_retry(attempt=attempt, deadline_at=deadline_at)
            except APIStatusError as exc:
                request_id = _safe_request_id(exc.request_id)
                if exc.status_code in RETRYABLE_HTTP_STATUSES and attempt < self._max_retries:
                    self._wait_to_retry(
                        attempt=attempt,
                        deadline_at=deadline_at,
                        retry_after=_retry_after_seconds(exc.response.headers),
                    )
                    continue
                self._raise_http_error(exc.status_code, provider_request_id=request_id, cause=exc)
            except OpenAIError as exc:
                self._raise_provider_error(
                    "OpenAI SDK rejected the request",
                    code="model_request_rejected",
                    retryable=False,
                    cause=exc,
                )
        raise AssertionError("OpenAI retry loop exhausted without returning or raising")

    def _bounded_content(self, response: Any) -> bytes:
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type and content_type != "application/json":
            raise ModelProviderError(
                "OpenAI returned an unsupported media type",
                code="invalid_model_response",
                retryable=False,
                provider_request_id=_safe_request_id(response.request_id),
            )
        content_length = response.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > self._max_response_bytes:
                    self._raise_response_too_large(response.request_id)
            except ValueError:
                pass
        content = bytearray()
        for chunk in response.iter_bytes():
            if len(content) + len(chunk) > self._max_response_bytes:
                self._raise_response_too_large(response.request_id)
            content.extend(chunk)
        return bytes(content)

    def _raise_response_too_large(self, request_id: object) -> NoReturn:
        raise ModelProviderError(
            "OpenAI response exceeded the configured size limit",
            code="model_response_too_large",
            retryable=False,
            provider_request_id=_safe_request_id(request_id),
        )

    @staticmethod
    def _decode_object(content: bytes, *, provider_request_id: object) -> dict[str, Any]:
        try:
            body = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ModelProviderError(
                "OpenAI returned invalid JSON",
                code="invalid_model_response",
                retryable=False,
                provider_request_id=_safe_request_id(provider_request_id),
            ) from exc
        if not isinstance(body, dict):
            raise ModelProviderError(
                "OpenAI returned a non-object response",
                code="invalid_model_response",
                retryable=False,
                provider_request_id=_safe_request_id(provider_request_id),
            )
        return body

    @staticmethod
    def _validate_response(body: Mapping[str, Any], *, provider_request_id: object) -> None:
        request_id = _safe_request_id(provider_request_id)
        status = body.get("status")
        if status == "incomplete":
            raise ModelProviderError(
                "OpenAI returned an incomplete response",
                code="model_response_incomplete",
                retryable=False,
                provider_request_id=request_id,
            )
        if status in {"failed", "cancelled"} or body.get("error") is not None:
            raise ModelProviderError(
                "OpenAI could not complete the response",
                code="model_response_failed",
                retryable=False,
                provider_request_id=request_id,
            )
        if status != "completed":
            raise ModelProviderError(
                "OpenAI returned a non-terminal response",
                code="invalid_model_response",
                retryable=False,
                provider_request_id=request_id,
            )

    @staticmethod
    def _structured_content(
        body: Mapping[str, Any], *, provider_request_id: str | None
    ) -> dict[str, Any]:
        output = body.get("output")
        if not isinstance(output, list):
            raise ModelProviderError(
                "OpenAI response omitted output items",
                code="invalid_model_response",
                retryable=False,
                provider_request_id=provider_request_id,
            )
        texts: list[str] = []
        for item in output:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            contents = item.get("content")
            if not isinstance(contents, list):
                continue
            for content in contents:
                if not isinstance(content, dict):
                    continue
                if content.get("type") == "refusal":
                    raise ModelProviderError(
                        "OpenAI refused the structured request",
                        code="model_refused",
                        retryable=False,
                        provider_request_id=provider_request_id,
                    )
                if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                    texts.append(content["text"])
        if not texts:
            raise ModelProviderError(
                "OpenAI response omitted output text",
                code="invalid_model_response",
                retryable=False,
                provider_request_id=provider_request_id,
            )
        raw = "".join(texts)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {"invalid_model_output": raw[:10_000]}
        return parsed if isinstance(parsed, dict) else {"invalid_model_output": parsed}

    def _request_timeout(self, deadline_at: datetime | None) -> float:
        if deadline_at is None:
            return self._generation_timeout_seconds
        remaining_seconds = (deadline_at - datetime.now(UTC)).total_seconds()
        if remaining_seconds <= 0:
            raise ModelProviderError(
                "Model deadline expired before dispatch",
                code="model_timeout",
                retryable=True,
            )
        return min(self._generation_timeout_seconds, remaining_seconds)

    def _wait_to_retry(
        self,
        *,
        attempt: int,
        deadline_at: datetime | None,
        retry_after: float | None = None,
    ) -> None:
        delay = retry_after
        if delay is None:
            delay = min(2.0, 0.5 * (2**attempt)) * (0.75 + self._randomizer() * 0.5)
        if deadline_at is not None:
            remaining = (deadline_at - datetime.now(UTC)).total_seconds()
            if delay >= remaining:
                raise ModelProviderError(
                    "Model deadline would expire before retry",
                    code="model_timeout",
                    retryable=True,
                )
        self._sleeper(delay)

    @staticmethod
    def _raise_http_error(
        status_code: int,
        *,
        provider_request_id: str | None,
        cause: Exception,
    ) -> NoReturn:
        if status_code in {401, 403}:
            code, retryable = "model_authentication_failed", False
        elif status_code == 404:
            code, retryable = "model_not_found", False
        elif status_code == 408:
            code, retryable = "model_timeout", True
        elif status_code in RETRYABLE_HTTP_STATUSES:
            code, retryable = "model_overloaded", True
        else:
            code, retryable = "model_request_rejected", False
        raise ModelProviderError(
            f"OpenAI returned HTTP {status_code}",
            code=code,
            retryable=retryable,
            provider_request_id=provider_request_id,
        ) from cause

    @staticmethod
    def _raise_provider_error(
        message: str,
        *,
        code: str,
        retryable: bool,
        cause: Exception,
    ) -> NoReturn:
        raise ModelProviderError(message, code=code, retryable=retryable) from cause


def _schema_name(request: StructuredModelRequest) -> str:
    raw = f"{request.role.value}_{request.prompt_id}_{request.prompt_version}"
    normalized = re.sub(r"[^A-Za-z0-9_-]", "_", raw).strip("_-")
    return (normalized or "structured_response")[:64]


def _prompt_cache_key(request: StructuredModelRequest, *, model: str) -> str:
    schema_hash = hashlib.sha256(
        json.dumps(request.output_schema, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    source = ":".join(
        (model, request.role.value, request.prompt_id, request.prompt_version, request.prompt_hash)
    )
    return hashlib.sha256(f"{source}:{schema_hash}".encode()).hexdigest()


def _retry_after_seconds(headers: Mapping[str, str]) -> float | None:
    milliseconds = headers.get("retry-after-ms")
    if milliseconds is not None:
        try:
            value = float(milliseconds) / 1_000
        except ValueError:
            value = 0
        if 0 < value <= MAX_RETRY_AFTER_SECONDS:
            return value
    retry_after = headers.get("retry-after")
    if retry_after is None:
        return None
    try:
        value = float(retry_after)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(retry_after)
            value = (parsed - datetime.now(UTC)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return None
    return value if 0 < value <= MAX_RETRY_AFTER_SECONDS else None


def _safe_request_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped[:200] if stripped else None


def _required_string(body: Mapping[str, Any], key: str, *, fallback: str) -> str:
    value = body.get(key, fallback)
    return value if isinstance(value, str) and value else fallback


def _nested_nonnegative_int(value: object, key: str) -> int | None:
    if not isinstance(value, dict):
        return None
    return _optional_nonnegative_int(value.get(key))


def _optional_nonnegative_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
