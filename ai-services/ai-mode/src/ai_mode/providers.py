"""Central composition of logical model profiles and concrete providers."""

from agent_core import LLMProvider, ModelRole
from ai_mode.adapters.openai import OpenAIModelProfile, OpenAIProvider
from ai_mode.configuration import ConfigurationError, Settings
from ai_mode.model_registry import load_model_registry
from shared_contracts import ModelProviderName, ModelRegistry


def configured_model_registry(settings: Settings) -> tuple[ModelRegistry, str]:
    """Load the registry and resolve the one profile required for readiness."""
    registry = load_model_registry(settings.model_registry_path)
    default_profile = settings.default_model_profile or registry.default_profile
    if registry.profile(default_profile) is None:
        raise ConfigurationError(
            f"AI_MODE_DEFAULT_MODEL_PROFILE is not registered: {default_profile}"
        )
    return registry, default_profile


def build_provider(
    settings: Settings,
    *,
    registry: ModelRegistry | None = None,
    readiness_profile: str | None = None,
) -> LLMProvider:
    """Build the configured production provider used by the service and diagnostics."""
    if registry is None or readiness_profile is None:
        registry, readiness_profile = configured_model_registry(settings)
    provider_name = ModelProviderName(settings.llm_provider)
    default = registry.profile(readiness_profile)
    if default is None:  # Defensive: configured_model_registry already validates this.
        raise ConfigurationError(f"unknown readiness profile: {readiness_profile}")
    default_providers = {
        registry.model(model_key).provider  # type: ignore[union-attr]
        for model_key in default.role_models.values()
    }
    if default_providers != {provider_name}:
        raise ConfigurationError(
            f"model profile {readiness_profile} does not use the configured "
            f"{provider_name.value} provider"
        )
    profiles: dict[str, OpenAIModelProfile] = {}
    for profile in registry.profiles:
        role_models: dict[ModelRole, str] = {}
        for role, model_key in profile.role_models.items():
            model = registry.model(model_key)
            if model is None:  # Defensive: ModelRegistry validation already rejects this.
                raise ConfigurationError(f"model profile references unknown model: {profile.key}")
            if model.provider is not provider_name:
                role_models = {}
                break
            role_models[ModelRole(role.value)] = model.model_id
        if not role_models:
            continue
        profiles[profile.key] = OpenAIModelProfile(
            models=role_models,
            context_tokens=profile.context_tokens,
            maximum_output_tokens=profile.maximum_output_tokens,
            reasoning_effort=profile.reasoning_effort,
        )
    return OpenAIProvider(
        api_key=(
            settings.gemini_api_key
            if provider_name is ModelProviderName.GEMINI
            else settings.openai_api_key
        ),
        base_url=(
            settings.gemini_base_url
            if provider_name is ModelProviderName.GEMINI
            else settings.openai_base_url
        ),
        provider_name=provider_name.value,
        api_style="chat_completions" if provider_name is ModelProviderName.GEMINI else "responses",
        profiles=profiles,
        readiness_profiles=frozenset({readiness_profile}),
        timeout_seconds=settings.openai_timeout_seconds,
        health_timeout_seconds=settings.openai_health_timeout_seconds,
        health_cache_seconds=settings.openai_health_cache_seconds,
        max_retries=settings.openai_max_retries,
        max_response_bytes=settings.max_model_response_bytes,
        prompt_cache_enabled=(
            settings.openai_prompt_cache_enabled
            if provider_name is ModelProviderName.OPENAI
            else False
        ),
    )
