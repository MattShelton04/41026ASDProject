"""Validated loader for the versioned AI-mode model registry."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from shared_contracts import ModelRegistry

DEFAULT_MODEL_REGISTRY_PATH = Path(__file__).resolve().parent / "model_assets" / "registry.v2.yaml"


class ModelRegistryError(ValueError):
    """The configured registry is missing, malformed, or internally inconsistent."""


def load_model_registry(path: Path | None = None) -> ModelRegistry:
    """Read and strictly validate a registry document without network access."""
    registry_path = (path or DEFAULT_MODEL_REGISTRY_PATH).resolve()
    try:
        raw = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
        return ModelRegistry.model_validate(raw)
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise ModelRegistryError(f"could not load model registry: {registry_path}") from exc
