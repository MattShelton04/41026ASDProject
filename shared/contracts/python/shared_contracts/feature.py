"""Validated feature discovery metadata used by shared integration services."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import Field, model_validator

from shared_contracts.agent import Identifier
from shared_contracts.base import ContractModel
from shared_contracts.deployment import FeatureOnboarding


class FeatureManifestError(ValueError):
    """A feature manifest set is missing, malformed, or internally inconsistent."""


class FeatureManifest(ContractModel):
    """Domain-neutral metadata owned by one student feature slice."""

    schema_version: Literal[1] = 1
    feature_key: Identifier
    display_name: str = Field(min_length=1, max_length=100)
    owner: Literal["student-1", "student-2", "student-3", "student-4", "student-5"]
    frontend_base_path: str = Field(min_length=2, max_length=200)
    backend_base_path: str = Field(min_length=2, max_length=200)
    health_path: str = Field(min_length=2, max_length=200)
    ai_capabilities: tuple[Identifier, ...] = Field(default=(), max_length=50)
    onboarding: FeatureOnboarding | None = None

    @model_validator(mode="after")
    def validate_identity_and_paths(self) -> FeatureManifest:
        """Reject owner mismatches and paths that could escape same-origin routing."""
        if not self.feature_key.startswith(f"{self.owner}-"):
            raise ValueError("feature_key must start with the owning student identifier")
        for field_name in ("frontend_base_path", "backend_base_path", "health_path"):
            value = getattr(self, field_name)
            _validate_route_path(field_name, value)
        if len(set(self.ai_capabilities)) != len(self.ai_capabilities):
            raise ValueError("ai_capabilities must not contain duplicates")
        return self


def load_feature_manifest(path: Path) -> FeatureManifest:
    """Load one YAML manifest and wrap parser/validation errors with its path."""
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise FeatureManifestError(f"could not read feature manifest {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise FeatureManifestError(f"feature manifest {path} must contain a YAML object")
    try:
        return FeatureManifest.model_validate(payload)
    except ValueError as exc:
        raise FeatureManifestError(f"invalid feature manifest {path}: {exc}") from exc


def load_feature_manifests(paths: Iterable[Path]) -> tuple[FeatureManifest, ...]:
    """Load a deterministic manifest set and reject duplicate identities or routes."""
    manifests = tuple(load_feature_manifest(path) for path in sorted(paths))
    seen: dict[tuple[str, str], str] = {}
    for manifest in manifests:
        unique_values = {
            "feature_key": manifest.feature_key,
            "owner": manifest.owner,
            "frontend_base_path": manifest.frontend_base_path,
            "backend_base_path": manifest.backend_base_path,
        }
        for kind, value in unique_values.items():
            key = (kind, value)
            if key in seen:
                raise FeatureManifestError(
                    f"duplicate {kind} {value!r} in {seen[key]} and {manifest.feature_key}"
                )
            seen[key] = manifest.feature_key
    return tuple(sorted(manifests, key=lambda item: item.owner))


def _validate_route_path(field_name: str, value: str) -> None:
    if not value.startswith("/") or value.startswith("//"):
        raise ValueError(f"{field_name} must be an absolute same-origin path")
    if any(character in value for character in ("?", "#", "\\")):
        raise ValueError(f"{field_name} cannot contain a query, fragment, or backslash")
    if ".." in PurePosixPath(value).parts:
        raise ValueError(f"{field_name} cannot traverse parent paths")
