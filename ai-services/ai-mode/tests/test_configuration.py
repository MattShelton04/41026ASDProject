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
        ({"AI_MODE_MAX_MODEL_RESPONSE_BYTES": "10"}, "must be between"),
        ({"AI_MODE_MAX_MODEL_RESPONSE_BYTES": "many"}, "must be an integer"),
        ({"OLLAMA_MODEL": " "}, "cannot be empty"),
        ({"OLLAMA_KEEP_ALIVE": " "}, "cannot be empty"),
    ],
)
def test_invalid_settings_fail_fast(values: dict[str, str], message: str) -> None:
    with pytest.raises(ConfigurationError, match=message):
        Settings.from_env(values)
