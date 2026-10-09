"""Bounded, allowlisted and hashed reading of release evidence files.

Collectors never open a path directly. They ask an :class:`EvidenceReader` for paths relative
to the evidence root; the reader refuses anything outside the root or behind a symlink, caps
per-file and total bytes, hashes every file it sees (including oversize ones) and records one
:class:`EvidenceInput` per path so the review can show exactly what it relied on.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from pydantic import JsonValue

from shared_contracts.evidence_review import EvidenceInput, InputStatus

DEFAULT_MAX_FILE_BYTES = 1024 * 1024
DEFAULT_MAX_TOTAL_BYTES = 16 * 1024 * 1024
DEFAULT_MAX_FILES = 150
DEFAULT_LOG_TAIL_BYTES = 512 * 1024
_HASH_CHUNK = 64 * 1024


@dataclass(frozen=True, slots=True)
class LoadedText:
    """Text of one evidence file, or ``None`` when it was not readable inside the bounds."""

    path: str
    text: str | None
    status: InputStatus
    truncated: bool = False


class EvidenceReader:
    """Read evidence below ``root`` with explicit caps and an auditable input ledger."""

    def __init__(
        self,
        root: Path,
        *,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
        max_files: int = DEFAULT_MAX_FILES,
    ) -> None:
        self.root = root.resolve()
        self.max_file_bytes = max_file_bytes
        self.max_total_bytes = max_total_bytes
        self.max_files = max_files
        self._consumed = 0
        self._inputs: dict[str, EvidenceInput] = {}

    @property
    def inputs(self) -> tuple[EvidenceInput, ...]:
        """Return every recorded input in deterministic path order."""
        return tuple(self._inputs[path] for path in sorted(self._inputs))

    def known_paths(self) -> frozenset[str]:
        """Return the paths a check may cite as evidence."""
        return frozenset(self._inputs)

    def exists(self, relative: str) -> bool:
        """Return whether an allowlisted regular file exists, without recording it."""
        target = self._resolve(relative)
        return target is not None and target.is_file()

    def glob(self, directory: str, patterns: tuple[str, ...], *, max_depth: int = 3) -> list[str]:
        """List regular files under ``directory`` matching any pattern, sorted and capped."""
        base = self._resolve(directory)
        if base is None or not base.is_dir():
            return []
        found: set[str] = set()
        for pattern in patterns:
            for candidate in base.rglob(pattern):
                relative = candidate.relative_to(self.root)
                if len(relative.relative_to(directory).parts) > max_depth:
                    continue
                if candidate.is_symlink() or not candidate.is_file():
                    continue
                found.add(relative.as_posix())
        return sorted(found)[: self.max_files]

    def read_text(self, relative: str, *, tail_bytes: int | None = None) -> LoadedText:
        """Read UTF-8 text, or only its final ``tail_bytes`` for long logs, recording the input."""
        path = PurePosixPath(relative).as_posix()
        target = self._resolve(path)
        if target is None:
            return self._record(path, InputStatus.INVALID, detail="path is outside the allowlist")
        if target.is_symlink():
            return self._record(path, InputStatus.INVALID, detail="symbolic links are not read")
        if not target.is_file():
            return self._record(path, InputStatus.MISSING, detail="file not found")
        if len(self._inputs) >= self.max_files and path not in self._inputs:
            return self._record(path, InputStatus.OVERSIZE, detail="evidence file limit reached")
        size = target.stat().st_size
        digest = _sha256(target)
        limit = self.max_file_bytes if tail_bytes is None else tail_bytes
        truncated = False
        if size > limit and tail_bytes is None:
            return self._record(
                path,
                InputStatus.OVERSIZE,
                sha256=digest,
                size=size,
                detail=f"{size} bytes exceeds the {limit}-byte review limit",
            )
        if self._consumed + min(size, limit) > self.max_total_bytes:
            return self._record(
                path,
                InputStatus.OVERSIZE,
                sha256=digest,
                size=size,
                detail="total evidence budget exhausted",
            )
        with target.open("rb") as stream:
            if size > limit:
                stream.seek(size - limit)
                truncated = True
            raw = stream.read(limit)
        self._consumed += len(raw)
        try:
            text = raw.decode("utf-8") if not truncated else raw.decode("utf-8", errors="replace")
        except UnicodeDecodeError:
            return self._record(
                path, InputStatus.INVALID, sha256=digest, size=size, detail="not UTF-8 text"
            )
        detail = f"final {limit} of {size} bytes reviewed" if truncated else None
        self._record(path, InputStatus.READ, sha256=digest, size=size, detail=detail)
        return LoadedText(path=path, text=text, status=InputStatus.READ, truncated=truncated)

    def read_json(self, relative: str) -> tuple[LoadedText, JsonValue | None]:
        """Read one JSON document; a parse failure marks the input invalid."""
        loaded = self.read_text(relative)
        if loaded.text is None:
            return loaded, None
        try:
            value: JsonValue = json.loads(loaded.text)
        except json.JSONDecodeError as exc:
            return self._invalidate(loaded, f"invalid JSON at line {exc.lineno}"), None
        return loaded, value

    def read_jsonl(self, relative: str) -> tuple[LoadedText, list[dict[str, JsonValue]] | None]:
        """Read JSON Lines objects; any malformed line marks the whole input invalid."""
        loaded = self.read_text(relative)
        if loaded.text is None:
            return loaded, None
        records: list[dict[str, JsonValue]] = []
        for number, line in enumerate(loaded.text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                return self._invalidate(loaded, f"invalid JSON on line {number}"), None
            if not isinstance(value, dict):
                return self._invalidate(loaded, f"line {number} is not a JSON object"), None
            records.append(value)
        return loaded, records

    def _invalidate(self, loaded: LoadedText, detail: str) -> LoadedText:
        current = self._inputs[loaded.path]
        self._inputs[loaded.path] = current.evolve(status=InputStatus.INVALID, detail=detail)
        return LoadedText(path=loaded.path, text=None, status=InputStatus.INVALID)

    def _resolve(self, relative: str) -> Path | None:
        candidate = PurePosixPath(relative)
        windows = PureWindowsPath(relative)
        if (
            candidate.is_absolute()
            or windows.drive
            or windows.is_absolute()
            or "\\" in relative
            or ".." in candidate.parts
        ):
            return None
        target = self.root.joinpath(*candidate.parts)
        try:
            resolved = target.resolve()
        except OSError:
            return None
        if resolved != self.root and self.root not in resolved.parents:
            return None
        # A symlink anywhere below the root could point outside it; report it, never follow it.
        if target.is_symlink():
            return target
        return resolved

    def _record(
        self,
        path: str,
        status: InputStatus,
        *,
        sha256: str | None = None,
        size: int | None = None,
        detail: str | None = None,
    ) -> LoadedText:
        self._inputs[path] = EvidenceInput(
            path=path[:300], status=status, sha256=sha256, bytes=size, detail=detail
        )
        return LoadedText(path=path, text=None, status=status)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(_HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()
