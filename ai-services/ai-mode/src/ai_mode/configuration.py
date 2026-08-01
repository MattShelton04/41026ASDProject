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
    ollama_timeout_seconds: float
    ollama_keep_alive: str | None
    max_model_response_bytes: int
    ollama_health_timeout_seconds: float = 2.0
    require_ollama_ready: bool = False
    max_request_bytes: int = 65_536
    max_tool_request_bytes: int = 262_144
    max_tool_response_bytes: int = 1_048_576
    tool_catalog_path: Path | None = None
    model_registry_path: Path | None = None
    default_model_profile: str | None = None
    evidence_access_token: str | None = None

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
        health_timeout = _positive_float(
            values.get("OLLAMA_HEALTH_TIMEOUT_SECONDS", "2"),
            "health timeout",
        )
        max_bytes = _bounded_int(
            values.get("AI_MODE_MAX_MODEL_RESPONSE_BYTES", "1048576"),
            "maximum model response bytes",
            minimum=1_024,
            maximum=10_485_760,
        )
        max_request_bytes = _bounded_int(
            values.get("AI_MODE_MAX_REQUEST_BYTES", "65536"),
            "maximum API request bytes",
            minimum=1_024,
            maximum=1_048_576,
        )
        max_tool_request_bytes = _bounded_int(
            values.get("AI_MODE_MAX_TOOL_REQUEST_BYTES", "262144"),
            "maximum tool request bytes",
            minimum=1_024,
            maximum=10_485_760,
        )
        max_tool_response_bytes = _bounded_int(
            values.get("AI_MODE_MAX_TOOL_RESPONSE_BYTES", "1048576"),
            "maximum tool response bytes",
            minimum=1_024,
            maximum=10_485_760,
        )
        keep_alive_value = values.get("OLLAMA_KEEP_ALIVE")
        keep_alive = keep_alive_value.strip() if keep_alive_value is not None else None
        if keep_alive_value is not None and not keep_alive:
            raise ConfigurationError("OLLAMA_KEEP_ALIVE cannot be empty")
        catalog_value = values.get("AI_MODE_TOOL_CATALOG_PATH", "").strip()
        registry_value = values.get("AI_MODE_MODEL_REGISTRY_PATH", "").strip()
        default_profile = values.get("AI_MODE_DEFAULT_MODEL_PROFILE", "").strip() or None
        if default_profile is not None and not _identifier(default_profile):
            raise ConfigurationError("AI_MODE_DEFAULT_MODEL_PROFILE is invalid")
        evidence_token = values.get("AI_MODE_EVIDENCE_ACCESS_TOKEN", "").strip() or None
        if evidence_token is not None and len(evidence_token) < 16:
            raise ConfigurationError("AI_MODE_EVIDENCE_ACCESS_TOKEN must be at least 16 characters")

        return cls(
            database_path=Path(values.get("AI_MODE_DATABASE_PATH", "instance/agent-state.sqlite3")),
            ollama_base_url=base_url,
            ollama_timeout_seconds=timeout,
            ollama_keep_alive=keep_alive,
            max_model_response_bytes=max_bytes,
            ollama_health_timeout_seconds=health_timeout,
            require_ollama_ready=_boolean(
                values.get("AI_MODE_REQUIRE_OLLAMA_READY", "false"),
                "strict Ollama readiness",
            ),
            max_request_bytes=max_request_bytes,
            max_tool_request_bytes=max_tool_request_bytes,
            max_tool_response_bytes=max_tool_response_bytes,
            tool_catalog_path=Path(catalog_value) if catalog_value else None,
            model_registry_path=Path(registry_value) if registry_value else None,
            default_model_profile=default_profile,
            evidence_access_token=evidence_token,
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


def _identifier(value: str) -> bool:
    return (
        len(value) <= 100
        and value[0].isalnum()
        and all(
            character.islower() or character.isdigit() or character in "._-" for character in value
        )
    )
