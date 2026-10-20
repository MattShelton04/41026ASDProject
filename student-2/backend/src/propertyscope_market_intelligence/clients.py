"""Injected HTTP clients for Feature 2's service boundaries."""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Mapping
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
    """A dependency could not be reached safely."""


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


class StoreClient:
    def __init__(self, base_url: str, token: str, *, client: httpx.Client | None = None) -> None:
        self._origin = base_url.rstrip("/")
        self._token = token
        self._client = client or httpx.Client(timeout=5, follow_redirects=False)

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Mapping[str, Any] | None = None,
    ) -> httpx.Response:
        try:
            return self._client.request(
                method,
                f"{self._origin}{path}",
                params=params,
                json=json,
                headers={"X-PropertyScope-Internal-Token": self._token},
            )
        except httpx.TransportError as exc:
            raise DependencyUnavailableError("Market database API is unavailable") from exc

    def ready(self) -> bool:
        try:
            return self._client.get(f"{self._origin}/health/ready", timeout=2).status_code == 200
        except httpx.TransportError:
            return False


class Feature1Client:
    def __init__(self, base_url: str, *, client: httpx.Client | None = None) -> None:
        self._origin = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=10, follow_redirects=False)

    def validate_property(self, property_ref: str) -> str:
        try:
            response = self._client.get(
                f"{self._origin}/api/data-platform/v1/properties/{property_ref}", timeout=3
            )
        except httpx.TransportError:
            return "unavailable"
        if response.status_code == 404:
            return "not_found"
        return "verified" if response.status_code < 300 else "unavailable"

    def iter_artifact(self, path: str) -> Iterator[bytes]:
        if not path.startswith("/api/data-platform/v1/dataset-releases/") or any(
            marker in path for marker in ("..", "\\", "?", "#")
        ):
            raise ValueError("artifact path is not a permitted Feature 1 route")
        try:
            with self._client.stream("GET", f"{self._origin}{path}", timeout=30) as response:
                if response.is_redirect:
                    raise ValueError("artifact redirects are rejected")
                response.raise_for_status()
                yield from response.iter_raw(chunk_size=256 * 1024)
        except httpx.TransportError as exc:
            raise DependencyUnavailableError("Feature 1 sales artifact is unavailable") from exc
        except httpx.HTTPStatusError as exc:
            raise ValueError("Feature 1 rejected the sales artifact request") from exc


class AiModeClient:
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
                "AI mode is unavailable; market-case CRUD and summaries remain usable"
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
        "The Multi-Agent Server is unavailable; saved market cases and their evidence still work"
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
        """Whether a brief could actually run now: configured and the server answering.

        Configuration alone is not enough. `dev.py` issues a service token to every stack it
        starts, but the Multi-Agent Server is a host process that CI never starts, so a
        configured backend there still has nothing to reach. The page asks this before it mounts
        a panel whose first request would otherwise be a 503 the reader cannot act on.

        Liveness only, on a short timeout: a server that is up but degraded still answers its own
        routes, and this must never become a second way for a run to fail.
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
