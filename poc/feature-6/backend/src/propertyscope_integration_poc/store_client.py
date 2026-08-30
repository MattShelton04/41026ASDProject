"""Credential-confined HTTP client for the POC's private database API."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import urlsplit

import httpx

from .publication_importer import (
    PublicationReceipt,
    PublicationRequest,
    StoredPublication,
)

_RESOURCES = frozenset({"market-cases", "saved-places", "site-reviews", "buyer-cases"})
_FORWARDED = frozenset({"x-request-id", "x-agent-run-id", "traceparent"})


class StoreHttpError(RuntimeError):
    def __init__(self, status_code: int, detail: str, *, request_id: str | None = None) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.request_id = request_id


class StoreHttpClient:
    """Implement PublicationStore and bounded CRUD over one fixed service origin."""

    def __init__(
        self,
        origin: str,
        token: str,
        *,
        client: httpx.Client | None = None,
        connect_timeout_seconds: float = 5.0,
        read_timeout_seconds: float = 14_400.0,
        write_timeout_seconds: float = 300.0,
        pool_timeout_seconds: float = 5.0,
    ) -> None:
        self.origin = _validated_origin(origin)
        if not token:
            raise ValueError("store token must not be empty")
        self._token = token
        timeouts = {
            "connect": connect_timeout_seconds,
            "read": read_timeout_seconds,
            "write": write_timeout_seconds,
            "pool": pool_timeout_seconds,
        }
        if any(value <= 0 for value in timeouts.values()):
            raise ValueError("store HTTP timeouts must be positive")
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(
                connect=connect_timeout_seconds,
                read=read_timeout_seconds,
                write=write_timeout_seconds,
                pool=pool_timeout_seconds,
            ),
            follow_redirects=False,
        )

    @property
    def timeout_configuration(self) -> httpx.Timeout:
        """Expose effective deadlines for readiness diagnostics and deterministic tests."""
        return self._client.timeout

    def close(self) -> None:
        """Release the owned HTTP connection pool."""
        if self._owns_client:
            self._client.close()

    def ready(self, *, headers: Mapping[str, str] | None = None) -> bool:
        try:
            response = self._client.get(
                self.origin + "/health/ready",
                headers=_headers(self._token, headers),
                follow_redirects=False,
            )
        except httpx.TransportError:
            return False
        return response.status_code == 200

    def find_publication(
        self, target_feature: str, idempotency_key: str
    ) -> StoredPublication | None:
        if not re.fullmatch(r"[A-Za-z0-9._:-]{8,200}", idempotency_key):
            # The provider contract permits broader keys, but this read route is a path.
            # Re-posting remains safe because the database transaction owns replay detection.
            return None
        path = f"/internal/v1/imports/{target_feature}/{idempotency_key}"
        try:
            payload = self._request("GET", path)
        except StoreHttpError as exc:
            if exc.status_code == 404:
                return None
            raise
        request_value = payload.get("request")
        receipt_value = payload.get("receipt")
        if not isinstance(request_value, Mapping) or not isinstance(receipt_value, Mapping):
            raise StoreHttpError(502, "store publication lookup is malformed")
        callback = {
            key: request_value[key]
            for key in (
                "release_id",
                "dataset_id",
                "schema_version",
                "content_sha256",
                "record_count",
                "manifest",
                "artifact_path",
                "idempotency_key",
            )
            if key in request_value
        }
        publication = PublicationRequest.from_callback(
            callback,
            header_idempotency_key=str(request_value.get("idempotency_key", "")),
        )
        receipt = PublicationReceipt.from_mapping(receipt_value)
        return StoredPublication.from_request(publication, receipt)

    def import_release_atomic(
        self,
        publication: PublicationRequest,
        records: Iterable[Mapping[str, Any]],
    ) -> Mapping[str, Any]:
        publication_payload = {
            "release_id": str(publication.release_id),
            "dataset_id": publication.dataset_id,
            "target_feature": publication.target_feature,
            "schema_version": publication.schema_version,
            "content_sha256": publication.content_sha256,
            "record_count": publication.record_count,
            "manifest": dict(publication.manifest),
            "artifact_path": publication.artifact_path,
            "idempotency_key": publication.idempotency_key,
        }

        def content() -> Iterable[bytes]:
            yield _json_line({"publication": publication_payload})
            for record in records:
                yield _json_line(record)

        headers = _headers(self._token, None)
        headers["Content-Type"] = "application/x-ndjson"
        try:
            response = self._client.post(
                self.origin + "/internal/v1/imports",
                content=content(),
                headers=headers,
                follow_redirects=False,
            )
        except httpx.TransportError as exc:
            raise StoreHttpError(503, "POC database service is unavailable") from exc
        if response.status_code >= 300:
            if response.status_code < 400:
                raise StoreHttpError(response.status_code, "store redirects are forbidden")
            raise _store_error(response)
        try:
            payload = response.json()
        except ValueError as exc:
            raise StoreHttpError(502, "store returned invalid JSON") from exc
        if not isinstance(payload, Mapping):
            raise StoreHttpError(502, "store response must be a JSON object")
        return payload

    def list_imports(self, *, headers: Mapping[str, str] | None = None) -> Mapping[str, Any]:
        return self._request("GET", "/internal/v1/imports", headers=headers)

    def collection(
        self,
        resource: str,
        *,
        method: str = "GET",
        body: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        _resource(resource)
        return self._request(method, f"/internal/v1/{resource}", json=body, headers=headers)

    def mutate_item(
        self,
        resource: str,
        item_id: uuid.UUID,
        *,
        method: str,
        body: Mapping[str, Any] | None = None,
        expected_version: int | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any] | None:
        _resource(resource)
        params = (
            {"expected_version": expected_version}
            if method == "DELETE" and expected_version is not None
            else None
        )
        result = self._request(
            method,
            f"/internal/v1/{resource}/{item_id}",
            json=body,
            params=params,
            headers=headers,
            allow_empty=method == "DELETE",
        )
        return None if method == "DELETE" else result

    def market_summary(
        self, case_id: uuid.UUID, *, headers: Mapping[str, str] | None = None
    ) -> Mapping[str, Any]:
        return self._request("GET", f"/internal/v1/market-cases/{case_id}/summary", headers=headers)

    def place_summary(
        self,
        postcode: str,
        *,
        latitude: float | None = None,
        longitude: float | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        params: dict[str, float] = {}
        if latitude is not None and longitude is not None:
            params = {"latitude": latitude, "longitude": longitude}
        return self._request(
            "GET", f"/internal/v1/places/{postcode}/summary", params=params, headers=headers
        )

    def site_evidence(
        self, review_id: uuid.UUID, *, headers: Mapping[str, str] | None = None
    ) -> Mapping[str, Any]:
        return self._request(
            "GET", f"/internal/v1/site-reviews/{review_id}/evidence", headers=headers
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        allow_empty: bool = False,
    ) -> Mapping[str, Any]:
        try:
            response = self._client.request(
                method,
                self.origin + path,
                json=json,
                params=params,
                headers=_headers(self._token, headers),
                follow_redirects=False,
            )
        except httpx.TransportError as exc:
            raise StoreHttpError(503, "POC database service is unavailable") from exc
        if 300 <= response.status_code < 400:
            raise StoreHttpError(response.status_code, "store redirects are forbidden")
        if response.status_code >= 400:
            raise _store_error(response)
        if response.status_code == 204 and allow_empty:
            return {}
        try:
            payload = response.json()
        except ValueError as exc:
            raise StoreHttpError(502, "store returned invalid JSON") from exc
        if not isinstance(payload, Mapping):
            raise StoreHttpError(502, "store response must be a JSON object")
        return payload


def _validated_origin(origin: str) -> str:
    parsed = urlsplit(origin)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("store origin must be an HTTP origin")
    return origin.rstrip("/")


def _resource(resource: str) -> None:
    if resource not in _RESOURCES:
        raise ValueError("resource is not allowlisted")


def _headers(token: str, supplied: Mapping[str, str] | None) -> dict[str, str]:
    values = {key: value for key, value in (supplied or {}).items() if key.lower() in _FORWARDED}
    values["Authorization"] = f"Bearer {token}"
    return values


def _store_error(response: httpx.Response) -> StoreHttpError:
    request_id = response.headers.get("X-Request-ID")
    try:
        payload = response.json()
    except ValueError:
        payload = None
    detail = (
        str(payload.get("detail"))
        if isinstance(payload, Mapping) and payload.get("detail")
        else f"store returned HTTP {response.status_code}"
    )
    if isinstance(payload, Mapping) and isinstance(payload.get("request_id"), str):
        request_id = str(payload["request_id"])
    return StoreHttpError(response.status_code, detail, request_id=request_id)


def _json_line(value: Mapping[str, Any]) -> bytes:
    try:
        return (
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
            + b"\n"
        )
    except (TypeError, ValueError) as exc:
        raise StoreHttpError(422, "publication record is not canonical JSON") from exc
