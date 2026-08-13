from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from propertyscope_data_platform.manifests import (
    ReleaseManifest,
    canonical_manifest_bytes,
    canonical_manifest_sha256,
    verify_content_sha256,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "contracts" / "fixtures"


def test_valid_release_manifest_is_canonical_and_stable() -> None:
    payload = json.loads((FIXTURES / "release-manifest.valid.json").read_text("utf-8"))
    manifest = ReleaseManifest.model_validate(payload)
    first = canonical_manifest_bytes(manifest)
    assert first == canonical_manifest_bytes(dict(reversed(list(payload.items()))))
    assert canonical_manifest_sha256(manifest) == canonical_manifest_sha256(payload)


def test_invalid_checksum_fixture_is_rejected() -> None:
    payload = json.loads((FIXTURES / "release-manifest.invalid-checksum.json").read_text("utf-8"))
    with pytest.raises(ValidationError, match="content_sha256"):
        ReleaseManifest.model_validate(payload)


def test_artifact_checksum_mismatch_fails_closed() -> None:
    with pytest.raises(ValueError, match="does not match"):
        verify_content_sha256(b"artifact", "0" * 64)
