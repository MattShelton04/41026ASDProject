"""Tests for loading the versioned model registry asset."""

from pathlib import Path

import pytest

from ai_mode.model_registry import ModelRegistryError, load_model_registry


def test_bundled_registry_has_openai_model_and_bounded_profiles() -> None:
    registry = load_model_registry()

    assert registry.schema_version == 2
    assert {model.provider.value for model in registry.models} == {"openai"}
    assert {model.model_id for model in registry.models} == {
        "gpt-5.6-luna",
        "gpt-5.6-terra",
    }
    assert registry.profile(registry.default_profile) is not None
    assert all(profile.context_tokens == 131_072 for profile in registry.profiles)
    assert all(profile.maximum_output_tokens == 16_384 for profile in registry.profiles)
    assert all(
        profile.context_tokens <= registry.model(model_key).maximum_context_tokens  # type: ignore[union-attr]
        for profile in registry.profiles
        for model_key in profile.role_models.values()
    )


def test_invalid_registry_is_reported_with_its_path(tmp_path: Path) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text("schema_version: 9\n", encoding="utf-8")

    with pytest.raises(ModelRegistryError, match=r"invalid\.yaml"):
        load_model_registry(path)
