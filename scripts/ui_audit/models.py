"""Typed immutable configuration and batch models for the UI audit."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Gate = Literal["release-critical-full-matrix", "required-capture-bounded-resilience"]


@dataclass(frozen=True)
class Viewport:
    """One configured browser viewport and its release policy."""

    id: str
    width: int
    height: int
    gate: Gate


@dataclass(frozen=True)
class AuditCase:
    """One executable fixture state for a route."""

    id: str
    scenario: str
    states: tuple[str, ...]
    path: str | None = None
    settle_ms: int = 650
    quick: bool = False
    expected_request_failures: tuple[str, ...] = ()
    capture_phase: Literal["settled", "loading", "loading-and-settled"] = "settled"
    readiness: str = "body"
    settled_readiness: str = "body"
    overrides: tuple[dict[str, Any], ...] = ()
    setup: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class RouteDefinition:
    """A baseline route with explicit executable and deferred states."""

    id: str
    workspace: str
    route_group: str
    path: str
    cases: tuple[AuditCase, ...]
    deferred_states: dict[str, str]
    configured_interactions: tuple[str, ...] = ()


@dataclass(frozen=True)
class AuditBatch:
    """Atomic resumable unit of route, case, and viewport work."""

    id: str
    workspace: str
    route_group: str
    route_id: str
    path: str
    case: AuditCase
    viewport: Viewport
    fingerprint: str

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-ready representation."""
        return asdict(self)


@dataclass(frozen=True)
class Finding:
    """One classified audit signal."""

    code: str
    severity: Literal["error", "warning", "info"]
    message: str
    gate: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-ready representation."""
        return asdict(self)
