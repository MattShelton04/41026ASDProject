"""Validated environment configuration for the AI-mode service."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_DATABASE_PATH = Path("instance/agent-state.sqlite3")
DEFAULT_LLM_PROVIDER = "openai"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
DEFAULT_OPENAI_TIMEOUT_SECONDS = 120.0
DEFAULT_OPENAI_HEALTH_TIMEOUT_SECONDS = 2.0
DEFAULT_OPENAI_HEALTH_CACHE_SECONDS = 60.0
DEFAULT_OPENAI_MAX_RETRIES = 2
DEFAULT_OPENAI_PROMPT_CACHE_ENABLED = True
DEFAULT_OPENAI_ALLOW_INSECURE_HTTP = False
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
SUPPORTED_LLM_PROVIDERS = frozenset({"gemini", "openai"})
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
    gemini_api_key: str | None = field(default=None, repr=False)
    gemini_base_url: str = DEFAULT_GEMINI_BASE_URL
    openai_timeout_seconds: float = DEFAULT_OPENAI_TIMEOUT_SECONDS
    openai_health_timeout_seconds: float = DEFAULT_OPENAI_HEALTH_TIMEOUT_SECONDS
    openai_health_cache_seconds: float = DEFAULT_OPENAI_HEALTH_CACHE_SECONDS
    openai_max_retries: int = DEFAULT_OPENAI_MAX_RETRIES
    openai_prompt_cache_enabled: bool = DEFAULT_OPENAI_PROMPT_CACHE_ENABLED
    openai_allow_insecure_http: bool = DEFAULT_OPENAI_ALLOW_INSECURE_HTTP
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
    mcp_enabled: bool = False
    rag_enabled: bool = False
    mcp_server_url: str = "http://127.0.0.1:5011/mcp"
    rag_server_url: str = "http://127.0.0.1:5012"
    mcp_service_token: str | None = field(default=None, repr=False)
    rag_service_token: str | None = field(default=None, repr=False)
    rag_corpora: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        """Keep safety-critical timing invariants true for injected settings too."""
        _require_positive_finite(self.openai_timeout_seconds, "OpenAI timeout")
        _require_positive_finite(self.openai_health_timeout_seconds, "OpenAI health timeout")
        if self.environment not in {"local", "compose"} and (self.mcp_enabled or self.rag_enabled):
            raise ConfigurationError("MCP and RAG are local-only capabilities")
        for enabled, token, url in (
            (self.mcp_enabled, self.mcp_service_token, self.mcp_server_url),
            (self.rag_enabled, self.rag_service_token, self.rag_server_url),
        ):
            if enabled and (not token or len(token) < 32):
                raise ConfigurationError("Enabled local AI services require a 32-character token")
            parsed = urlparse(url)
            if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
                raise ConfigurationError("Shared MCP/RAG URLs must be loopback HTTP endpoints")
            if parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ConfigurationError("Shared service URL cannot contain credentials or query")
        _require_positive_finite(
            self.queue_reconcile_interval_seconds,
            "queue reconcile interval",
        )

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        """Load settings without mutating process environment; read an explicit secret file."""
        values = os.environ if environ is None else environ
        provider = values.get("AI_MODE_LLM_PROVIDER", DEFAULT_LLM_PROVIDER).strip().lower()
        if provider not in SUPPORTED_LLM_PROVIDERS:
            raise ConfigurationError(
                f"AI_MODE_LLM_PROVIDER must be one of: {', '.join(sorted(SUPPORTED_LLM_PROVIDERS))}"
            )
        base_url = values.get("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL).rstrip("/")
        gemini_base_url = values.get("GEMINI_BASE_URL", DEFAULT_GEMINI_BASE_URL).rstrip("/")
        allow_insecure_http = _boolean(
            values.get(
                "OPENAI_ALLOW_INSECURE_HTTP",
                str(DEFAULT_OPENAI_ALLOW_INSECURE_HTTP),
            ),
            "OpenAI insecure HTTP opt-in",
        )
        _validate_provider_url(
            base_url,
            label="OPENAI_BASE_URL",
            allow_insecure_http=allow_insecure_http,
        )
        _validate_provider_url(
            gemini_base_url,
            label="GEMINI_BASE_URL",
            allow_insecure_http=allow_insecure_http,
        )
        api_key = (
            _configured_secret(
                values,
                value_name="OPENAI_API_KEY",
                file_name="OPENAI_API_KEY_FILE",
            )
            if provider == "openai"
            else None
        )
        gemini_api_key = (
            _configured_secret(
                values,
                value_name="GEMINI_API_KEY",
                file_name="GEMINI_API_KEY_FILE",
            )
            if provider == "gemini"
            else None
        )
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
        health_cache = _bounded_float(
            values.get(
                "OPENAI_HEALTH_CACHE_SECONDS",
                str(DEFAULT_OPENAI_HEALTH_CACHE_SECONDS),
            ),
            "OpenAI health cache",
            minimum=1.0,
            maximum=3_600.0,
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
            gemini_api_key=gemini_api_key,
            gemini_base_url=gemini_base_url,
            openai_timeout_seconds=timeout,
            openai_health_timeout_seconds=health_timeout,
            openai_health_cache_seconds=health_cache,
            openai_max_retries=max_retries,
            openai_prompt_cache_enabled=_boolean(
                values.get(
                    "OPENAI_PROMPT_CACHE_ENABLED",
                    str(DEFAULT_OPENAI_PROMPT_CACHE_ENABLED),
                ),
                "OpenAI prompt caching",
            ),
            openai_allow_insecure_http=allow_insecure_http,
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
            mcp_enabled=_boolean(values.get("AI_MODE_MCP_ENABLED", "false"), "AI_MODE_MCP_ENABLED"),
            rag_enabled=_boolean(values.get("AI_MODE_RAG_ENABLED", "false"), "AI_MODE_RAG_ENABLED"),
            mcp_server_url=values.get("MCP_SERVER_URL", "http://127.0.0.1:5011/mcp"),
            rag_server_url=values.get("RAG_SERVER_URL", "http://127.0.0.1:5012"),
            mcp_service_token=values.get("MCP_SERVICE_TOKEN"),
            rag_service_token=values.get("RAG_SERVICE_TOKEN"),
            rag_corpora=_corpus_scopes(
                values.get(
                    "AI_MODE_RAG_CORPORA", "student-1-propertyscope-data-platform:operator-guidance"
                )
            ),
        )

    @property
    def configured_tool_catalog_paths(self) -> tuple[Path, ...]:
        """Return the multi-catalog setting or its legacy single-path equivalent."""
        if self.tool_catalog_paths:
            return self.tool_catalog_paths
        if self.tool_catalog_path is not None:
            return (self.tool_catalog_path,)
        return ()


def _validate_provider_url(
    value: str,
    *,
    label: str,
    allow_insecure_http: bool,
) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigurationError(f"{label} must be an absolute http or https URL")
    if parsed.username is not None or parsed.password is not None:
        raise ConfigurationError(f"{label} must not contain credentials")
    if (
        parsed.scheme == "http"
        and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        and not allow_insecure_http
    ):
        raise ConfigurationError(
            f"{label} must use https; set OPENAI_ALLOW_INSECURE_HTTP=true "
            "only for trusted local development"
        )


def _optional_secret(value: str | None, label: str) -> str | None:
    if value is None:
        return None
    secret = value.strip()
    if not secret:
        return None
    if len(secret) > 4_096 or any(character in secret for character in "\r\n"):
        raise ConfigurationError(f"{label} is invalid")
    return secret


def _configured_secret(
    values: Mapping[str, str],
    *,
    value_name: str,
    file_name: str,
) -> str | None:
    direct = values.get(value_name, "").strip()
    secret_path = values.get(file_name, "").strip()
    if direct and secret_path:
        raise ConfigurationError(f"set only one of {value_name} or {file_name}")
    if not secret_path:
        return _optional_secret(direct, value_name)
    try:
        with Path(secret_path).open(encoding="utf-8") as stream:
            value = stream.read(4_097)
    except OSError as exc:
        raise ConfigurationError(f"{file_name} could not be read") from exc
    return _optional_secret(value, file_name)


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
    _require_positive_finite(parsed, label)
    return parsed


def _require_positive_finite(value: float, label: str) -> None:
    if not isfinite(value) or value <= 0:
        raise ConfigurationError(f"{label} must be finite and greater than zero")


def _bounded_float(
    value: str,
    label: str,
    *,
    minimum: float,
    maximum: float,
) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ConfigurationError(f"{label} must be numeric") from exc
    if not minimum <= parsed <= maximum:
        raise ConfigurationError(f"{label} must be between {minimum:g} and {maximum:g}")
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


def _corpus_scopes(value: str) -> tuple[tuple[str, str], ...]:
    scopes: dict[str, str] = {}
    for item in value.split(",") if value.strip() else ():
        parts = item.strip().split(":")
        if len(parts) != 2 or not all(_identifier(part) for part in parts):
            raise ConfigurationError("AI_MODE_RAG_CORPORA must contain feature:corpus pairs")
        feature, corpus = parts
        if feature in scopes:
            raise ConfigurationError("Only one default corpus is permitted per feature")
        scopes[feature] = corpus
    return tuple(scopes.items())


def _identifier(value: str) -> bool:
    return (
        bool(value)
        and len(value) <= 100
        and value[0].isalnum()
        and all(
            character.islower() or character.isdigit() or character in "._-" for character in value
        )
    )
