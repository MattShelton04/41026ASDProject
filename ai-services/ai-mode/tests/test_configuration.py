"""Tests for strict service configuration and bounded secret loading."""

from pathlib import Path

import pytest

from ai_mode.configuration import (
    DEFAULT_MAX_REQUEST_BYTES,
    DEFAULT_QUEUE_CAPACITY,
    ConfigurationError,
    Settings,
)


def test_defaults_have_one_typed_runtime_source() -> None:
    settings = Settings.from_env({})

    assert settings.max_request_bytes == DEFAULT_MAX_REQUEST_BYTES
    assert settings.queue_capacity == DEFAULT_QUEUE_CAPACITY
    assert settings.environment == "local"
    assert settings.log_level == "INFO"
    assert settings.operations_enabled is False
    assert settings.llm_provider == "openai"
    assert settings.openai_base_url == "https://api.openai.com/v1"
    assert settings.openai_api_key is None
    assert settings.gemini_base_url == ("https://generativelanguage.googleapis.com/v1beta/openai")
    assert settings.gemini_api_key is None
    assert settings.openai_prompt_cache_enabled is True
    assert settings.openai_allow_insecure_http is False
    assert settings.openai_health_cache_seconds == 60


def test_direct_settings_construction_preserves_finite_timing_invariants() -> None:
    with pytest.raises(ConfigurationError, match="OpenAI timeout must be finite"):
        Settings(openai_timeout_seconds=float("inf"))
    with pytest.raises(ConfigurationError, match="OpenAI health timeout must be finite"):
        Settings(openai_health_timeout_seconds=float("nan"))
    with pytest.raises(ConfigurationError, match="queue reconcile interval must be finite"):
        Settings(queue_reconcile_interval_seconds=float("inf"))


def test_openai_configuration_accepts_a_loopback_compatible_api() -> None:
    settings = Settings.from_env(
        {
            "OPENAI_BASE_URL": "http://localhost:8080/v1/",
            "OPENAI_API_KEY": "test-secret",
            "AI_MODE_DEFAULT_MODEL_PROFILE": "remote-standard.v1",
        }
    )

    assert settings.openai_base_url == "http://localhost:8080/v1"
    assert settings.openai_api_key == "test-secret"
    assert settings.default_model_profile == "remote-standard.v1"
    assert "test-secret" not in repr(settings)


def test_openai_configuration_reads_a_bounded_secret_file(tmp_path: Path) -> None:
    secret_path = tmp_path / "openai-key"
    secret_path.write_text("file-secret\n", encoding="utf-8")

    settings = Settings.from_env({"OPENAI_API_KEY_FILE": str(secret_path)})

    assert settings.openai_api_key == "file-secret"
    assert "file-secret" not in repr(settings)


def test_gemini_configuration_uses_its_compatible_endpoint_and_secret() -> None:
    settings = Settings.from_env(
        {
            "AI_MODE_LLM_PROVIDER": "gemini",
            "GEMINI_API_KEY": "gemini-secret",
            "AI_MODE_DEFAULT_MODEL_PROFILE": "gemini-development.v1",
        }
    )

    assert settings.llm_provider == "gemini"
    assert settings.gemini_api_key == "gemini-secret"
    assert settings.gemini_base_url.endswith("/v1beta/openai")
    assert settings.default_model_profile == "gemini-development.v1"
    assert "gemini-secret" not in repr(settings)


