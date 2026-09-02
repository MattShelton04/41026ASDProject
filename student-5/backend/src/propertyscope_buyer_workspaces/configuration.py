"""Runtime configuration for the public Buyer Case backend."""

from __future__ import annotations

import os
from dataclasses import dataclass

DEMO_OWNER_REF = "release0-demo-owner"


@dataclass(frozen=True, slots=True)
class BackendSettings:
    """Server-only settings; none are projected into browser content."""

    database_api_url: str
    internal_token: str
    demo_owner_ref: str = DEMO_OWNER_REF
    max_request_bytes: int = 1_048_576

    def __post_init__(self) -> None:
        if not self.database_api_url.startswith(("http://", "https://")):
            raise ValueError("database_api_url must be an HTTP origin")
        if not self.internal_token.strip():
            raise ValueError("internal_token must not be empty")
        if not self.demo_owner_ref.strip():
            raise ValueError("demo_owner_ref must not be empty")
        if self.max_request_bytes < 1:
            raise ValueError("max_request_bytes must be positive")

    @classmethod
    def from_environment(cls) -> BackendSettings:
        return cls(
            database_api_url=os.environ.get(
                "PROPERTYSCOPE_BUYER_DATABASE_API_URL", "http://f5-db-api:5502"
            ),
            internal_token=os.environ.get(
                "PROPERTYSCOPE_INTERNAL_TOKEN", "propertyscope-local-development-only"
            ),
            demo_owner_ref=os.environ.get("PROPERTYSCOPE_DEMO_OWNER_REF", DEMO_OWNER_REF),
        )
