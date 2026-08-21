"""Tests for the public supported-model registry contract."""

import pytest
from pydantic import ValidationError

from shared_contracts import ModelRegistry, ModelRoleName


def _registry() -> dict[str, object]:
    return {
        "schema_version": 2,
        "default_profile": "remote-standard.v1",
        "models": [
            {
                "key": "gpt-5.6-luna",
                "provider": "openai",
                "model_id": "gpt-5.6-luna",
                "maximum_context_tokens": 1_050_000,
                "maximum_output_tokens": 128_000,
                "source_url": "https://developers.openai.com/api/docs/models/gpt-5.6-luna",
                "description": "Test model",
            }
        ],
        "profiles": [
            {
                "key": "remote-standard.v1",
                "role_models": {
                    "planner": "gpt-5.6-luna",
                    "adapter": "gpt-5.6-luna",
                },
                "context_tokens": 16_384,
                "maximum_output_tokens": 2_048,
                "reasoning_effort": "low",
                "description": "Test profile",
            }
        ],
    }


def test_registry_resolves_models_and_profiles() -> None:
    registry = ModelRegistry.model_validate(_registry())

    assert registry.profile("remote-standard.v1") is not None
    assert registry.model("gpt-5.6-luna") is not None
    assert registry.profile("missing") is None


def test_profile_reports_supported_role_sets() -> None:
    profile = ModelRegistry.model_validate(_registry()).profiles[0]

    assert profile.supports(ModelRoleName.PLANNER)
    assert profile.supports(ModelRoleName.PLANNER, ModelRoleName.ADAPTER)
    assert not profile.supports(ModelRoleName.REVIEWER)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update(default_profile="missing.v1"), "default model profile"),
        (
            lambda value: value["profiles"][0].update(role_models={"planner": "missing"}),  # type: ignore[index,union-attr]
            "unknown model",
        ),
        (
            lambda value: value["profiles"][0].update(context_tokens=1_050_001),  # type: ignore[index,union-attr]
            "exceeds the model context",
        ),
        (
            lambda value: value["models"][0].update(maximum_output_tokens=2_047),  # type: ignore[index,union-attr]
            "exceeds the model output",
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
