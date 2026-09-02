"""Bounded HTTP clients for the database and shared AI-mode boundaries."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ServiceError(RuntimeError):
    def __init__(self, status: int, payload: dict[str, Any]) -> None:
        super().__init__(str(payload.get("code", "dependency_error")))
        self.status, self.payload = status, payload


class HttpClient:
    def __init__(self, base_url: str, timeout: float = 4.0) -> None:
        self.base_url, self.timeout = base_url.rstrip("/"), timeout

    def request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        data = json.dumps(payload).encode() if payload is not None else None
        request = Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read(1_048_576))
        except HTTPError as exc:
            try:
                body = json.loads(exc.read(65_536))
            except json.JSONDecodeError:
                body = {"code": "dependency_error"}
            raise ServiceError(exc.code, body) from exc
        except (URLError, TimeoutError) as exc:
            raise ServiceError(503, {"code": "dependency_unavailable"}) from exc
