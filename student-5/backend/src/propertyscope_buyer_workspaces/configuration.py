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
    data_platform_url: str = "http://f1-backend:5201"
    market_intelligence_url: str = "http://f2-backend:5301"
    due_diligence_url: str = "http://f4-backend:5401"
    ai_mode_url: str = "http://shared-ai-mode:5005"

    def __post_init__(self) -> None:
        origins = {
            "database_api_url": self.database_api_url,
            "data_platform_url": self.data_platform_url,
            "market_intelligence_url": self.market_intelligence_url,
            "due_diligence_url": self.due_diligence_url,
            "ai_mode_url": self.ai_mode_url,
        }
        for name, origin in origins.items():
            if not origin.startswith(("http://", "https://")):
                raise ValueError(f"{name} must be an HTTP origin")
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
            data_platform_url=os.environ.get(
                "PROPERTYSCOPE_DATA_PLATFORM_URL", "http://f1-backend:5201"
            ),
            market_intelligence_url=os.environ.get(
                "PROPERTYSCOPE_MARKET_INTELLIGENCE_URL", "http://f2-backend:5301"
            ),
            due_diligence_url=os.environ.get(
                "PROPERTYSCOPE_DUE_DILIGENCE_URL", "http://f4-backend:5401"
            ),
            ai_mode_url=os.environ.get("AI_MODE_BASE_URL", "http://shared-ai-mode:5005"),
            demo_owner_ref=os.environ.get("PROPERTYSCOPE_DEMO_OWNER_REF", DEMO_OWNER_REF),
        )
