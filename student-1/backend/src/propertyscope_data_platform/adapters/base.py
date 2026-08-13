"""Value objects shared by source acquisition adapters."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import Field, field_validator

from ..domain import DomainModel, Identifier, ResourceLimits, Sha256


class SourceObject(DomainModel):
    logical_key: str = Field(min_length=1, max_length=300)
    media_type: str = Field(min_length=1, max_length=200)
    expected_bytes: int | None = Field(default=None, ge=0)
    expected_sha256: Sha256 | None = None
    partition: dict[str, str] = Field(default_factory=dict)


class SourceSnapshot(DomainModel):
    source_release: str = Field(min_length=1, max_length=100)
    objects: tuple[SourceObject, ...] = Field(max_length=100_000)
    discovered_at: datetime
    complete: bool

    @field_validator("objects")
    @classmethod
    def deterministic_objects(cls, value: tuple[SourceObject, ...]) -> tuple[SourceObject, ...]:
        keys = [item.logical_key for item in value]
        if len(keys) != len(set(keys)):
            raise ValueError("source object logical keys must be unique")
        if keys != sorted(keys):
            raise ValueError("source objects must be sorted by logical key")
        return value


class ArtifactRef(DomainModel):
    artifact_id: str = Field(min_length=1, max_length=200)
    logical_key: str = Field(min_length=1, max_length=300)
    content_sha256: Sha256
    media_type: str = Field(min_length=1, max_length=200)
    bytes: int = Field(ge=0)


class CancellationToken(Protocol):
    def raise_if_cancelled(self) -> None: ...


class RunContext(DomainModel):
    run_id: str = Field(min_length=1, max_length=100)
    source_key: Identifier
    scope: dict[str, object]
    limits: ResourceLimits
