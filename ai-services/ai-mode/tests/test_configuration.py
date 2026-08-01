"""Tests for strict, side-effect-free service configuration."""

import pytest

from ai_mode.configuration import ConfigurationError, Settings


def test_course_openai_compatible_url_is_normalized_for_native_ollama_api() -> None:
    settings = Settings.from_env(
        {
            "OLLAMA_BASE_URL": "http://localhost:11434/v1",
            "OLLAMA_MODEL": "qwen2.5:0.5b",
        }
    )

    assert settings.ollama_base_url == "http://localhost:11434"
    assert settings.ollama_model == "qwen2.5:0.5b"


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
        ({"OLLAMA_MODEL": " "}, "cannot be empty"),
        ({"OLLAMA_KEEP_ALIVE": " "}, "cannot be empty"),
        ({"AI_MODE_REQUIRE_OLLAMA_READY": "sometimes"}, "must be true or false"),
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
