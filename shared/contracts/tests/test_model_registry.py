"""Tests for the public supported-model registry contract."""

import pytest
from pydantic import ValidationError

from shared_contracts import ModelRegistry


def _registry() -> dict[str, object]:
    return {
        "schema_version": 1,
        "default_profile": "local-small.v1",
        "models": [
            {
                "key": "qwen-test",
                "family": "qwen",
                "provider": "ollama",
                "ollama_tag": "qwen:test",
                "parameters_billion": 0.5,
                "download_size_gb": 0.4,
                "maximum_context_tokens": 8192,
                "source_url": "https://ollama.com/library/qwen",
                "description": "Test model",
            }
        ],
        "profiles": [
            {
                "key": "local-small.v1",
                "model_key": "qwen-test",
                "context_tokens": 4096,
                "maximum_output_tokens": 512,
                "keep_alive": "5m",
                "intended_roles": ["planner", "adapter"],
                "description": "Test profile",
            }
        ],
    }


def test_registry_resolves_models_and_profiles() -> None:
    registry = ModelRegistry.model_validate(_registry())

    assert registry.profile("local-small.v1") is not None
    assert registry.model("qwen-test") is not None
    assert registry.profile("missing") is None


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update(default_profile="missing.v1"), "default model profile"),
        (
            lambda value: value["profiles"][0].update(model_key="missing"),  # type: ignore[index,union-attr]
            "unknown model",
        ),
        (
            lambda value: value["profiles"][0].update(context_tokens=16384),  # type: ignore[index,union-attr]
            "exceeds the model context",
        ),
    ],
)
def test_registry_rejects_inconsistent_references(
    mutation: object,
    message: str,
) -> None:
    raw = _registry()
    assert callable(mutation)
    mutation(raw)

    with pytest.raises(ValidationError, match=message):
        ModelRegistry.model_validate(raw)
