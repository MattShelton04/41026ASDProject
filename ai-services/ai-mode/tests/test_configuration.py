"""Tests for strict, side-effect-free service configuration."""

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


def test_course_openai_compatible_url_is_normalized_for_native_ollama_api() -> None:
    settings = Settings.from_env(
        {
            "OLLAMA_BASE_URL": "http://localhost:11434/v1",
            "AI_MODE_DEFAULT_MODEL_PROFILE": "local-balanced.v1",
        }
    )

    assert settings.ollama_base_url == "http://localhost:11434"
    assert settings.default_model_profile == "local-balanced.v1"


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"OLLAMA_BASE_URL": "file:///tmp/model"}, "must use http"),
        ({"OLLAMA_TIMEOUT_SECONDS": "0"}, "greater than zero"),
        ({"OLLAMA_TIMEOUT_SECONDS": "slow"}, "must be numeric"),
        ({"OLLAMA_HEALTH_TIMEOUT_SECONDS": "0"}, "greater than zero"),
        ({"AI_MODE_MAX_MODEL_RESPONSE_BYTES": "10"}, "must be between"),
        ({"AI_MODE_MAX_MODEL_RESPONSE_BYTES": "many"}, "must be an integer"),
        ({"AI_MODE_MAX_REQUEST_BYTES": "10"}, "must be between"),
        ({"AI_MODE_MAX_TOOL_REQUEST_BYTES": "10"}, "must be between"),
        ({"AI_MODE_MAX_TOOL_RESPONSE_BYTES": "many"}, "must be an integer"),
        ({"AI_MODE_EVIDENCE_ACCESS_TOKEN": "short"}, "at least 16"),
        ({"OLLAMA_KEEP_ALIVE": " "}, "cannot be empty"),
        ({"AI_MODE_DEFAULT_MODEL_PROFILE": "Not Valid"}, "is invalid"),
        ({"AI_MODE_REQUIRE_OLLAMA_READY": "sometimes"}, "must be true or false"),
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
def test_strict_ollama_readiness_is_explicitly_configured(
    value: str,
    expected: bool,
) -> None:
    settings = Settings.from_env({"AI_MODE_REQUIRE_OLLAMA_READY": value})

    assert settings.require_ollama_ready is expected


def test_operations_interface_is_explicitly_enabled() -> None:
    settings = Settings.from_env({"AI_MODE_OPERATIONS_ENABLED": "true"})

    assert settings.operations_enabled is True
