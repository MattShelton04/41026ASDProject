"""Immutable downstream release manifest contracts and canonical hashing."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from .release_builders import ReleaseManifestV1

ReleaseManifest = ReleaseManifestV1


def canonical_manifest_bytes(manifest: ReleaseManifest | dict[str, Any]) -> bytes:
    payload = (
        manifest.model_dump(mode="json", by_alias=True, exclude_none=True)
        if isinstance(manifest, ReleaseManifest)
        else ReleaseManifest.model_validate(manifest).model_dump(
            mode="json", by_alias=True, exclude_none=True
        )
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
