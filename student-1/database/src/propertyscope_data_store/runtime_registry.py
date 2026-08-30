"""Typed runtime versions derived from Feature 1's reviewed job profiles.

The database service owns this projection because it is the authority that persists
the immutable runtime snapshot on a job and its runs.  The declarative job-profile
documents are the service boundary: the database package deliberately does not
import the backend package that also validates those documents against executable
adapters and release builders.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

RuntimeComponentKind = Literal["adapter", "release_builder", "import_profile", "quality_policy"]
_QUALITY_POLICY = re.compile(r"^(?P<key>[a-z][a-z0-9-]{0,99})\.v(?P<major>[1-9][0-9]*)$")


class RuntimeRegistryError(ValueError):
    """The checked-in runtime configuration is absent, invalid, or contradictory."""


class _VersionedComponentDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    key: str = Field(pattern=r"^[a-z][a-z0-9-]{0,99}$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$", max_length=30)


class _RuntimeProfileDocument(BaseModel):
    """Persistence-relevant subset of the feature-owned job-profile contract."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    schema_version: Literal["propertyscope.job-profile.v1"]
    key: str = Field(pattern=r"^[a-z][a-z0-9-]{0,99}$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$", max_length=30)
    adapter: _VersionedComponentDocument
    release_builder: _VersionedComponentDocument
    import_profile: _VersionedComponentDocument
    quality_policy: str = Field(pattern=r"^[a-z][a-z0-9-]{0,99}\.v[1-9][0-9]*$")


@dataclass(frozen=True, slots=True)
class RuntimeComponent:
    """A closed runtime implementation reference persisted with durable work."""

    key: str
    version: str


@dataclass(frozen=True, slots=True)
class RuntimeProfile:
    """All versioned runtime choices controlled by one registered job profile."""

    key: str
    version: str
    adapter: RuntimeComponent
    release_builder: RuntimeComponent
    import_profile: RuntimeComponent
    quality_policy: RuntimeComponent


class RuntimeRegistry:
    """Immutable profile registry that rejects ambiguous component versions."""

    def __init__(self, profiles: Iterable[RuntimeProfile], *, maximum: int = 100) -> None:
        items = tuple(profiles)
        if not items:
            raise RuntimeRegistryError("runtime registry must contain at least one profile")
        if len(items) > maximum:
            raise RuntimeRegistryError(f"runtime registry exceeds maximum of {maximum} profiles")

        by_profile: dict[str, RuntimeProfile] = {}
        component_versions: dict[tuple[RuntimeComponentKind, str], str] = {}
        for profile in items:
            if profile.key in by_profile:
                raise RuntimeRegistryError(f"duplicate runtime profile: {profile.key}")
            by_profile[profile.key] = profile
            components: tuple[tuple[RuntimeComponentKind, RuntimeComponent], ...] = (
                ("adapter", profile.adapter),
                ("release_builder", profile.release_builder),
                ("import_profile", profile.import_profile),
                ("quality_policy", profile.quality_policy),
            )
            for kind, component in components:
                identity = (kind, component.key)
                registered = component_versions.setdefault(identity, component.version)
                if registered != component.version:
                    raise RuntimeRegistryError(
                        f"conflicting {kind} versions for {component.key}: "
                        f"{registered} and {component.version}"
                    )

        self._profiles: Mapping[str, RuntimeProfile] = MappingProxyType(by_profile)
        self._component_versions: Mapping[tuple[RuntimeComponentKind, str], str] = MappingProxyType(
            component_versions
        )

    def profile(self, key: str) -> RuntimeProfile:
        """Resolve one exact profile or fail closed."""
        try:
            return self._profiles[key]
        except KeyError as exc:
            raise RuntimeRegistryError(f"unknown runtime profile: {key}") from exc

    def component_version(self, kind: RuntimeComponentKind, key: str) -> str:
        """Expose the single version registered for a component identity."""
        try:
            return self._component_versions[(kind, key)]
        except KeyError as exc:
            raise RuntimeRegistryError(f"unknown registered {kind}: {key}") from exc

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._profiles))

    def __iter__(self) -> Iterator[str]:
        return iter(self.keys())


def load_runtime_registry(path: Path) -> RuntimeRegistry:
    """Load the persistence projection from one job-profile file or directory."""
    files = (path,) if path.is_file() else tuple(sorted(path.glob("*.yaml")))
    profiles: list[RuntimeProfile] = []
    for file in files:
        try:
            payload: Any = yaml.safe_load(file.read_text(encoding="utf-8"))
            if not isinstance(payload, Mapping):
                raise RuntimeRegistryError("job profile must be a YAML object")
            document = _RuntimeProfileDocument.model_validate(payload)
            profiles.append(_runtime_profile(document))
        except (OSError, yaml.YAMLError, ValidationError, RuntimeRegistryError) as exc:
            raise RuntimeRegistryError(f"invalid runtime profile {file}: {exc}") from exc
    if not files:
        raise RuntimeRegistryError(f"no runtime profiles found at {path}")
    return RuntimeRegistry(profiles)


def _runtime_profile(document: _RuntimeProfileDocument) -> RuntimeProfile:
    match = _QUALITY_POLICY.fullmatch(document.quality_policy)
    if match is None:  # Kept defensive if the document pattern changes independently.
        raise RuntimeRegistryError("quality policy must use the <key>.v<major> form")
    return RuntimeProfile(
        key=document.key,
        version=document.version,
        adapter=RuntimeComponent(document.adapter.key, document.adapter.version),
        release_builder=RuntimeComponent(
            document.release_builder.key, document.release_builder.version
        ),
        import_profile=RuntimeComponent(
            document.import_profile.key, document.import_profile.version
        ),
        quality_policy=RuntimeComponent(document.quality_policy, f"{match.group('major')}.0.0"),
    )
