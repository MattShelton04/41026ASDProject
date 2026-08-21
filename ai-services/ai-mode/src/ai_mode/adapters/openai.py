"""OpenAI Responses API adapter for structured model generation."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic, sleep
from typing import Any
from uuid import uuid4

import httpx

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


@dataclass(frozen=True, slots=True)
class OpenAIModelProfile:
    """Role-routed OpenAI model settings selected through a stable logical profile."""

    models: Mapping[ModelRole, str]
    maximum_output_tokens: int = 4_096
    reasoning_effort: ModelReasoningEffort = ModelReasoningEffort.LOW


class OpenAIProvider(LLMProvider):
    """Call the OpenAI Responses API while preserving the local provider contract."""

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str,
        profiles: Mapping[str, OpenAIModelProfile],
        readiness_profiles: frozenset[str] | None = None,
        timeout_seconds: float,
        health_timeout_seconds: float = 2.0,
        max_retries: int = 2,
        max_response_bytes: int,
        client: httpx.Client | None = None,
        sleeper: Callable[[float], None] = sleep,
    ) -> None:
        self._api_key = api_key
        self._profiles = dict(profiles)
        self._readiness_profiles = readiness_profiles or frozenset(self._profiles)
        if self._readiness_profiles - self._profiles.keys():
            raise ValueError("readiness profile is not registered")
        self._generation_timeout_seconds = timeout_seconds
        self._health_timeout_seconds = health_timeout_seconds
        self._max_retries = max_retries
        self._max_response_bytes = max_response_bytes
        self._sleeper = sleeper
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout_seconds),
            headers={"Accept": "application/json", "User-Agent": "asd-ai-mode/0.1"},
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
        started = monotonic()
        response = self._post_with_retries(
            payload,
            deadline_at=request.deadline_at,
            client_request_id=str(uuid4()),
        )
        total_duration_ms = max(0, int((monotonic() - started) * 1_000))
        body = self._response_object(response)
        content = self._structured_content(body)
        usage = body.get("usage")
        usage_object = usage if isinstance(usage, dict) else {}
        input_details = usage_object.get("input_tokens_details")
        output_details = usage_object.get("output_tokens_details")
        result = StructuredModelResult(
            content=content,
            provider="openai",
            model=_required_string(body, "model", fallback=model),
            metrics=ModelMetrics(
                total_duration_ms=total_duration_ms,
                prompt_tokens=_optional_nonnegative_int(usage_object.get("input_tokens")),
                output_tokens=_optional_nonnegative_int(usage_object.get("output_tokens")),
                cached_prompt_tokens=_nested_nonnegative_int(input_details, "cached_tokens"),
                reasoning_tokens=_nested_nonnegative_int(output_details, "reasoning_tokens"),
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
                "reasoning_tokens": result.metrics.reasoning_tokens,
                "repair_count": request.repair_attempt,
            },
        )
        return result

    def health(self) -> ProviderHealth:
        """Report credential and selected-model readiness without throwing."""
        if self._api_key is None:
            return ProviderHealth(
                reachable=False,
                detail="OpenAI API credentials are not configured",
            )
        try:
            models = {
                model
                for profile_name in self._readiness_profiles
                for model in self._profiles[profile_name].models.values()
            }
            for model in sorted(models):
                response = self._client.get(
                    f"/models/{model}",
                    headers=self._headers(),
                    timeout=self._health_timeout_seconds,
                )
                if response.status_code in {401, 403}:
                    return ProviderHealth(
                        reachable=False,
                        detail="OpenAI authentication or model access failed",
                    )
                if response.status_code != 200:
                    return ProviderHealth(
                        reachable=False,
                        detail=f"OpenAI model readiness returned HTTP {response.status_code}",
                    )
                if len(response.content) > self._max_response_bytes:
                    return ProviderHealth(
                        reachable=False,
                        detail="OpenAI model readiness response was too large",
                    )
                body = response.json()
                if not isinstance(body, dict) or body.get("id") != model:
                    return ProviderHealth(
                        reachable=False,
                        detail="OpenAI model readiness returned an invalid response",
                    )
            return ProviderHealth(reachable=True, detail="OpenAI and configured models are ready")
        except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
            return ProviderHealth(
                reachable=False,
                detail=f"OpenAI unavailable: {type(exc).__name__}",
            )

    def close(self) -> None:
        """Close only a client created by this adapter."""
        if self._owns_client:
            self._client.close()

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
                (
                    f"model profile {request.model_profile} does not support "
                    f"the {request.role.value} role"
                ),
                code="model_role_not_supported",
                retryable=False,
            )
        if request.max_output_tokens > profile.maximum_output_tokens:
            raise ModelProviderError(
                (
                    f"requested output limit {request.max_output_tokens} exceeds "
                    f"profile maximum {profile.maximum_output_tokens}"
                ),
                code="model_output_limit_exceeded",
                retryable=False,
            )
        return profile, model

    @staticmethod
    def _payload(
        request: StructuredModelRequest,
        profile: OpenAIModelProfile,
        *,
        model: str,
    ) -> dict[str, object]:
        system_messages = [
            message.content for message in request.messages if message.role == "system"
        ]
        input_messages = [
            {"role": message.role, "content": message.content}
            for message in request.messages
            if message.role != "system"
        ]
        if not input_messages:
            input_messages.append(
                {"role": "user", "content": "Produce the requested structured response."}
            )
        payload: dict[str, object] = {
            "model": model,
            "input": input_messages,
            "max_output_tokens": request.max_output_tokens,
            "reasoning": {"effort": profile.reasoning_effort.value},
            "store": False,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": _schema_name(request),
                    "schema": request.output_schema,
                    # The Plan contract intentionally contains dynamic tool arguments,
                    # which cannot satisfy OpenAI's all-properties-closed strict subset.
                    # Agent-core still validates the complete schema and performs one repair.
                    "strict": False,
                }
            },
        }
        if system_messages:
            payload["instructions"] = "\n\n".join(system_messages)
        if profile.reasoning_effort is ModelReasoningEffort.NONE:
            payload["temperature"] = request.temperature
        return payload

    def _post_with_retries(
        self,
        payload: Mapping[str, object],
        *,
        deadline_at: datetime | None,
        client_request_id: str,
    ) -> httpx.Response:
        for attempt in range(self._max_retries + 1):
            try:
                with self._client.stream(
                    "POST",
                    "/responses",
                    json=payload,
                    headers=self._headers(client_request_id=client_request_id),
                    timeout=self._request_timeout(deadline_at),
                ) as response:
                    if response.status_code in RETRYABLE_HTTP_STATUSES:
                        if attempt < self._max_retries:
                            retry_after = response.headers.get("retry-after")
                        else:
                            self._raise_http_error(response.status_code)
                    elif response.status_code >= 400:
                        self._raise_http_error(response.status_code)
                    else:
                        return self._bounded_response(response)
            except httpx.TimeoutException as exc:
                if attempt < self._max_retries:
                    self._wait_to_retry(attempt=attempt, deadline_at=deadline_at)
                    continue
                raise ModelProviderError(
                    "OpenAI request timed out", code="model_timeout", retryable=True
                ) from exc
            except httpx.NetworkError as exc:
                if attempt < self._max_retries:
                    self._wait_to_retry(attempt=attempt, deadline_at=deadline_at)
                    continue
                raise ModelProviderError(
                    "OpenAI is unavailable", code="model_unavailable", retryable=True
                ) from exc
            self._wait_to_retry(
                attempt=attempt,
                deadline_at=deadline_at,
                retry_after=retry_after,
            )
        raise AssertionError("OpenAI retry loop exhausted without returning or raising")

    def _bounded_response(self, response: httpx.Response) -> httpx.Response:
        content = bytearray()
        for chunk in response.iter_bytes():
            if len(content) + len(chunk) > self._max_response_bytes:
                raise ModelProviderError(
                    "OpenAI response exceeded the configured size limit",
                    code="model_response_too_large",
                    retryable=False,
                )
            content.extend(chunk)
        return httpx.Response(
            response.status_code,
            headers=response.headers,
            content=bytes(content),
            request=response.request,
        )

    def _headers(self, *, client_request_id: str | None = None) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self._api_key is not None:
            headers["Authorization"] = f"Bearer {self._api_key}"
        if client_request_id is not None:
            headers["X-Client-Request-Id"] = client_request_id
        return headers

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
        retry_after: str | None = None,
    ) -> None:
        delay = min(2.0, 0.5 * (2**attempt))
        if retry_after is not None:
            try:
                parsed = float(retry_after)
            except ValueError:
                parsed = 0
            if 0 < parsed <= 60:
                delay = parsed
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
    def _raise_http_error(status_code: int) -> None:
        if status_code in {401, 403}:
            code = "model_authentication_failed"
            retryable = False
        elif status_code == 404:
            code = "model_not_found"
            retryable = False
        elif status_code == 408:
            code = "model_timeout"
            retryable = True
        elif status_code in RETRYABLE_HTTP_STATUSES:
            code = "model_overloaded"
            retryable = True
        else:
            code = "model_request_rejected"
            retryable = False
        raise ModelProviderError(
            f"OpenAI returned HTTP {status_code}",
            code=code,
            retryable=retryable,
        )

    @staticmethod
    def _response_object(response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except json.JSONDecodeError as exc:
            raise ModelProviderError(
                "OpenAI returned invalid JSON",
                code="invalid_model_response",
                retryable=False,
            ) from exc
        if not isinstance(body, dict):
            raise ModelProviderError(
                "OpenAI returned a non-object response",
                code="invalid_model_response",
                retryable=False,
            )
        status = body.get("status")
        if status == "incomplete":
            raise ModelProviderError(
                "OpenAI returned an incomplete response",
                code="model_response_incomplete",
                retryable=False,
            )
        if status in {"failed", "cancelled"} or body.get("error") is not None:
            raise ModelProviderError(
                "OpenAI could not complete the response",
                code="model_response_failed",
                retryable=False,
            )
        if status != "completed":
            raise ModelProviderError(
                "OpenAI returned a non-terminal response",
                code="invalid_model_response",
                retryable=False,
            )
        return body

    @staticmethod
    def _structured_content(body: Mapping[str, Any]) -> dict[str, Any]:
        output = body.get("output")
        if not isinstance(output, list):
            raise ModelProviderError(
                "OpenAI response omitted output items",
                code="invalid_model_response",
                retryable=False,
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
                    )
                if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                    texts.append(content["text"])
        if not texts:
            raise ModelProviderError(
                "OpenAI response omitted output text",
                code="invalid_model_response",
                retryable=False,
            )
        raw = "".join(texts)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {"invalid_model_output": raw[:10_000]}
        if not isinstance(parsed, dict):
            return {"invalid_model_output": parsed}
        return parsed


def _schema_name(request: StructuredModelRequest) -> str:
    raw = f"{request.role.value}_{request.prompt_id}_{request.prompt_version}"
    normalized = re.sub(r"[^A-Za-z0-9_-]", "_", raw).strip("_-")
    return (normalized or "structured_response")[:64]


def _required_string(body: Mapping[str, Any], key: str, *, fallback: str) -> str:
    value = body.get(key, fallback)
    return value if isinstance(value, str) and value else fallback


def _nested_nonnegative_int(value: object, key: str) -> int | None:
    if not isinstance(value, dict):
        return None
    return _optional_nonnegative_int(value.get(key))


def _optional_nonnegative_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
