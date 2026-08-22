"""Composition tests for provider-specific registry profiles and API styles."""

import pytest

from ai_mode.configuration import ConfigurationError, Settings
from ai_mode.providers import build_provider, configured_model_registry


def test_gemini_profile_builds_chat_completions_provider() -> None:
    settings = Settings.from_env(
        {
            "AI_MODE_LLM_PROVIDER": "gemini",
            "GEMINI_API_KEY": "test-key",
            "AI_MODE_DEFAULT_MODEL_PROFILE": "gemini-development.v1",
        }
    )
    registry, default_profile = configured_model_registry(settings)

    provider = build_provider(
        settings,
        registry=registry,
        readiness_profile=default_profile,
    )

    assert provider._provider_name == "gemini"  # type: ignore[attr-defined]
    assert provider._api_style == "chat_completions"  # type: ignore[attr-defined]
    assert set(provider._profiles) == {  # type: ignore[attr-defined]
        "gemini-development.v1",
        "gemini-quality.v1",
    }
    provider.close()  # type: ignore[attr-defined]


def test_configured_provider_rejects_a_profile_owned_by_another_provider() -> None:
    settings = Settings.from_env(
        {
            "AI_MODE_LLM_PROVIDER": "gemini",
            "GEMINI_API_KEY": "test-key",
            "AI_MODE_DEFAULT_MODEL_PROFILE": "remote-standard.v1",
        }
    )

    with pytest.raises(ConfigurationError, match="does not use the configured gemini provider"):
        build_provider(settings)
