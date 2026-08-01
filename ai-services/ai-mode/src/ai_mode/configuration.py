"""Validated environment configuration for the AI-mode service."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


class ConfigurationError(ValueError):
    """A required setting is invalid before the service starts."""


@dataclass(frozen=True, slots=True)
class Settings:
    """Small, explicit set of Release 0 runtime settings."""

    database_path: Path
    ollama_base_url: str
    ollama_model: str
    ollama_timeout_seconds: float
    ollama_keep_alive: str
    max_model_response_bytes: int
    require_ollama_ready: bool = False

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        """Load settings without mutating process environment or performing I/O."""
        values = os.environ if environ is None else environ
        base_url = values.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        # The course guide uses the OpenAI-compatible /v1 URL; this service intentionally
        # uses Ollama's native API to retain structured output and detailed timings.
        if base_url.endswith("/v1"):
            base_url = base_url[:-3]
        if not base_url.startswith(("http://", "https://")):
            raise ConfigurationError("OLLAMA_BASE_URL must use http or https")

        timeout = _positive_float(values.get("OLLAMA_TIMEOUT_SECONDS", "120"), "timeout")
        max_bytes = _bounded_int(
            values.get("AI_MODE_MAX_MODEL_RESPONSE_BYTES", "1048576"),
            "maximum model response bytes",
            minimum=1_024,
            maximum=10_485_760,
        )
        model = values.get("OLLAMA_MODEL", "qwen2.5:0.5b").strip()
        if not model:
            raise ConfigurationError("OLLAMA_MODEL cannot be empty")
        keep_alive = values.get("OLLAMA_KEEP_ALIVE", "5m").strip()
        if not keep_alive:
            raise ConfigurationError("OLLAMA_KEEP_ALIVE cannot be empty")

        return cls(
            database_path=Path(values.get("AI_MODE_DATABASE_PATH", "instance/agent-state.sqlite3")),
            ollama_base_url=base_url,
            ollama_model=model,
            ollama_timeout_seconds=timeout,
            ollama_keep_alive=keep_alive,
            max_model_response_bytes=max_bytes,
            require_ollama_ready=_boolean(
                values.get("AI_MODE_REQUIRE_OLLAMA_READY", "false"),
                "strict Ollama readiness",
            ),
        )


def _positive_float(value: str, label: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ConfigurationError(f"{label} must be numeric") from exc
    if parsed <= 0:
        raise ConfigurationError(f"{label} must be greater than zero")
    return parsed


def _bounded_int(value: str, label: str, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConfigurationError(f"{label} must be an integer") from exc
    if not minimum <= parsed <= maximum:
        raise ConfigurationError(f"{label} must be between {minimum} and {maximum}")
    return parsed


def _boolean(value: str, label: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise ConfigurationError(f"{label} must be true or false")
