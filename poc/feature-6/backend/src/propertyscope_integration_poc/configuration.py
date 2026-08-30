"""Environment-backed configuration for the local integration POC."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    feature1_origin: str
    ai_mode_origin: str
    store_origin: str
    internal_token: str
    contract_root: Path
    maximum_artifact_bytes: int
    maximum_legacy_json_bytes: int
    store_connect_timeout_seconds: float = 5.0
    store_read_timeout_seconds: float = 14_400.0
    store_write_timeout_seconds: float = 300.0
    store_pool_timeout_seconds: float = 5.0

    @classmethod
    def from_environment(cls) -> Settings:
        return cls(
            feature1_origin=os.environ.get("PROPERTYSCOPE_F1_ORIGIN", "http://f1-backend:5201"),
            ai_mode_origin=os.environ.get("AI_MODE_BASE_URL", "http://shared-ai-mode:5005"),
            store_origin=os.environ.get(
                "PROPERTYSCOPE_F6_DATABASE_API_URL", "http://poc-f6-db-api:5602"
            ),
            internal_token=os.environ.get(
                "PROPERTYSCOPE_F6_INTERNAL_TOKEN", "poc-f6-local-development-only"
            ),
            contract_root=Path(os.environ.get("POC_F6_CONTRACT_ROOT", "student-1/contracts")),
            maximum_artifact_bytes=_positive_int("POC_F6_MAX_ARTIFACT_BYTES", 250_000_000),
            maximum_legacy_json_bytes=_positive_int("POC_F6_MAX_LEGACY_JSON_BYTES", 50_000_000),
            store_connect_timeout_seconds=_positive_float(
                "POC_F6_STORE_CONNECT_TIMEOUT_SECONDS", 5.0
            ),
            store_read_timeout_seconds=_positive_float(
                "POC_F6_STORE_READ_TIMEOUT_SECONDS", 14_400.0
            ),
            store_write_timeout_seconds=_positive_float(
                "POC_F6_STORE_WRITE_TIMEOUT_SECONDS", 300.0
            ),
            store_pool_timeout_seconds=_positive_float("POC_F6_STORE_POOL_TIMEOUT_SECONDS", 5.0),
        )


def _positive_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _positive_float(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive number") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive number")
    return value
