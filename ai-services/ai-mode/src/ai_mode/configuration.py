"""Validated environment configuration for the AI-mode service."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_DATABASE_PATH = Path("instance/agent-state.sqlite3")
DEFAULT_LLM_PROVIDER = "openai"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_OPENAI_TIMEOUT_SECONDS = 120.0
DEFAULT_OPENAI_HEALTH_TIMEOUT_SECONDS = 2.0
DEFAULT_OPENAI_MAX_RETRIES = 2
DEFAULT_MAX_MODEL_RESPONSE_BYTES = 1_048_576
DEFAULT_MAX_REQUEST_BYTES = 65_536
DEFAULT_MAX_TOOL_REQUEST_BYTES = 262_144
DEFAULT_MAX_TOOL_RESPONSE_BYTES = 1_048_576
DEFAULT_QUEUE_CAPACITY = 100
DEFAULT_QUEUE_RECONCILE_INTERVAL_SECONDS = 1.0
DEFAULT_ENVIRONMENT = "local"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_OPERATIONS_ASSETS_PATH = (
    Path(__file__).resolve().parents[4] / "shared" / "frontend" / "operations" / "ai-mode"
)
SUPPORTED_LLM_PROVIDERS = frozenset({"openai"})
SUPPORTED_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


class ConfigurationError(ValueError):
    """A required setting is invalid before the service starts."""


@dataclass(frozen=True, slots=True)
class Settings:
    """Small, explicit set of AI-mode runtime settings."""

    database_path: Path = DEFAULT_DATABASE_PATH
    llm_provider: str = DEFAULT_LLM_PROVIDER
    openai_api_key: str | None = field(default=None, repr=False)
    openai_base_url: str = DEFAULT_OPENAI_BASE_URL
    openai_timeout_seconds: float = DEFAULT_OPENAI_TIMEOUT_SECONDS
    openai_health_timeout_seconds: float = DEFAULT_OPENAI_HEALTH_TIMEOUT_SECONDS
    openai_max_retries: int = DEFAULT_OPENAI_MAX_RETRIES
    max_model_response_bytes: int = DEFAULT_MAX_MODEL_RESPONSE_BYTES
    require_provider_ready: bool = False
    max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES
    max_tool_request_bytes: int = DEFAULT_MAX_TOOL_REQUEST_BYTES
    max_tool_response_bytes: int = DEFAULT_MAX_TOOL_RESPONSE_BYTES
    queue_capacity: int = DEFAULT_QUEUE_CAPACITY
    queue_reconcile_interval_seconds: float = DEFAULT_QUEUE_RECONCILE_INTERVAL_SECONDS
    tool_catalog_path: Path | None = None
    tool_catalog_paths: tuple[Path, ...] = ()
    model_registry_path: Path | None = None
    default_model_profile: str | None = None
    evidence_access_token: str | None = field(default=None, repr=False)
    operations_enabled: bool = False
    operations_assets_path: Path = DEFAULT_OPERATIONS_ASSETS_PATH
    environment: str = DEFAULT_ENVIRONMENT
    log_level: str = DEFAULT_LOG_LEVEL

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        """Load settings without mutating process environment or performing I/O."""
        values = os.environ if environ is None else environ
        provider = values.get("AI_MODE_LLM_PROVIDER", DEFAULT_LLM_PROVIDER).strip().lower()
        if provider not in SUPPORTED_LLM_PROVIDERS:
            raise ConfigurationError(
                f"AI_MODE_LLM_PROVIDER must be one of: {', '.join(sorted(SUPPORTED_LLM_PROVIDERS))}"
            )
        base_url = values.get("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL).rstrip("/")
        _validate_provider_url(base_url)
        api_key = _optional_secret(values.get("OPENAI_API_KEY"), "OPENAI_API_KEY")
        timeout = _positive_float(
            values.get("OPENAI_TIMEOUT_SECONDS", str(DEFAULT_OPENAI_TIMEOUT_SECONDS)),
            "OpenAI timeout",
        )
        health_timeout = _positive_float(
            values.get(
                "OPENAI_HEALTH_TIMEOUT_SECONDS",
                str(DEFAULT_OPENAI_HEALTH_TIMEOUT_SECONDS),
            ),
            "OpenAI health timeout",
        )
        max_retries = _bounded_int(
            values.get("OPENAI_MAX_RETRIES", str(DEFAULT_OPENAI_MAX_RETRIES)),
            "OpenAI maximum retries",
            minimum=0,
            maximum=5,
        )
        max_bytes = _bounded_int(
            values.get("AI_MODE_MAX_MODEL_RESPONSE_BYTES", str(DEFAULT_MAX_MODEL_RESPONSE_BYTES)),
            "maximum model response bytes",
            minimum=1_024,
            maximum=10_485_760,
        )
        max_request_bytes = _bounded_int(
            values.get("AI_MODE_MAX_REQUEST_BYTES", str(DEFAULT_MAX_REQUEST_BYTES)),
            "maximum API request bytes",
            minimum=1_024,
            maximum=1_048_576,
        )
        max_tool_request_bytes = _bounded_int(
            values.get("AI_MODE_MAX_TOOL_REQUEST_BYTES", str(DEFAULT_MAX_TOOL_REQUEST_BYTES)),
            "maximum tool request bytes",
            minimum=1_024,
            maximum=10_485_760,
        )
        max_tool_response_bytes = _bounded_int(
            values.get("AI_MODE_MAX_TOOL_RESPONSE_BYTES", str(DEFAULT_MAX_TOOL_RESPONSE_BYTES)),
            "maximum tool response bytes",
            minimum=1_024,
            maximum=10_485_760,
        )
        catalog_value = values.get("AI_MODE_TOOL_CATALOG_PATH", "").strip()
        catalog_values = values.get("AI_MODE_TOOL_CATALOG_PATHS", "").strip()
        if catalog_value and catalog_values:
            raise ConfigurationError(
                "set only one of AI_MODE_TOOL_CATALOG_PATH or AI_MODE_TOOL_CATALOG_PATHS"
            )
        catalog_paths = _catalog_paths(catalog_values)
        registry_value = values.get("AI_MODE_MODEL_REGISTRY_PATH", "").strip()
        default_profile = values.get("AI_MODE_DEFAULT_MODEL_PROFILE", "").strip() or None
        if default_profile is not None and not _identifier(default_profile):
            raise ConfigurationError("AI_MODE_DEFAULT_MODEL_PROFILE is invalid")
        evidence_token = _optional_secret(
            values.get("AI_MODE_EVIDENCE_ACCESS_TOKEN"),
            "AI_MODE_EVIDENCE_ACCESS_TOKEN",
        )
        if evidence_token is not None and len(evidence_token) < 16:
            raise ConfigurationError("AI_MODE_EVIDENCE_ACCESS_TOKEN must be at least 16 characters")
        queue_capacity = _bounded_int(
            values.get("AI_MODE_QUEUE_CAPACITY", str(DEFAULT_QUEUE_CAPACITY)),
            "queue capacity",
            minimum=1,
            maximum=10_000,
        )
        reconcile_interval = _positive_float(
            values.get(
                "AI_MODE_QUEUE_RECONCILE_INTERVAL_SECONDS",
                str(DEFAULT_QUEUE_RECONCILE_INTERVAL_SECONDS),
            ),
            "queue reconcile interval",
        )
        environment = values.get("AI_MODE_ENVIRONMENT", DEFAULT_ENVIRONMENT).strip()
        if not _identifier(environment):
            raise ConfigurationError("AI_MODE_ENVIRONMENT is invalid")
        log_level = values.get("AI_MODE_LOG_LEVEL", DEFAULT_LOG_LEVEL).strip().upper()
        if log_level not in SUPPORTED_LOG_LEVELS:
            raise ConfigurationError(
                "AI_MODE_LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL"
            )

        return cls(
            database_path=Path(values.get("AI_MODE_DATABASE_PATH", str(DEFAULT_DATABASE_PATH))),
            llm_provider=provider,
            openai_api_key=api_key,
            openai_base_url=base_url,
            openai_timeout_seconds=timeout,
            openai_health_timeout_seconds=health_timeout,
            openai_max_retries=max_retries,
            max_model_response_bytes=max_bytes,
            require_provider_ready=_boolean(
                values.get("AI_MODE_REQUIRE_PROVIDER_READY", "false"),
                "strict provider readiness",
            ),
            max_request_bytes=max_request_bytes,
            max_tool_request_bytes=max_tool_request_bytes,
            max_tool_response_bytes=max_tool_response_bytes,
            queue_capacity=queue_capacity,
            queue_reconcile_interval_seconds=reconcile_interval,
            tool_catalog_path=Path(catalog_value) if catalog_value else None,
            tool_catalog_paths=catalog_paths,
            model_registry_path=Path(registry_value) if registry_value else None,
            default_model_profile=default_profile,
            evidence_access_token=evidence_token,
            operations_enabled=_boolean(
                values.get("AI_MODE_OPERATIONS_ENABLED", "false"),
                "operations interface",
            ),
            operations_assets_path=Path(
                values.get("AI_MODE_OPERATIONS_ASSETS_PATH", str(DEFAULT_OPERATIONS_ASSETS_PATH))
            ),
            environment=environment,
            log_level=log_level,
        )

    @property
    def configured_tool_catalog_paths(self) -> tuple[Path, ...]:
        """Return the multi-catalog setting or its legacy single-path equivalent."""
        if self.tool_catalog_paths:
            return self.tool_catalog_paths
        if self.tool_catalog_path is not None:
            return (self.tool_catalog_path,)
        return ()


def _validate_provider_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigurationError("OPENAI_BASE_URL must be an absolute http or https URL")
    if parsed.username is not None or parsed.password is not None:
        raise ConfigurationError("OPENAI_BASE_URL must not contain credentials")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ConfigurationError("OPENAI_BASE_URL must use https except for loopback development")


def _optional_secret(value: str | None, label: str) -> str | None:
    if value is None:
        return None
    secret = value.strip()
    if not secret:
        return None
    if len(secret) > 4_096 or any(character in secret for character in "\r\n"):
        raise ConfigurationError(f"{label} is invalid")
    return secret


def _catalog_paths(value: str) -> tuple[Path, ...]:
    if not value:
        return ()
    raw_paths = value.split(",")
    if any(not raw_path.strip() for raw_path in raw_paths):
        raise ConfigurationError("AI_MODE_TOOL_CATALOG_PATHS contains an empty path")
    paths = tuple(Path(raw_path.strip()) for raw_path in raw_paths)
    if len(paths) != len(set(paths)):
        raise ConfigurationError("AI_MODE_TOOL_CATALOG_PATHS must not contain duplicates")
    return paths


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
        bool(value)
        and len(value) <= 100
        and value[0].isalnum()
        and all(
            character.islower() or character.isdigit() or character in "._-" for character in value
        )
    )
