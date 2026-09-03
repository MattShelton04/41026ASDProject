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

    def search(self, query: str, limit: int = 8) -> dict[str, Any]:
        """Return ``{"available": bool, "items": [...]}`` of verified-property matches.

        Mirrors ``validate``: transport failures degrade to ``available: False`` rather than
        raising, so the create form can fall back gracefully when Feature 1 is unreachable.
        """
        try:
            response = self._client.get(
                f"{self._origin}/api/data-platform/v1/properties/search",
                params={"q": query, "state": "NSW", "limit": limit},
            )
        except httpx.TransportError:
            return {"available": False, "items": []}
        if response.status_code != 200:
            return {"available": True, "items": []}
        payload = response.json()
        raw_items = payload.get("items", []) if isinstance(payload, dict) else []
        items = [
            {
                "property_ref": item["property_ref"],
                "address_display": item["address_display"],
                "resolution_status": item.get("resolution_status"),
                "locality": item.get("locality"),
                "postcode": item.get("postcode"),
            }
            for item in raw_items
            if isinstance(item, dict)
            and isinstance(item.get("property_ref"), str)
            and isinstance(item.get("address_display"), str)
        ]
        return {"available": True, "items": items[:limit]}

    def coordinates(self, property_ref: str) -> tuple[float, float] | None:
        """Return ``(longitude, latitude)`` for a verified property, or ``None`` if unavailable.

        Resolves the canonical property record from Feature 1 by reference, so Feature 4 never
        persists a coordinate and does not depend on address text matching a search index.
        """
        try:
            response = self._client.get(
                f"{self._origin}/api/data-platform/v1/properties/{property_ref}"
            )
        except httpx.TransportError:
            return None
        if response.status_code != 200:
            return None
        payload = response.json()
        prop = payload.get("property") if isinstance(payload, dict) else None
        if not isinstance(prop, dict):
            return None
        longitude = prop.get("longitude")
        latitude = prop.get("latitude")
        if isinstance(longitude, (int, float)) and isinstance(latitude, (int, float)):
            return (float(longitude), float(latitude))
        return None


class AiModeClient:
    """Feature-safe projection over the shared AI-mode agent-run API.

    The feature never selects a model or provider: it creates a bounded agent run and
    the shared AI-mode service applies its configured model profile (OpenAI or Gemini).
    Transport failures degrade to ``DependencyUnavailableError`` so direct CRUD and
    deterministic evidence keep working when AI-mode is unavailable.
    """

    def __init__(self, base_url: str, *, client: httpx.Client | None = None) -> None:
        self._origin = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=10, follow_redirects=False)

    def create_run(self, payload: Mapping[str, Any]) -> httpx.Response:
        return self._request("POST", "/api/v1/agent-runs", json=payload)

    def get(self, path: str, *, params: Mapping[str, Any] | None = None) -> httpx.Response:
        return self._request("GET", path, params=params)

    def cancel(self, run_id: str) -> httpx.Response:
        return self._request("POST", f"/api/v1/agent-runs/{run_id}/cancel")

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            return self._client.request(method, f"{self._origin}{path}", **kwargs)
        except httpx.TransportError as exc:
            raise DependencyUnavailableError(
                "AI mode is unavailable; direct CRUD and evidence remain usable"
            ) from exc
