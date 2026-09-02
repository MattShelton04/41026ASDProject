"""Content-addressed artifact store with traversal-safe verified reads."""

from __future__ import annotations

import hashlib
import os
import tempfile
import time
from collections.abc import Callable, Iterable
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

    def put(
        self, chunks: Iterable[bytes], *, media_type: str, max_bytes: int | None = None
    ) -> ArtifactRef:
        digest = hashlib.sha256()
        byte_count = 0
        descriptor, temporary_name = tempfile.mkstemp(prefix="artifact-", dir=self._root)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                for chunk in chunks:
                    byte_count += len(chunk)
                    if max_bytes is not None and byte_count > max_bytes:
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
                existing_digest = hashlib.sha256()
                with destination.open("rb") as existing:
                    for chunk in iter(lambda: existing.read(1024 * 1024), b""):
                        existing_digest.update(chunk)
                if (
                    destination.stat().st_size == byte_count
                    and existing_digest.hexdigest() == checksum
                ):
                    Path(temporary_name).unlink()
                else:
                    # The new temporary was hashed while written, so it can safely repair a
                    # corrupt object already occupying the content-addressed destination.
                    os.replace(temporary_name, destination)
            else:
                os.replace(temporary_name, destination)
            return ArtifactRef(checksum, storage_key, byte_count, media_type)
        except BaseException:
            Path(temporary_name).unlink(missing_ok=True)
            raise

    def put_generated(
        self,
        generate: Callable[[Path], object],
        *,
        media_type: str,
        max_bytes: int | None = None,
    ) -> ArtifactRef:
        """Let a seekable-format writer populate a managed temporary artifact atomically."""
        descriptor, temporary_name = tempfile.mkstemp(prefix="artifact-", dir=self._root)
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            generate(temporary)
            if not temporary.is_file():
                raise ArtifactError("artifact generator did not create an artifact")
            byte_count = temporary.stat().st_size
            if max_bytes is not None and byte_count > max_bytes:
                raise ArtifactError("artifact exceeds registered byte limit")
            digest = hashlib.sha256()
            with temporary.open("r+b") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
                os.fsync(stream.fileno())
            checksum = digest.hexdigest()
            storage_key = f"sha256/{checksum[:2]}/{checksum}"
            destination = self._resolve(storage_key)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() and self._matches(destination, byte_count, checksum):
                temporary.unlink()
            else:
                os.replace(temporary, destination)
            return ArtifactRef(checksum, storage_key, byte_count, media_type)
        except BaseException:
            temporary.unlink(missing_ok=True)
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

    def verified_path(
        self,
        storage_key: str,
        expected_sha256: str,
        *,
        expected_bytes: int,
        max_bytes: int | None = None,
    ) -> Path:
        """Verify a large artifact without materialising it in memory, then return its path."""
        path = self._resolve(storage_key)
        if not path.is_file():
            raise ArtifactError("artifact does not exist")
        if (
            max_bytes is not None and expected_bytes > max_bytes
        ) or path.stat().st_size != expected_bytes:
            raise ArtifactError("artifact size does not match registered metadata")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected_sha256:
            raise ArtifactError("artifact checksum failed")
        return path

    def cleanup_unreferenced(
        self,
        referenced_storage_keys: set[str],
        *,
        grace_seconds: int,
        dry_run: bool = True,
    ) -> dict[str, object]:
        """Report or remove only content objects absent from the durable reference ledger."""
        if grace_seconds < 1:
            raise ArtifactError("artifact cleanup requires a positive grace period")
        cutoff = time.time() - grace_seconds
        candidates: list[dict[str, object]] = []
        removed_bytes = 0
        content_root = self._root / "sha256"
        if content_root.is_dir():
            for path in content_root.glob("*/*"):
                if not path.is_file():
                    continue
                storage_key = path.relative_to(self._root).as_posix()
                if storage_key in referenced_storage_keys or path.stat().st_mtime > cutoff:
                    continue
                size = path.stat().st_size
                candidates.append({"storage_key": storage_key, "bytes": size})
                if not dry_run:
                    path.unlink()
                    removed_bytes += size
        return {
            "dry_run": dry_run,
            "grace_seconds": grace_seconds,
            "candidate_count": len(candidates),
            "candidate_bytes": sum(int(str(item["bytes"])) for item in candidates),
            "removed_bytes": removed_bytes,
            "candidates": candidates,
        }

    def _resolve(self, storage_key: str) -> Path:
        if not storage_key.startswith("sha256/") or ".." in Path(storage_key).parts:
            raise ArtifactError("storage key is not content-addressed")
        path = (self._root / storage_key).resolve()
        if path == self._root or self._root not in path.parents:
            raise ArtifactError("storage key escapes artifact root")
        return path

    @staticmethod
    def _matches(path: Path, expected_bytes: int, expected_sha256: str) -> bool:
        if path.stat().st_size != expected_bytes:
            return False
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest() == expected_sha256
