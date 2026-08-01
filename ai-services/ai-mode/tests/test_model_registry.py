"""Tests for loading the versioned model registry asset."""

from pathlib import Path

import pytest

from ai_mode.model_registry import ModelRegistryError, load_model_registry


def test_bundled_registry_has_assignment_approved_families_and_bounded_profiles() -> None:
    registry = load_model_registry()

    assert {model.family.value for model in registry.models} == {
        "qwen",
        "llama",
        "deepseek",
    }
    assert registry.profile(registry.default_profile) is not None
    assert all(
        profile.context_tokens <= registry.model(profile.model_key).maximum_context_tokens  # type: ignore[union-attr]
        for profile in registry.profiles
    )


def test_invalid_registry_is_reported_with_its_path(tmp_path: Path) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text("schema_version: 9\n", encoding="utf-8")

    with pytest.raises(ModelRegistryError, match=r"invalid\.yaml"):
        load_model_registry(path)
