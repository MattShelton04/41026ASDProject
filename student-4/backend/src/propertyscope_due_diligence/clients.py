"""HTTP clients for the due-diligence backend's downstream boundaries.

The backend never opens a database connection. It calls its own feature-owned
database API over HTTP, and validates property references against Feature 1 over
HTTP. The network methods are ``# pragma: no cover`` because the deterministic gate
injects fakes; they are exercised by the container/integration checks.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx


class DependencyUnavailableError(RuntimeError):
    """A required downstream HTTP dependency could not answer safely."""


class DueDiligenceStoreClient:
    """Transport facade over the feature-owned database API."""

    def __init__(self, base_url: str, internal_token: str, *, client: httpx.Client | None = None):
        self._origin = base_url.rstrip("/")
        self._token = internal_token
        self._client = client or httpx.Client(timeout=5, follow_redirects=False)

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
    ) -> httpx.Response:
        try:
            return self._client.request(
                method,
                f"{self._origin}{path}",
                headers={"X-PropertyScope-Internal-Token": self._token},
                params=params,
                json=json,
            )
        except httpx.TransportError as exc:
            raise DependencyUnavailableError("due-diligence data store is unavailable") from exc

    def ready(self) -> bool:
        try:
            return self._client.get(f"{self._origin}/health/ready", timeout=2).status_code == 200
        except httpx.TransportError:
            return False


class Feature1Client:
    """Validate property references against Feature 1 without any shared database."""

    def __init__(self, base_url: str, *, client: httpx.Client | None = None):
        self._origin = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=5, follow_redirects=False)

    def validate(self, property_ref: str) -> str:
        """Return ``valid``, ``not_found`` or ``unavailable`` for one property reference."""
        try:
            response = self._client.get(
                f"{self._origin}/api/data-platform/v1/properties/{property_ref}"
            )
        except httpx.TransportError:
            return "unavailable"
        if response.status_code == 200:
            return "valid"
        if response.status_code == 404:
            return "not_found"
        return "unavailable"
