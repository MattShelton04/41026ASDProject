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
    assert settings.openai_prompt_cache_enabled is True
    assert settings.openai_allow_insecure_http is False
    assert settings.openai_health_cache_seconds == 60


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
        ({"OPENAI_TIMEOUT_SECONDS": "0"}, "greater than zero"),
        ({"OPENAI_TIMEOUT_SECONDS": "slow"}, "must be numeric"),
        ({"OPENAI_HEALTH_TIMEOUT_SECONDS": "0"}, "greater than zero"),
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
