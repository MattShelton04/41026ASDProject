"""Closed, versioned application registries loaded from declarative YAML."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Generic, TypeVar

import yaml
from pydantic import AnyHttpUrl, Field, ValidationError

from .domain import (
    DomainModel,
    Identifier,
    RefreshStrategy,
    ResourceLimits,
    RunMode,
    TargetContract,
    VersionedKey,
)

T = TypeVar("T")


class ConfigurationError(ValueError):
    pass


class AdapterDescriptor(DomainModel):
    schema_version: str
    key: Identifier
    version: str
    publisher: str
    supported_refresh_strategies: tuple[RefreshStrategy, ...]
    supported_modes: tuple[RunMode, ...]
    partition_dimensions: tuple[Identifier, ...] = ()
    expected_media_types: tuple[str, ...]
    allowed_hosts: tuple[str, ...]
    required_secrets: tuple[Identifier, ...] = ()
    limits: ResourceLimits


class AdapterRegister(DomainModel):
    schema_version: str = Field(pattern=r"^propertyscope\.adapter-register\.v1$")
    adapters: tuple[AdapterDescriptor, ...] = Field(min_length=1, max_length=100)


class SourceRegisterEntry(DomainModel):
    key: Identifier
    display_name: str = Field(min_length=1, max_length=200)
    publisher: str = Field(min_length=1, max_length=200)
    adapter_key: Identifier
    source_url: AnyHttpUrl
    cadence: str = Field(min_length=1, max_length=100)
    licence_id: Identifier
    licence_url: AnyHttpUrl
    redistribution_policy: Identifier
    catalogue_status: str = Field(
        pattern=r"^(catalogued|fixture_backed|executable_cached|executable_live|blocked|deferred)$"
    )
    target_features: tuple[Identifier, ...] = Field(min_length=1, max_length=5)


class SourceRegister(DomainModel):
    schema_version: str = Field(pattern=r"^propertyscope\.source-register\.v1$")
    sources: tuple[SourceRegisterEntry, ...] = Field(min_length=1, max_length=100)


class JobProfile(DomainModel):
    schema_version: str
    key: Identifier
    version: str = "1.0.0"
    display_name: str
    source_key: Identifier
    adapter: VersionedKey
    refresh_strategy: RefreshStrategy
    supported_modes: tuple[RunMode, ...]
    release_builder: VersionedKey
    import_profile: VersionedKey
    target: TargetContract
    scope_profiles: dict[Identifier, dict[str, object]]
    quality_policy: Identifier
    limits: ResourceLimits
    publication: str


class Registry(Generic[T]):  # noqa: UP046
    """Immutable bounded key registry; callers cannot select modules or commands."""

    def __init__(self, values: Iterable[T], *, maximum: int = 100) -> None:
        items = tuple(values)
        if len(items) > maximum:
            raise ConfigurationError(f"registry exceeds maximum of {maximum} entries")
        mapping: dict[str, T] = {}
        for item in items:
            key = getattr(item, "key", None)
            if not isinstance(key, str):
                raise ConfigurationError("registry values must expose a string key")
            if key in mapping:
                raise ConfigurationError(f"duplicate registry key: {key}")
            mapping[key] = item
        self._values: Mapping[str, T] = MappingProxyType(mapping)

    def get_profile(self, key: str) -> T:
        try:
            return self._values[key]
        except KeyError as exc:
            raise ConfigurationError(f"unknown registered key: {key}") from exc

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._values))

    def __iter__(self) -> Iterator[str]:
        return iter(self.keys())

    def __len__(self) -> int:
        return len(self._values)


def get_profile(registry: Registry[T], key: str) -> T:  # noqa: UP047
    return registry.get_profile(key)


def load_job_profiles(path: Path) -> Registry[JobProfile]:
    files = (path,) if path.is_file() else tuple(sorted(path.glob("*.yaml")))
    profiles: list[JobProfile] = []
    for file in files:
        try:
            payload = yaml.safe_load(file.read_text(encoding="utf-8"))
            profiles.append(JobProfile.model_validate(payload))
        except (OSError, yaml.YAMLError, ValidationError) as exc:
            raise ConfigurationError(f"invalid job profile {file}: {exc}") from exc
    if not profiles:
        raise ConfigurationError(f"no job profiles found at {path}")
    return Registry(profiles)


def load_source_register(path: Path) -> Registry[SourceRegisterEntry]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        register = SourceRegister.model_validate(payload)
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise ConfigurationError(f"invalid source register {path}: {exc}") from exc
    return Registry(register.sources)


def load_adapter_register(path: Path) -> Registry[AdapterDescriptor]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        register = AdapterRegister.model_validate(payload)
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise ConfigurationError(f"invalid adapter register {path}: {exc}") from exc
    return Registry(register.adapters)


def validate_job_profile(
    profile: JobProfile,
    *,
    sources: Registry[SourceRegisterEntry],
    adapters: Registry[AdapterDescriptor],
) -> None:
    """Cross-check one job against closed source and adapter capability registries."""
    source = sources.get_profile(profile.source_key)
    adapter = adapters.get_profile(profile.adapter.key)
    if source.adapter_key != adapter.key:
        raise ConfigurationError("job adapter does not match its registered source")
    if profile.adapter.version != adapter.version:
        raise ConfigurationError("job adapter version does not match the registry")
    if profile.refresh_strategy not in adapter.supported_refresh_strategies:
        raise ConfigurationError("job refresh strategy is unsupported by its adapter")
    if set(profile.supported_modes) - set(adapter.supported_modes):
        raise ConfigurationError("job requests unsupported adapter modes")
    checks = (
        ("max_objects", profile.limits.max_objects, adapter.limits.max_objects),
        ("max_bytes", profile.limits.max_bytes, adapter.limits.max_bytes),
        ("max_rows", profile.limits.max_rows, adapter.limits.max_rows),
        ("deadline", profile.limits.deadline_seconds, adapter.limits.deadline_seconds),
        ("parallelism", profile.limits.max_parallelism, adapter.limits.max_parallelism),
    )
    for name, requested, maximum in checks:
        if requested > maximum:
            raise ConfigurationError(f"job {name} exceeds the adapter limit")
