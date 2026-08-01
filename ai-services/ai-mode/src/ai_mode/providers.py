"""Central composition of logical model profiles and concrete providers."""

from ai_mode.adapters.ollama import OllamaModelProfile, OllamaProvider
from ai_mode.configuration import Settings

PRIMARY_MODEL_PROFILE = "local-small.v1"


def build_ollama_provider(settings: Settings) -> OllamaProvider:
    """Build the production provider used by the service and runtime diagnostics."""
    return OllamaProvider(
        base_url=settings.ollama_base_url,
        profiles={
            PRIMARY_MODEL_PROFILE: OllamaModelProfile(
                model=settings.ollama_model,
                keep_alive=settings.ollama_keep_alive,
            )
        },
        timeout_seconds=settings.ollama_timeout_seconds,
        health_timeout_seconds=settings.ollama_health_timeout_seconds,
        max_response_bytes=settings.max_model_response_bytes,
    )
