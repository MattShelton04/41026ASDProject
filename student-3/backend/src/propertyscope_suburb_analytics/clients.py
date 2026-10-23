"""Bounded HTTP clients for the database and shared AI-mode boundaries."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import httpx

from shared_contracts import (
    REQUEST_ID_HEADER,
    TRACEPARENT_HEADER,
    is_valid_request_id,
    is_valid_traceparent,
)
from shared_contracts.multi_agent import MULTI_AGENT_API_PREFIX


class ServiceError(RuntimeError):
    def __init__(self, status: int, payload: dict[str, Any]) -> None:
        super().__init__(str(payload.get("code", "dependency_error")))
        self.status, self.payload = status, payload


class HttpClient:
    def __init__(self, base_url: str, timeout: float = 4.0, *, service_token: str = "") -> None:
        self.base_url, self.timeout = base_url.rstrip("/"), timeout
        self._service_token = service_token

    def request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        data = json.dumps(payload).encode() if payload is not None else None
        request = Request(  # noqa: S310 - base_url is a configured http(s) service URL, never user input
            self.base_url + path,
            data=data,
            method=method,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                **(
                    {"X-PropertyScope-AI-Token": self._service_token} if self._service_token else {}
                ),
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - the request targets the configured service URL above
                body = response.read(16_777_217)
                if len(body) > 16_777_216:
                    raise ServiceError(502, {"code": "dependency_response_too_large"})
                result = json.loads(body)
                if not isinstance(result, dict):
                    raise ServiceError(502, {"code": "invalid_dependency_response"})
                return result
        except HTTPError as exc:
            try:
                body = json.loads(exc.read(65_536))
            except json.JSONDecodeError:
                body = {"code": "dependency_error"}
            raise ServiceError(exc.code, body) from exc
        except (URLError, TimeoutError) as exc:
            raise ServiceError(503, {"code": "dependency_unavailable"}) from exc


class MultiAgentUnavailableError(RuntimeError):
    """The host Multi-Agent Server is unconfigured, unreachable or rejected our credential."""


def forwarded_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Return validated correlation headers and no browser credentials."""
    result: dict[str, str] = {}
    request_id = headers.get(REQUEST_ID_HEADER, "").strip()
    traceparent = headers.get(TRACEPARENT_HEADER, "").strip()
    if request_id and is_valid_request_id(request_id):
        result[REQUEST_ID_HEADER] = request_id
    if traceparent and is_valid_traceparent(traceparent):
        result[TRACEPARENT_HEADER] = traceparent
    return result


class MultiAgentClient:
    """Fixed-operation HTTP client for Feature 3's shared multi-agent boundary."""

    API_PREFIX = MULTI_AGENT_API_PREFIX
    UNAVAILABLE_DETAIL = (
        "The Multi-Agent Server is unavailable; saved suburb comparisons and trends still work"
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
            timeout=httpx.Timeout(10.0, connect=3.0), follow_redirects=False
        )

    def available(self) -> bool:
        if not self._token:
            return False
        try:
            response = self._client.get(f"{self._origin}/health", timeout=httpx.Timeout(1.5))
        except httpx.HTTPError:
            return False
        return response.status_code < 400

    def template(self, template_id: str, headers: Mapping[str, str]) -> httpx.Response:
        return self._send("GET", f"/templates/{template_id}", headers)

    def create_run(self, payload: Mapping[str, Any], headers: Mapping[str, str]) -> httpx.Response:
        return self._send("POST", "/runs", headers, json=dict(payload))

    def list_runs(
        self, params: Mapping[str, str | int], headers: Mapping[str, str]
    ) -> httpx.Response:
        return self._send("GET", "/runs", headers, params=params)

    def get_run(self, run_id: uuid.UUID, headers: Mapping[str, str]) -> httpx.Response:
        return self._send("GET", f"/runs/{run_id}", headers)

    def decide(
        self,
        run_id: uuid.UUID,
        payload: Mapping[str, Any],
        headers: Mapping[str, str],
    ) -> httpx.Response:
        return self._send("POST", f"/runs/{run_id}/decision", headers, json=dict(payload))

    def cancel(
        self,
        run_id: uuid.UUID,
        payload: Mapping[str, Any] | None,
        headers: Mapping[str, str],
    ) -> httpx.Response:
        body = dict(payload) if payload is not None else None
        return self._send("POST", f"/runs/{run_id}/cancel", headers, json=body)

    def history(
        self,
        run_id: uuid.UUID,
        headers: Mapping[str, str],
        params: Mapping[str, str | int] | None = None,
    ) -> httpx.Response:
        return self._send("GET", f"/runs/{run_id}/history", headers, params=params or None)

    def _send(
        self,
        method: str,
        path: str,
        headers: Mapping[str, str],
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
            raise MultiAgentUnavailableError(self.UNAVAILABLE_DETAIL)
        return response
