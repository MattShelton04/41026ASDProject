"""Extract only bounded, flat PNG and JSON files from an untrusted capture artifact.

Archive member names are never used as paths: each must match a strict flat pattern.
"""

from __future__ import annotations

import re
import stat
import zipfile
from pathlib import Path

from scripts.visual.policy import MAX_JSON_BYTES, MAX_PNG_BYTES, MAX_VIEWS

MEMBER = re.compile(r"^(?:[a-z][a-z0-9-]{0,63}\.png|capture-(?:fixture|stack)\.json)$")
MAX_TOTAL_BYTES = 400_000_000


def extract(archive_path: Path, destination: Path) -> list[str]:
    """Extract accepted members and return their names; reject the whole archive otherwise."""
    destination.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    total = 0
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        if len(members) > MAX_VIEWS * 2 + 4:
            raise ValueError("too many artifact entries")
        for member in members:
            name = member.filename
            if name.endswith(".failed.png"):
                continue  # diagnostic screenshots stay in the capture artifact only
            if not MEMBER.fullmatch(name):
                raise ValueError(f"unexpected artifact entry: {name[:80]!r}")
            if stat.S_ISLNK(member.external_attr >> 16):
                raise ValueError("artifact symlinks are not accepted")
            limit = MAX_PNG_BYTES if name.endswith(".png") else MAX_JSON_BYTES
            total += member.file_size
            if member.file_size > limit or total > MAX_TOTAL_BYTES:
                raise ValueError(f"{name} exceeds the artifact size limit")
            with archive.open(member) as source:
                data = source.read(limit + 1)
            if len(data) > limit:
                raise ValueError(f"{name} exceeds the artifact size limit")
            (destination / name).write_bytes(data)
            written.append(name)
    return written
