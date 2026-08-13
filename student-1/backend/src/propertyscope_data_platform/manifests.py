"""Immutable downstream release manifest contracts and canonical hashing."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import date
from typing import Annotated, Any

from pydantic import Field, StringConstraints, field_validator, model_validator

from .domain import DomainModel, Identifier, Sha256

Month = Annotated[str, StringConstraints(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]


class ReleasePeriod(DomainModel):
    from_: Month = Field(alias="from")
    to: Month

    @model_validator(mode="after")
    def ordered(self) -> ReleasePeriod:
        if self.from_ > self.to:
            raise ValueError("period.from must not be after period.to")
        return self


class ReleaseManifest(DomainModel):
    schema_version: str = Field(min_length=1, max_length=100)
    release_id: str = Field(min_length=1, max_length=150)
    dataset_id: Identifier
    owner_feature: Identifier
    publisher: str = Field(min_length=1, max_length=200)
    source_release: str = Field(min_length=1, max_length=100)
    content_sha256: Sha256
    record_count: int = Field(ge=0)
    geographies: tuple[str, ...] = Field(default=(), max_length=10_000)
    period: ReleasePeriod | None = None
    measures: tuple[Identifier, ...] = Field(default=(), max_length=100)
    redistribution_policy: Identifier
    known_limitations: tuple[str, ...] = Field(default=(), max_length=100)
    created_date: date | None = None

    @field_validator("geographies", "measures")
    @classmethod
    def sorted_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("manifest collections must not contain duplicates")
        if value != tuple(sorted(value)):
            raise ValueError("manifest collections must use canonical sorted order")
        return value


def canonical_manifest_bytes(manifest: ReleaseManifest | dict[str, Any]) -> bytes:
    payload = (
        manifest.model_dump(mode="json", by_alias=True, exclude_none=True)
        if isinstance(manifest, ReleaseManifest)
        else manifest
    )
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def canonical_manifest_sha256(manifest: ReleaseManifest | dict[str, Any]) -> str:
    return hashlib.sha256(canonical_manifest_bytes(manifest)).hexdigest()


def verify_content_sha256(content: bytes, expected: str) -> None:
    actual = hashlib.sha256(content).hexdigest()
    if not hmac.compare_digest(actual, expected):
        raise ValueError("release artifact checksum does not match manifest")
