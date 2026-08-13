from __future__ import annotations

import hashlib

import pytest

from propertyscope_data_platform.artifacts import ArtifactError, LocalArtifactStore


def test_verified_path_streams_and_validates_registered_metadata(tmp_path) -> None:
    store = LocalArtifactStore(tmp_path)
    payload = b"official-source-bytes" * 100
    artifact = store.put(
        (payload[:50], payload[50:]), max_bytes=len(payload), media_type="test/zip"
    )

    path = store.verified_path(
        artifact.storage_key,
        artifact.sha256,
        expected_bytes=len(payload),
        max_bytes=len(payload),
    )

    assert path.read_bytes() == payload
    assert artifact.sha256 == hashlib.sha256(payload).hexdigest()


def test_verified_path_rejects_size_checksum_and_missing_artifacts(tmp_path) -> None:
    store = LocalArtifactStore(tmp_path)
    artifact = store.put((b"payload",), max_bytes=7, media_type="application/octet-stream")

    with pytest.raises(ArtifactError, match="size does not match"):
        store.verified_path(artifact.storage_key, artifact.sha256, expected_bytes=8, max_bytes=8)
    with pytest.raises(ArtifactError, match="checksum failed"):
        store.verified_path(artifact.storage_key, "0" * 64, expected_bytes=7, max_bytes=7)
    with pytest.raises(ArtifactError, match="does not exist"):
        store.verified_path("sha256/00/" + "0" * 64, "0" * 64, expected_bytes=0, max_bytes=1)
