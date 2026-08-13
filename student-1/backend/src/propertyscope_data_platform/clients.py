"""Injected HTTP clients for database-service and AI-mode boundaries."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx
from werkzeug.datastructures import Headers

PROPAGATED_HEADERS = ("X-Request-ID", "X-Agent-Run-ID", "traceparent", "Idempotency-Key")


class DependencyUnavailableError(RuntimeError):
    """A required HTTP dependency could not answer safely."""


class DataStoreClient:
    """Typed-enough transport facade; backend never imports database implementation."""

    def __init__(
        self,
        base_url: str,
        internal_token: str,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self._origin = base_url.rstrip("/")
        self._token = internal_token
        self._client = client or httpx.Client(timeout=5, follow_redirects=False)

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Mapping[str, Any] | None = None,
        json: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        request_headers = {"X-PropertyScope-Internal-Token": self._token}
        if headers:
            request_headers.update(
                {key: value for key, value in headers.items() if key in PROPAGATED_HEADERS}
            )
        try:
            return self._client.request(
                method,
                f"{self._origin}{path}",
                headers=request_headers,
                params=params,
                json=json,
                timeout=timeout,
            )
        except httpx.TransportError as exc:
            raise DependencyUnavailableError("Property data store is unavailable") from exc

    def ready(self) -> bool:
        try:
            return self._client.get(f"{self._origin}/health/ready", timeout=2).status_code == 200
        except httpx.TransportError:
            return False


class AiModeClient:
    """Feature-safe projection over shared AI-mode HTTP APIs."""

    def __init__(self, base_url: str, *, client: httpx.Client | None = None) -> None:
        self._origin = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=10, follow_redirects=False)

    def create_run(
        self, payload: Mapping[str, Any], headers: Mapping[str, str] | Headers
    ) -> httpx.Response:
        try:
            return self._client.post(
                f"{self._origin}/api/v1/agent-runs",
                json=dict(payload),
                headers={key: value for key, value in headers.items() if key in PROPAGATED_HEADERS},
            )
        except httpx.TransportError as exc:
            raise DependencyUnavailableError(
                "AI mode is unavailable; direct data operations remain usable"
            ) from exc

    def get(self, path: str, headers: Mapping[str, str] | Headers) -> httpx.Response:
        try:
            return self._client.get(
                f"{self._origin}{path}",
                headers={key: value for key, value in headers.items() if key in PROPAGATED_HEADERS},
            )
        except httpx.TransportError as exc:
            raise DependencyUnavailableError(
                "AI mode is unavailable; direct data operations remain usable"
            ) from exc
