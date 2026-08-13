"""Content-addressed artifact store with traversal-safe verified reads."""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


class ArtifactError(RuntimeError):
    """Artifact violates storage, size, or checksum policy."""


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    sha256: str
    storage_key: str
    bytes: int
    media_type: str


class LocalArtifactStore:
    """Atomic, streaming, content-addressed local artifact implementation."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def put(self, chunks: Iterable[bytes], *, max_bytes: int, media_type: str) -> ArtifactRef:
        digest = hashlib.sha256()
        byte_count = 0
        descriptor, temporary_name = tempfile.mkstemp(prefix="artifact-", dir=self._root)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                for chunk in chunks:
                    byte_count += len(chunk)
                    if byte_count > max_bytes:
                        raise ArtifactError("artifact exceeds registered byte limit")
                    digest.update(chunk)
                    stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            checksum = digest.hexdigest()
            storage_key = f"sha256/{checksum[:2]}/{checksum}"
            destination = self._resolve(storage_key)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                Path(temporary_name).unlink()
            else:
                os.replace(temporary_name, destination)
            return ArtifactRef(checksum, storage_key, byte_count, media_type)
        except BaseException:
            Path(temporary_name).unlink(missing_ok=True)
            raise

    def read_verified(self, storage_key: str, expected_sha256: str, *, max_bytes: int) -> bytes:
        path = self._resolve(storage_key)
        if not path.is_file():
            raise ArtifactError("artifact does not exist")
        data = path.read_bytes()
        if len(data) > max_bytes:
            raise ArtifactError("artifact exceeds registered read limit")
        if hashlib.sha256(data).hexdigest() != expected_sha256:
            raise ArtifactError("artifact checksum failed")
        return data

    def _resolve(self, storage_key: str) -> Path:
        if not storage_key.startswith("sha256/") or ".." in Path(storage_key).parts:
            raise ArtifactError("storage key is not content-addressed")
        path = (self._root / storage_key).resolve()
        if path == self._root or self._root not in path.parents:
            raise ArtifactError("storage key escapes artifact root")
        return path