def test_non_loopback_http_requires_an_explicit_local_development_opt_in() -> None:
    settings = Settings.from_env(
        {
            "OPENAI_BASE_URL": "http://host.docker.internal:8080/v1",
            "OPENAI_ALLOW_INSECURE_HTTP": "true",
        }
    )

    assert settings.openai_allow_insecure_http is True


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"AI_MODE_LLM_PROVIDER": "unknown"}, "must be one of"),
        ({"OPENAI_BASE_URL": "file:///tmp/model"}, "absolute http or https"),
        ({"OPENAI_BASE_URL": "http://api.example.com/v1"}, "must use https"),
        ({"OPENAI_BASE_URL": "https://user:password@example.com/v1"}, "credentials"),
        ({"GEMINI_BASE_URL": "file:///tmp/model"}, "GEMINI_BASE_URL must be an absolute"),
        ({"OPENAI_TIMEOUT_SECONDS": "0"}, "greater than zero"),
        ({"OPENAI_TIMEOUT_SECONDS": "nan"}, "finite and greater than zero"),
        ({"OPENAI_TIMEOUT_SECONDS": "inf"}, "finite and greater than zero"),
        ({"OPENAI_TIMEOUT_SECONDS": "slow"}, "must be numeric"),
        ({"OPENAI_HEALTH_TIMEOUT_SECONDS": "0"}, "greater than zero"),
        ({"OPENAI_HEALTH_TIMEOUT_SECONDS": "nan"}, "finite and greater than zero"),
        ({"OPENAI_HEALTH_TIMEOUT_SECONDS": "inf"}, "finite and greater than zero"),
        ({"OPENAI_HEALTH_CACHE_SECONDS": "0"}, "must be between"),
        ({"OPENAI_PROMPT_CACHE_ENABLED": "sometimes"}, "must be true or false"),
        ({"OPENAI_ALLOW_INSECURE_HTTP": "sometimes"}, "must be true or false"),
        ({"OPENAI_MAX_RETRIES": "6"}, "must be between"),
        ({"OPENAI_MAX_RETRIES": "many"}, "must be an integer"),
        ({"OPENAI_API_KEY": "bad\nkey"}, "OPENAI_API_KEY is invalid"),
        (
            {"OPENAI_API_KEY": "direct", "OPENAI_API_KEY_FILE": "/run/secrets/key"},
            "set only one",
        ),
        ({"OPENAI_API_KEY_FILE": "/missing/openai-key"}, "could not be read"),
        (
            {"AI_MODE_LLM_PROVIDER": "gemini", "GEMINI_API_KEY": "bad\nkey"},
            "GEMINI_API_KEY is invalid",
        ),
        ({"AI_MODE_MAX_MODEL_RESPONSE_BYTES": "10"}, "must be between"),
        ({"AI_MODE_MAX_MODEL_RESPONSE_BYTES": "many"}, "must be an integer"),
        ({"AI_MODE_MAX_REQUEST_BYTES": "10"}, "must be between"),
        ({"AI_MODE_MAX_TOOL_REQUEST_BYTES": "10"}, "must be between"),
        ({"AI_MODE_MAX_TOOL_RESPONSE_BYTES": "many"}, "must be an integer"),
        ({"AI_MODE_EVIDENCE_ACCESS_TOKEN": "short"}, "at least 16"),
        ({"AI_MODE_DEFAULT_MODEL_PROFILE": "Not Valid"}, "is invalid"),
        ({"AI_MODE_REQUIRE_PROVIDER_READY": "sometimes"}, "must be true or false"),
        ({"AI_MODE_QUEUE_CAPACITY": "0"}, "queue capacity must be between"),
        ({"AI_MODE_QUEUE_RECONCILE_INTERVAL_SECONDS": "0"}, "greater than zero"),
        (
            {"AI_MODE_QUEUE_RECONCILE_INTERVAL_SECONDS": "nan"},
            "finite and greater than zero",
        ),
        (
            {"AI_MODE_QUEUE_RECONCILE_INTERVAL_SECONDS": "inf"},
            "finite and greater than zero",
        ),
        ({"AI_MODE_ENVIRONMENT": "Not Valid"}, "AI_MODE_ENVIRONMENT is invalid"),
        ({"AI_MODE_ENVIRONMENT": ""}, "AI_MODE_ENVIRONMENT is invalid"),
        ({"AI_MODE_LOG_LEVEL": "verbose"}, "AI_MODE_LOG_LEVEL must be"),
        ({"AI_MODE_OPERATIONS_ENABLED": "sometimes"}, "must be true or false"),
    ],
)
def test_invalid_settings_fail_fast(values: dict[str, str], message: str) -> None:
    with pytest.raises(ConfigurationError, match=message):
        Settings.from_env(values)


