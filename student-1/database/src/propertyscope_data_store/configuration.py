"""Configuration for the exclusive PropertyScope database owner."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_LOADER_TEMP_FILE_LIMIT_KIB = 16 * 1024 * 1024
DEFAULT_LOADER_DISK_RESERVE_BYTES = 4 * 1024 * 1024 * 1024
DEFAULT_LOADER_ARTIFACT_EXPANSION_FACTOR = 3


def _default_runtime_profile_root() -> Path:
    return Path(__file__).resolve().parents[3] / "config" / "job-profiles"


@dataclass(frozen=True, slots=True)
class StoreSettings:
    """Validated database-service settings."""

    database_url: str
    artifact_root: Path
    internal_token: str
    auto_migrate: bool = True
    runtime_profile_root: Path = field(default_factory=_default_runtime_profile_root)
    loader_temp_file_limit_kib: int = DEFAULT_LOADER_TEMP_FILE_LIMIT_KIB
    loader_disk_reserve_bytes: int = DEFAULT_LOADER_DISK_RESERVE_BYTES
    loader_artifact_expansion_factor: int = DEFAULT_LOADER_ARTIFACT_EXPANSION_FACTOR

    @classmethod
    def from_environment(cls) -> StoreSettings:
        """Load explicit settings without leaking credential values."""
        database_url = os.environ.get("PROPERTYSCOPE_DATABASE_URL", "").strip()
        if not database_url:
            raise RuntimeError("PROPERTYSCOPE_DATABASE_URL is required")
        token = os.environ.get("PROPERTYSCOPE_INTERNAL_TOKEN", "local-development-only").strip()
        if not token:
            raise RuntimeError("PROPERTYSCOPE_INTERNAL_TOKEN must not be empty")
        return cls(
            database_url=database_url,
            artifact_root=Path(
                os.environ.get("PROPERTYSCOPE_ARTIFACT_ROOT", "/var/lib/propertyscope/artifacts")
            ).resolve(),
            internal_token=token,
            auto_migrate=_boolean("PROPERTYSCOPE_AUTO_MIGRATE", default=True),
            runtime_profile_root=Path(
                os.environ.get(
                    "PROPERTYSCOPE_RUNTIME_PROFILE_ROOT",
                    str(_default_runtime_profile_root()),
                )
            ).resolve(),
            loader_temp_file_limit_kib=_bounded_integer(
                "PROPERTYSCOPE_LOADER_TEMP_FILE_LIMIT_KIB",
                default=DEFAULT_LOADER_TEMP_FILE_LIMIT_KIB,
                minimum=64 * 1024,
                maximum=64 * 1024 * 1024,
            ),
            loader_disk_reserve_bytes=_bounded_integer(
                "PROPERTYSCOPE_LOADER_DISK_RESERVE_BYTES",
                default=DEFAULT_LOADER_DISK_RESERVE_BYTES,
                minimum=0,
                maximum=1024 * 1024 * 1024 * 1024,
            ),
            loader_artifact_expansion_factor=_bounded_integer(
                "PROPERTYSCOPE_LOADER_ARTIFACT_EXPANSION_FACTOR",
                default=DEFAULT_LOADER_ARTIFACT_EXPANSION_FACTOR,
                minimum=1,
                maximum=16,
            ),
        )


def _boolean(name: str, *, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _bounded_integer(name: str, *, default: int, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value < minimum or value > maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
    return value
