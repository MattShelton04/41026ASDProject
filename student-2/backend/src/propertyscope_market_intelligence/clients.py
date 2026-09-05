"""Injected HTTP clients for Feature 2's service boundaries."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

import httpx


class DependencyUnavailableError(RuntimeError):
    """A dependency could not be reached safely."""


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
                "AI mode is unavailable; market-case CRUD and summaries remain usable"
            ) from exc
