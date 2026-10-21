"""HTTP clients for the due-diligence backend's downstream boundaries.

The backend never opens a database connection. It calls its own feature-owned
database API over HTTP, validates property references against Feature 1 over
HTTP, and reaches the shared AI-mode service and the host Multi-Agent Server over
HTTP only. The network methods are ``# pragma: no cover`` because the deterministic gate
injects fakes; they are exercised by the container/integration checks.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

import httpx
from werkzeug.datastructures import Headers

from shared_contracts import (
    REQUEST_ID_HEADER,
    TRACEPARENT_HEADER,
    is_valid_request_id,
    is_valid_traceparent,
)
from shared_contracts.multi_agent import MULTI_AGENT_API_PREFIX


class DependencyUnavailableError(RuntimeError):
    """A required downstream HTTP dependency could not answer safely."""


_FORWARDED_REQUEST_HEADERS = {
    REQUEST_ID_HEADER.lower(): REQUEST_ID_HEADER,
    TRACEPARENT_HEADER.lower(): TRACEPARENT_HEADER,
}


def forwarded_headers(headers: Mapping[str, str] | Headers) -> dict[str, str]:
    """Return the allowlisted correlation headers under their canonical names.

    WSGI title-cases inbound header names, so matching on the display spelling loses correlation
    metadata. Each value is validated before it is forwarded to another service.
    """
    forwarded: dict[str, str] = {}
    for name, raw_value in headers.items():
        canonical = _FORWARDED_REQUEST_HEADERS.get(name.lower())
        if canonical is None:
            continue
        value = raw_value.strip()
        if not value:
            continue
        if canonical == REQUEST_ID_HEADER and not is_valid_request_id(value):
            continue
        if canonical == TRACEPARENT_HEADER and not is_valid_traceparent(value):
            continue
        forwarded[canonical] = value
    return forwarded


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

    def __init__(
        self, base_url: str, *, service_token: str = "", client: httpx.Client | None = None
    ) -> None:
        self._origin = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=10, follow_redirects=False)
        if service_token:
            self._client.headers["X-PropertyScope-AI-Token"] = service_token

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


class MultiAgentUnavailableError(DependencyUnavailableError):
    """The host Multi-Agent Server is unconfigured, unreachable or rejected our credential."""


class MultiAgentClient:
    """Fixed-operation HTTP client for the shared Multi-Agent Server.

    Every method maps to one documented ``/api/v1/multi-agent`` operation; there is no general
    upstream proxy, and the server is never imported in-process. Without a service token the
    client refuses to send anything, so the required cloud baseline - which supplies an empty
    token deliberately - degrades to ``multi_agent_unavailable`` rather than probing the server
    anonymously.
    """

    API_PREFIX = MULTI_AGENT_API_PREFIX
    CONNECT_TIMEOUT_SECONDS = 3.0
    READ_TIMEOUT_SECONDS = 10.0
    # The page waits on this before painting the card, so it is far shorter than a run's.
    PROBE_TIMEOUT_SECONDS = 1.5
    UNAVAILABLE_DETAIL = (
        "The Multi-Agent Server is unavailable; site reviews and their evidence still work"
    )

    def __init__(
        self,
        base_url: str,
        *,
        service_token: str = "",
        client: httpx.Client | None = None,
    ) -> None:
        self._origin = base_url.rstrip("/")
        self._token = service_token.strip()
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(self.READ_TIMEOUT_SECONDS, connect=self.CONNECT_TIMEOUT_SECONDS),
            follow_redirects=False,
        )

    @property
    def configured(self) -> bool:
        return bool(self._token)

    def available(self) -> bool:
        """Whether a review could actually run now: configured and the server answering.

        A token alone is not enough: ``dev.py`` issues one to every stack it starts, but the
        Multi-Agent Server is a host process that CI never starts. Liveness only, on a short
        timeout, so this never becomes a second way for a run to fail.
        """
        if not self._token:
            return False
        try:
            response = self._client.get(
                f"{self._origin}/health",
                timeout=httpx.Timeout(self.PROBE_TIMEOUT_SECONDS),
            )
        except httpx.HTTPError:
            return False
        return response.status_code < 400

    def template(self, template_id: str, headers: Mapping[str, str] | Headers) -> httpx.Response:
        return self._send("GET", f"/templates/{template_id}", headers)

    def create_run(
        self, payload: Mapping[str, Any], headers: Mapping[str, str] | Headers
    ) -> httpx.Response:
        return self._send("POST", "/runs", headers, json=dict(payload))

    def list_runs(
        self, params: Mapping[str, str | int], headers: Mapping[str, str] | Headers
    ) -> httpx.Response:
        return self._send("GET", "/runs", headers, params=params)

    def get_run(self, run_id: uuid.UUID, headers: Mapping[str, str] | Headers) -> httpx.Response:
        return self._send("GET", f"/runs/{run_id}", headers)

    def decide(
        self,
        run_id: uuid.UUID,
        payload: Mapping[str, Any],
        headers: Mapping[str, str] | Headers,
    ) -> httpx.Response:
        return self._send("POST", f"/runs/{run_id}/decision", headers, json=dict(payload))

    def cancel(
        self,
        run_id: uuid.UUID,
        payload: Mapping[str, Any] | None,
        headers: Mapping[str, str] | Headers,
    ) -> httpx.Response:
        body = dict(payload) if payload is not None else None
        return self._send("POST", f"/runs/{run_id}/cancel", headers, json=body)

    def history(
        self,
        run_id: uuid.UUID,
        headers: Mapping[str, str] | Headers,
        params: Mapping[str, str | int] | None = None,
    ) -> httpx.Response:
        return self._send("GET", f"/runs/{run_id}/history", headers, params=params or None)

    def _send(
        self,
        method: str,
        path: str,
        headers: Mapping[str, str] | Headers,
        *,
        params: Mapping[str, str | int] | None = None,
        json: Mapping[str, Any] | None = None,
    ) -> httpx.Response:
        if not self._token:
            raise MultiAgentUnavailableError(
                "The Multi-Agent Server is not configured for this deployment"
            )
        request_headers = forwarded_headers(headers)
        request_headers["Authorization"] = f"Bearer {self._token}"
        try:
            response = self._client.request(
                method,
                f"{self._origin}{self.API_PREFIX}{path}",
                headers=request_headers,
                params=params,
                json=json,
            )
        except httpx.TransportError as exc:
            raise MultiAgentUnavailableError(self.UNAVAILABLE_DETAIL) from exc
        if response.status_code == 401:
            # A rejected service credential is a deployment fault, not the browser's problem.
            raise MultiAgentUnavailableError(self.UNAVAILABLE_DETAIL)
        return response
