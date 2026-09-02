"""Environment settings for the Feature 2 database API."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StoreSettings:
    """Small validated settings surface owned by the database service."""

    database_path: Path
    internal_token: str
    auto_migrate: bool = True

    @classmethod
    def from_environment(cls) -> StoreSettings:
        return cls(
            database_path=Path(
                os.environ.get(
                    "PROPERTYSCOPE_MARKET_DATABASE_PATH",
                    "/var/lib/propertyscope-market/market.sqlite3",
                )
            ),
            internal_token=os.environ.get(
                "PROPERTYSCOPE_INTERNAL_TOKEN", "propertyscope-local-development-only"
            ),
            auto_migrate=os.environ.get("PROPERTYSCOPE_AUTO_MIGRATE", "true").lower()
            in {"1", "true", "yes"},
        )
