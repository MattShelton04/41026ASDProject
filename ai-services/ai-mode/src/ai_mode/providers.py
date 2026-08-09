"""Central composition of logical model profiles and concrete providers."""

from agent_core import ModelRole
from ai_mode.adapters.ollama import OllamaModelProfile, OllamaProvider
from ai_mode.configuration import ConfigurationError, Settings
from ai_mode.model_registry import load_model_registry
from shared_contracts import ModelRegistry


def configured_model_registry(settings: Settings) -> tuple[ModelRegistry, str]:
    """Load the registry and resolve the one profile required for readiness."""
    registry = load_model_registry(settings.model_registry_path)
    default_profile = settings.default_model_profile or registry.default_profile
    if registry.profile(default_profile) is None:
        raise ConfigurationError(
            f"AI_MODE_DEFAULT_MODEL_PROFILE is not registered: {default_profile}"
        )
    return registry, default_profile


def build_ollama_provider(
    settings: Settings,
    *,
    registry: ModelRegistry | None = None,
    readiness_profile: str | None = None,
) -> OllamaProvider:
    """Build the production provider used by the service and runtime diagnostics."""
    if registry is None or readiness_profile is None:
        registry, readiness_profile = configured_model_registry(settings)
    profiles: dict[str, OllamaModelProfile] = {}
    for profile in registry.profiles:
        model = registry.model(profile.model_key)
        if model is None:  # Defensive: ModelRegistry validation already rejects this.
            raise ConfigurationError(f"model profile references unknown model: {profile.key}")
        profiles[profile.key] = OllamaModelProfile(
            model=model.ollama_tag,
            keep_alive=settings.ollama_keep_alive or profile.keep_alive,
            context_tokens=profile.context_tokens,
            maximum_output_tokens=profile.maximum_output_tokens,
            intended_roles=frozenset(ModelRole(role.value) for role in profile.intended_roles),
        )
    return OllamaProvider(
        base_url=settings.ollama_base_url,
        profiles=profiles,
        readiness_profiles=frozenset({readiness_profile}),
        timeout_seconds=settings.ollama_timeout_seconds,
        health_timeout_seconds=settings.ollama_health_timeout_seconds,
        max_response_bytes=settings.max_model_response_bytes,
    )
