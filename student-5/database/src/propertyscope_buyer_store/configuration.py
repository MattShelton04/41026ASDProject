"""Configuration for the Student 5 database service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class StoreSettings:
    """Runtime settings owned by the database service."""

    database_path: Path
    internal_token: str
    demo_owner_ref: str
    auto_migrate: bool = True

    def __post_init__(self) -> None:
        if not self.internal_token.strip():
            raise ValueError("internal_token must not be empty")
        if not self.demo_owner_ref.strip():
            raise ValueError("demo_owner_ref must not be empty")

    @classmethod
    def from_environment(cls) -> StoreSettings:
        """Load safe defaults used by the future container boundary."""

        return cls(
            database_path=Path(
                os.environ.get(
                    "PROPERTYSCOPE_BUYER_DATABASE_PATH",
                    "/var/lib/propertyscope-buyer/buyer-workspaces.sqlite3",
                )
            ),
            internal_token=os.environ.get(
                "PROPERTYSCOPE_INTERNAL_TOKEN",
                "propertyscope-local-development-only",
            ),
            demo_owner_ref=os.environ.get(
                "PROPERTYSCOPE_DEMO_OWNER_REF",
                "release0-demo-owner",
            ),
            auto_migrate=os.environ.get("PROPERTYSCOPE_AUTO_MIGRATE", "true").lower()
            not in {"0", "false", "no"},
        )
