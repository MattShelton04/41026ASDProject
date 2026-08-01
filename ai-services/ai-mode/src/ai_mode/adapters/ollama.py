"""Native Ollama API adapter for structured model generation."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from threading import Lock
from typing import Any

import httpx

from agent_core import (
    LLMProvider,
    ModelMetrics,
    ModelProviderError,
    ProviderHealth,
    StructuredModelRequest,
    StructuredModelResult,
)

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OllamaModelProfile:
    """Concrete model settings selected through a stable logical profile."""

    model: str
    keep_alive: str = "5m"
    digest: str | None = None


class OllamaProvider(LLMProvider):
    """Call Ollama's native chat API with JSON Schema constrained output."""

    def __init__(
        self,
        *,
        base_url: str,
        profiles: Mapping[str, OllamaModelProfile],
        timeout_seconds: float,
        health_timeout_seconds: float = 2.0,
        max_response_bytes: int,
        client: httpx.Client | None = None,
    ) -> None:
        self._profiles = dict(profiles)
        self._max_response_bytes = max_response_bytes
        self._health_timeout_seconds = health_timeout_seconds
        self._generation_timeout_seconds = timeout_seconds
        self._unsupported_schema_digests: set[str] = set()
        self._schema_lock = Lock()
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout_seconds),
            headers={"Accept": "application/json", "User-Agent": "asd-ai-mode/0.1"},
        )

    def generate_structured(self, request: StructuredModelRequest) -> StructuredModelResult:
        """Generate structured output and preserve provider timing metadata."""
        profile = self._profiles.get(request.model_profile)
        if profile is None:
            raise ModelProviderError(
                f"unknown model profile: {request.model_profile}",
                code="model_profile_not_found",
                retryable=False,
            )
        payload = {
            "model": profile.model,
            "messages": [message.model_dump(mode="json") for message in request.messages],
            "stream": False,
            "format": self._format_spec(request.output_schema),
            "keep_alive": profile.keep_alive,
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_output_tokens,
            },
        }
        response = self._post(payload, deadline_at=request.deadline_at)
        if len(response.content) > self._max_response_bytes:
            raise ModelProviderError(
                "Ollama response exceeded the configured size limit",
                code="model_response_too_large",
                retryable=False,
            )
        body = self._response_object(response)
        content = self._structured_content(body)
        return StructuredModelResult(
            content=content,
            provider="ollama",
            model=_required_string(body, "model", fallback=profile.model),
            model_digest=profile.digest,
            metrics=ModelMetrics(
                total_duration_ms=_nanoseconds_to_ms(body.get("total_duration")),
                load_duration_ms=_optional_nanoseconds_to_ms(body.get("load_duration")),
                prompt_eval_duration_ms=_optional_nanoseconds_to_ms(
                    body.get("prompt_eval_duration")
                ),
                eval_duration_ms=_optional_nanoseconds_to_ms(body.get("eval_duration")),
                prompt_tokens=_optional_nonnegative_int(body.get("prompt_eval_count")),
                output_tokens=_optional_nonnegative_int(body.get("eval_count")),
            ),
        )

    def health(self) -> ProviderHealth:
        """Report endpoint and configured-model readiness without throwing."""
        try:
            response = self._client.get("/api/tags", timeout=self._health_timeout_seconds)
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError("response was not an object")
            available = {
                item.get("name")
                for item in body.get("models", [])
                if isinstance(item, dict) and isinstance(item.get("name"), str)
            }
            required = {profile.model for profile in self._profiles.values()}
            missing = sorted(required - available)
            if missing:
                return ProviderHealth(
                    reachable=False,
                    detail=f"Ollama reachable; configured models missing: {', '.join(missing)}",
                )
            return ProviderHealth(reachable=True, detail="Ollama and configured models are ready")
        except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
            return ProviderHealth(
                reachable=False,
                detail=f"Ollama unavailable: {type(exc).__name__}",
            )

    def close(self) -> None:
        """Close only a client created by this adapter."""
        if self._owns_client:
            self._client.close()

    def _post(
        self,
        payload: Mapping[str, object],
        *,
        deadline_at: datetime | None,
    ) -> httpx.Response:
        try:
            response = self._client.post(
                "/api/chat",
                json=payload,
                timeout=self._request_timeout(deadline_at),
            )
            if _is_grammar_rejection(response, payload.get("format")):
                format_spec = payload["format"]
                if isinstance(format_spec, dict):
                    with self._schema_lock:
                        self._unsupported_schema_digests.add(_schema_digest(format_spec))
                LOGGER.warning(
                    "Ollama rejected the JSON Schema grammar; using JSON mode with "
                    "application-side validation"
                )
                response = self._client.post(
                    "/api/chat",
                    json={**payload, "format": "json"},
                    timeout=self._request_timeout(deadline_at),
                )
            response.raise_for_status()
            return response
        except httpx.TimeoutException as exc:
            raise ModelProviderError(
                "Ollama request timed out", code="model_timeout", retryable=True
            ) from exc
        except httpx.NetworkError as exc:
            raise ModelProviderError(
                "Ollama is unavailable", code="model_unavailable", retryable=True
            ) from exc
        except httpx.HTTPStatusError as exc:
            retryable = exc.response.status_code in {408, 429, 502, 503, 504}
            raise ModelProviderError(
                f"Ollama returned HTTP {exc.response.status_code}",
                code="model_overloaded" if retryable else "model_request_rejected",
                retryable=retryable,
            ) from exc

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

    def _format_spec(self, schema: dict[str, Any]) -> dict[str, Any] | str:
        digest = _schema_digest(schema)
        with self._schema_lock:
            unsupported = digest in self._unsupported_schema_digests
        return "json" if unsupported else schema

    @staticmethod
    def _response_object(response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except json.JSONDecodeError as exc:
            raise ModelProviderError(
                "Ollama returned invalid JSON", code="invalid_model_response", retryable=False
            ) from exc
        if not isinstance(body, dict):
            raise ModelProviderError(
                "Ollama returned a non-object response",
                code="invalid_model_response",
                retryable=False,
            )
        return body

    @staticmethod
    def _structured_content(body: Mapping[str, Any]) -> dict[str, Any]:
        message = body.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise ModelProviderError(
                "Ollama response omitted message content",
                code="invalid_model_response",
                retryable=False,
            )
        raw = message["content"]
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {"invalid_model_output": raw[:10_000]}
        if not isinstance(parsed, dict):
            return {"invalid_model_output": parsed}
        return parsed


def _required_string(body: Mapping[str, Any], key: str, *, fallback: str) -> str:
    value = body.get(key, fallback)
    return value if isinstance(value, str) and value else fallback


def _nanoseconds_to_ms(value: object) -> int:
    parsed = _optional_nonnegative_int(value)
    return 0 if parsed is None else parsed // 1_000_000


def _optional_nanoseconds_to_ms(value: object) -> int | None:
    parsed = _optional_nonnegative_int(value)
    return None if parsed is None else parsed // 1_000_000


def _optional_nonnegative_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _is_grammar_rejection(response: httpx.Response, format_spec: object) -> bool:
    """Recognize Ollama/llama.cpp schema-complexity rejection without masking other 400s."""
    if response.status_code != 400 or not isinstance(format_spec, dict):
        return False
    if len(response.content) > 10_000:
        return False
    try:
        body = response.json()
    except json.JSONDecodeError:
        return False
    error = body.get("error") if isinstance(body, dict) else None
    return isinstance(error, str) and "failed to parse grammar" in error.lower()


def _schema_digest(schema: Mapping[str, Any]) -> str:
    canonical = json.dumps(schema, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256(canonical.encode("utf-8")).hexdigest()
