"""Fail fast when the bundled model registry is invalid or inconsistent."""

from __future__ import annotations

from ai_mode.model_registry import DEFAULT_MODEL_REGISTRY_PATH, load_model_registry


def main() -> int:
    """Validate the source-of-truth registry without Ollama or internet access."""
    registry = load_model_registry()
    print(
        f"Validated model registry v{registry.schema_version}: "
        f"{len(registry.models)} models, {len(registry.profiles)} profiles "
        f"({DEFAULT_MODEL_REGISTRY_PATH})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
