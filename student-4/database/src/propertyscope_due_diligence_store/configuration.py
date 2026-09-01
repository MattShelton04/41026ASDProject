"""Configuration for the exclusive Student 4 due-diligence database owner."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StoreSettings:
    """Validated database-service settings loaded without leaking credentials."""

    database_url: str
    internal_token: str
    auto_migrate: bool = True

    @classmethod
    def from_environment(cls) -> StoreSettings:
        """Read explicit environment settings and reject missing credentials."""
        database_url = os.environ.get("PROPERTYSCOPE_DUE_DILIGENCE_DATABASE_URL", "").strip()
        if not database_url:
            raise RuntimeError("PROPERTYSCOPE_DUE_DILIGENCE_DATABASE_URL is required")
        token = os.environ.get("PROPERTYSCOPE_INTERNAL_TOKEN", "local-development-only").strip()
        if not token:
            raise RuntimeError("PROPERTYSCOPE_INTERNAL_TOKEN must not be empty")
        return cls(
            database_url=database_url,
            internal_token=token,
            auto_migrate=_boolean("PROPERTYSCOPE_AUTO_MIGRATE", default=True),
        )


def _boolean(name: str, *, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