@pytest.mark.parametrize(("value", "expected"), [("true", True), ("0", False)])
def test_strict_provider_readiness_is_explicitly_configured(
    value: str,
    expected: bool,
) -> None:
    settings = Settings.from_env({"AI_MODE_REQUIRE_PROVIDER_READY": value})

    assert settings.require_provider_ready is expected


def test_operations_interface_is_explicitly_enabled() -> None:
    settings = Settings.from_env({"AI_MODE_OPERATIONS_ENABLED": "true"})

    assert settings.operations_enabled is True


def test_multiple_tool_catalog_paths_are_ordered_and_trimmed() -> None:
    settings = Settings.from_env(
        {"AI_MODE_TOOL_CATALOG_PATHS": "feature-one.yaml, fixtures/tools.yaml"}
    )

    assert settings.configured_tool_catalog_paths == (
        Path("feature-one.yaml"),
        Path("fixtures/tools.yaml"),
    )


def test_legacy_single_tool_catalog_path_remains_supported() -> None:
    settings = Settings.from_env({"AI_MODE_TOOL_CATALOG_PATH": "feature.yaml"})

    assert settings.tool_catalog_path == Path("feature.yaml")
    assert settings.configured_tool_catalog_paths == (Path("feature.yaml"),)


@pytest.mark.parametrize(
    ("values", "message"),
    [
        (
            {
                "AI_MODE_TOOL_CATALOG_PATH": "one.yaml",
                "AI_MODE_TOOL_CATALOG_PATHS": "two.yaml,three.yaml",
            },
            "set only one",
        ),
        ({"AI_MODE_TOOL_CATALOG_PATHS": "one.yaml,"}, "empty path"),
        ({"AI_MODE_TOOL_CATALOG_PATHS": "one.yaml,one.yaml"}, "duplicates"),
    ],
)
def test_invalid_multi_catalog_settings_fail_fast(values: dict[str, str], message: str) -> None:
    with pytest.raises(ConfigurationError, match=message):
        Settings.from_env(values)


def test_local_compose_allows_only_the_registered_shared_service_origins() -> None:
    settings = Settings.from_env(
        {
            "AI_MODE_ENVIRONMENT": "compose",
            "AI_MODE_MCP_ENABLED": "true",
            "AI_MODE_RAG_ENABLED": "true",
            "MCP_SERVICE_TOKEN": "m" * 32,
            "RAG_SERVICE_TOKEN": "r" * 32,
            "MCP_SERVER_URL": "http://mcp-server:5011/mcp",
            "RAG_SERVER_URL": "http://rag-server:5012",
        }
    )
    assert settings.mcp_enabled and settings.rag_enabled


@pytest.mark.parametrize(
    ("environment", "name", "url"),
    [
        ("local", "MCP_SERVER_URL", "http://mcp-server:5011/mcp"),
        ("local", "RAG_SERVER_URL", "http://rag-server:5012"),
        ("compose", "MCP_SERVER_URL", "http://rag-server:5012"),
        ("compose", "RAG_SERVER_URL", "http://mcp-server:5011/mcp"),
        ("compose", "MCP_SERVER_URL", "http://mcp-server:5012/mcp"),
        ("compose", "MCP_SERVER_URL", "http://mcp-server:5011/other"),
        ("compose", "RAG_SERVER_URL", "http://rag-server:5012?token=x"),
        ("compose", "RAG_SERVER_URL", "http://rag-server.attacker.test:5012"),
    ],
)
def test_compose_service_url_exception_does_not_expand_other_boundaries(
    environment: str, name: str, url: str
) -> None:
    with pytest.raises(ConfigurationError, match="Shared MCP/RAG URLs"):
        Settings.from_env({"AI_MODE_ENVIRONMENT": environment, name: url})
