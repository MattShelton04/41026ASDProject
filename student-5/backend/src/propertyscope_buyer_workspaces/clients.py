"""Injected HTTP boundary for the Student 5 database API."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

_INTERNAL_API = "/internal/buyer-workspaces/v1"
_TOKEN_HEADER = "X-PropertyScope-Internal-Token"
_REQUEST_ID_HEADER = "X-Request-ID"


class DatabaseUnavailableError(RuntimeError):
    """The database API could not be reached."""


class DatabaseProtocolError(RuntimeError):
    """The database API returned an unusable representation."""


@dataclass(frozen=True, slots=True)
class ClientResponse:
    status_code: int
    body: bytes
    headers: Mapping[str, str]

    def json(self) -> object:
        try:
            return json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DatabaseProtocolError("Database API returned invalid JSON") from exc


class HttpTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        params: Mapping[str, int] | None,
        json_body: Mapping[str, Any] | None,
        timeout_seconds: float,
    ) -> ClientResponse: ...


class BuyerStoreGateway(Protocol):
    def ready(self) -> bool: ...

    def list_cases(self, *, page: int, page_size: int, request_id: str) -> ClientResponse: ...

    def create_case(self, values: Mapping[str, Any], *, request_id: str) -> ClientResponse: ...

    def get_case(self, case_id: str, *, request_id: str) -> ClientResponse: ...

    def update_case(
        self, case_id: str, values: Mapping[str, Any], *, request_id: str
    ) -> ClientResponse: ...

    def delete_case(self, case_id: str, *, request_id: str) -> ClientResponse: ...

    def list_children(
        self, case_id: str, resource: str, *, page: int, page_size: int, request_id: str
    ) -> ClientResponse: ...

    def create_child(
        self, case_id: str, resource: str, values: Mapping[str, Any], *, request_id: str
    ) -> ClientResponse: ...

    def get_child(
        self, case_id: str, resource: str, child_id: str, *, request_id: str
    ) -> ClientResponse: ...

    def update_child(
        self,
        case_id: str,
        resource: str,
        child_id: str,
        values: Mapping[str, Any],
        *,
        request_id: str,
    ) -> ClientResponse: ...

    def delete_child(
        self, case_id: str, resource: str, child_id: str, *, request_id: str
    ) -> ClientResponse: ...


class UrllibTransport:
    """Small default transport; tests inject a deterministic implementation."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        params: Mapping[str, int] | None,
        json_body: Mapping[str, Any] | None,
        timeout_seconds: float,
    ) -> ClientResponse:
        if params:
            url = f"{url}?{urlencode(params)}"
        body = None if json_body is None else json.dumps(json_body).encode("utf-8")
        request_headers = dict(headers)
        request_headers["Accept"] = "application/json"
        if body is not None:
            request_headers["Content-Type"] = "application/json"
        outbound = Request(url, data=body, headers=request_headers, method=method)
        try:
            with urlopen(outbound, timeout=timeout_seconds) as response:
                return ClientResponse(
                    status_code=response.status,
                    body=response.read(),
                    headers=dict(response.headers.items()),
                )
        except HTTPError as error:
            try:
                return ClientResponse(
                    status_code=error.code,
                    body=error.read(),
                    headers=dict(error.headers.items()),
                )
            finally:
                error.close()
        except (URLError, TimeoutError, OSError) as exc:
            raise DatabaseUnavailableError("Buyer workspace database API is unavailable") from exc


class BuyerStoreClient:
    """Typed operations against the internal database API only."""

    def __init__(
        self,
        base_url: str,
        internal_token: str,
        *,
        transport: HttpTransport | None = None,
        timeout_seconds: float = 5,
    ) -> None:
        self._origin = base_url.rstrip("/")
        self._internal_token = internal_token
        self._transport = transport or UrllibTransport()
        self._timeout_seconds = timeout_seconds

    def ready(self) -> bool:
        try:
            response = self._transport.request(
                "GET",
                f"{self._origin}/health/ready",
                headers={},
                params=None,
                json_body=None,
                timeout_seconds=min(self._timeout_seconds, 2),
            )
        except DatabaseUnavailableError:
            return False
        return response.status_code == 200

    def list_cases(self, *, page: int, page_size: int, request_id: str) -> ClientResponse:
        return self._request(
            "GET",
            "/buyer-cases",
            request_id=request_id,
            params={"page": page, "page_size": page_size},
        )

    def create_case(self, values: Mapping[str, Any], *, request_id: str) -> ClientResponse:
        return self._request("POST", "/buyer-cases", request_id=request_id, json_body=values)

    def get_case(self, case_id: str, *, request_id: str) -> ClientResponse:
        return self._request("GET", f"/buyer-cases/{case_id}", request_id=request_id)

    def update_case(
        self, case_id: str, values: Mapping[str, Any], *, request_id: str
    ) -> ClientResponse:
        return self._request(
            "PUT", f"/buyer-cases/{case_id}", request_id=request_id, json_body=values
        )

    def delete_case(self, case_id: str, *, request_id: str) -> ClientResponse:
        return self._request("DELETE", f"/buyer-cases/{case_id}", request_id=request_id)

    def list_children(
        self, case_id: str, resource: str, *, page: int, page_size: int, request_id: str
    ) -> ClientResponse:
        return self._request(
            "GET",
            f"/buyer-cases/{case_id}/{resource}",
            request_id=request_id,
            params={"page": page, "page_size": page_size},
        )

    def create_child(
        self, case_id: str, resource: str, values: Mapping[str, Any], *, request_id: str
    ) -> ClientResponse:
        return self._request(
            "POST",
            f"/buyer-cases/{case_id}/{resource}",
            request_id=request_id,
            json_body=values,
        )

    def get_child(
        self, case_id: str, resource: str, child_id: str, *, request_id: str
    ) -> ClientResponse:
        return self._request(
            "GET", f"/buyer-cases/{case_id}/{resource}/{child_id}", request_id=request_id
        )

    def update_child(
        self,
        case_id: str,
        resource: str,
        child_id: str,
        values: Mapping[str, Any],
        *,
        request_id: str,
    ) -> ClientResponse:
        return self._request(
            "PUT",
            f"/buyer-cases/{case_id}/{resource}/{child_id}",
            request_id=request_id,
            json_body=values,
        )

    def delete_child(
        self, case_id: str, resource: str, child_id: str, *, request_id: str
    ) -> ClientResponse:
        return self._request(
            "DELETE", f"/buyer-cases/{case_id}/{resource}/{child_id}", request_id=request_id
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        request_id: str,
        params: Mapping[str, int] | None = None,
        json_body: Mapping[str, Any] | None = None,
    ) -> ClientResponse:
        return self._transport.request(
            method,
            f"{self._origin}{_INTERNAL_API}{path}",
            headers={
                _TOKEN_HEADER: self._internal_token,
                _REQUEST_ID_HEADER: request_id,
            },
            params=params,
            json_body=json_body,
            timeout_seconds=self._timeout_seconds,
        )
