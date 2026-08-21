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
    if settings.llm_provider != ModelProviderName.OPENAI.value:
        raise ConfigurationError(f"unsupported LLM provider: {settings.llm_provider}")
    profiles: dict[str, OpenAIModelProfile] = {}
    for profile in registry.profiles:
        role_models: dict[ModelRole, str] = {}
        for role, model_key in profile.role_models.items():
            model = registry.model(model_key)
            if model is None:  # Defensive: ModelRegistry validation already rejects this.
                raise ConfigurationError(f"model profile references unknown model: {profile.key}")
            if model.provider is not ModelProviderName.OPENAI:
                raise ConfigurationError(
                    f"model profile {profile.key} does not use the configured OpenAI provider"
                )
            role_models[ModelRole(role.value)] = model.model_id
        profiles[profile.key] = OpenAIModelProfile(
            models=role_models,
            maximum_output_tokens=profile.maximum_output_tokens,
            reasoning_effort=profile.reasoning_effort,
        )
    return OpenAIProvider(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        profiles=profiles,
        readiness_profiles=frozenset({readiness_profile}),
        timeout_seconds=settings.openai_timeout_seconds,
        health_timeout_seconds=settings.openai_health_timeout_seconds,
        max_retries=settings.openai_max_retries,
        max_response_bytes=settings.max_model_response_bytes,
    )
