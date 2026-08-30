"""Typed, bounded HTTP reads from Feature 1's public API.

This experimental client deliberately knows only the published HTTP contract.  It does
not import Feature 1 code, resolve arbitrary URLs, or receive database credentials.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

_DATASET_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,99}$")
_TARGET_FEATURE = re.compile(r"^feature-[1-5]$")
_ARTIFACT_PATH = re.compile(
    r"^/api/data-platform/v1/dataset-releases/"
    r"(?P<release_id>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/artifact$"
)
_FORWARDED_HEADERS = frozenset({"x-request-id", "x-agent-run-id", "traceparent", "idempotency-key"})


class Feature1ContractError(ValueError):
    """Feature 1 returned data that cannot satisfy its public contract."""


class Feature1HttpError(RuntimeError):
    """A bounded Feature 1 call failed."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class AcceptedRelease:
    """The immutable evidence needed to reconcile one accepted product."""

    release_id: uuid.UUID
    dataset_id: str
    target_feature: str
    release_version: str
    schema_version: str
    content_sha256: str
    record_count: int
    manifest: Mapping[str, Any]
    artifact_path: str

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> AcceptedRelease:
        release = payload.get("release")
        if not isinstance(release, Mapping):
            raise Feature1ContractError("accepted release response has no release object")
        try:
            release_id = uuid.UUID(str(release["id"]))
            dataset_id = str(release["dataset_id"])
            target_feature = str(release["target_feature"])
            release_version = str(release["release_version"])
            schema_version = str(release["schema_version"])
            content_sha256 = str(release["content_sha256"])
            record_count = int(release["record_count"])
            manifest = release["manifest_json"]
        except (KeyError, TypeError, ValueError) as exc:
            raise Feature1ContractError("accepted release evidence is malformed") from exc
        if not _DATASET_ID.fullmatch(dataset_id):
            raise Feature1ContractError("accepted release dataset ID is invalid")
        if not _TARGET_FEATURE.fullmatch(target_feature):
            raise Feature1ContractError("accepted release target feature is invalid")
        if not release_version or not schema_version:
            raise Feature1ContractError("accepted release version evidence is missing")
        if not re.fullmatch(r"[0-9a-f]{64}", content_sha256):
            raise Feature1ContractError("accepted release checksum is invalid")
        if record_count < 0 or not isinstance(manifest, Mapping):
            raise Feature1ContractError("accepted release manifest or count is invalid")
        if release.get("status") != "accepted":
            raise Feature1ContractError("accepted lookup did not return an accepted release")
        return cls(
            release_id=release_id,
            dataset_id=dataset_id,
            target_feature=target_feature,
            release_version=release_version,
            schema_version=schema_version,
            content_sha256=content_sha256,
            record_count=record_count,
            manifest=dict(manifest),
            artifact_path=(f"/api/data-platform/v1/dataset-releases/{release_id}/artifact"),
        )


class Feature1Client:
    """Small Feature 1 client suitable for dependency injection into a Flask app."""

    def __init__(
        self,
        origin: str,
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self.origin = _validated_origin(origin)
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 1.0)),
            follow_redirects=False,
        )

    def catalogue(self, *, headers: Mapping[str, str] | None = None) -> Mapping[str, Any]:
        payload = self._get_json("/api/data-platform/v1/data-products", headers=headers)
        items = payload.get("items")
        if not isinstance(items, list) or not isinstance(payload.get("count"), int):
            raise Feature1ContractError("data-product catalogue is malformed")
        return payload

    def accepted_release(
        self,
        dataset_id: str,
        target_feature: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> AcceptedRelease | None:
        _validate_dataset_target(dataset_id, target_feature)
        path = f"/api/data-platform/v1/data-products/{quote(dataset_id, safe='')}/accepted"
        try:
            response = self._client.get(
                self.origin + path,
                params={"target_feature": target_feature},
                headers=_safe_headers(headers),
                follow_redirects=False,
            )
        except httpx.TransportError as exc:
            raise Feature1HttpError(503, "Feature 1 is unavailable") from exc
        if response.status_code == 404:
            return None
        payload = _checked_json(response)
        accepted = AcceptedRelease.from_payload(payload)
        if accepted.dataset_id != dataset_id or accepted.target_feature != target_feature:
            raise Feature1ContractError("accepted lookup returned a different product")
        return accepted

    def report_section(
        self,
        property_ref: uuid.UUID,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        payload = self._get_json(
            f"/api/data-platform/v1/properties/{property_ref}/report-section",
            headers=headers,
        )
        if payload.get("schema_version") != "propertyscope.report-section.v1" or payload.get(
            "property_ref"
        ) != str(property_ref):
            raise Feature1ContractError("property report section is not contract-valid")
        return payload

    def property_search(
        self,
        query: str,
        *,
        limit: int = 25,
        headers: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        query = query.strip()
        if not 2 <= len(query) <= 200 or not 1 <= limit <= 100:
            raise ValueError("property search query or limit is outside contract bounds")
        try:
            response = self._client.get(
                self.origin + "/api/data-platform/v1/properties/search",
                params={"q": query, "state": "NSW", "limit": limit},
                headers=_safe_headers(headers),
                follow_redirects=False,
            )
        except httpx.TransportError as exc:
            raise Feature1HttpError(503, "Feature 1 is unavailable") from exc
        payload = _checked_json(response)
        if not isinstance(payload.get("items"), list):
            raise Feature1ContractError("property search page is malformed")
        return payload

    def sales_source_records(
        self,
        *,
        year: int,
        release_id: uuid.UUID | None = None,
        limit: int = 1_000,
        headers: Mapping[str, str] | None = None,
    ) -> Iterator[Mapping[str, Any]]:
        """Page accepted PSI facts while pinning every page to one release."""
        if not 1990 <= year <= 9999 or not 1 <= limit <= 5_000:
            raise ValueError("sales source-record page bounds are invalid")
        offset = 0
        pinned = release_id
        while True:
            params: dict[str, str | int] = {"year": year, "limit": limit, "offset": offset}
            if pinned is not None:
                params["release_id"] = str(pinned)
            try:
                response = self._client.get(
                    self.origin
                    + "/api/data-platform/v1/data-products/nsw-psi-sales/source-records",
                    params=params,
                    headers=_safe_headers(headers),
                    follow_redirects=False,
                )
            except httpx.TransportError as exc:
                raise Feature1HttpError(503, "Feature 1 is unavailable") from exc
            payload = _checked_json(response)
            release = payload.get("release")
            items = payload.get("items")
            if not isinstance(release, Mapping) or not isinstance(items, list):
                raise Feature1ContractError("sales source-record page is malformed")
            page_release = uuid.UUID(str(release.get("id")))
            if pinned is None:
                pinned = page_release
            elif page_release != pinned:
                raise Feature1ContractError("sales source-record release changed between pages")
            for item in items:
                if not isinstance(item, Mapping):
                    raise Feature1ContractError("sales source record is not an object")
                yield item
            next_offset = payload.get("next_offset")
            if next_offset is None:
                return
            if not isinstance(next_offset, int) or next_offset <= offset:
                raise Feature1ContractError("sales source-record pagination is invalid")
            offset = next_offset

    @contextmanager
    def stream_artifact(
        self,
        artifact_path: str,
        *,
        release_id: uuid.UUID,
        headers: Mapping[str, str] | None = None,
    ) -> Iterator[httpx.Response]:
        match = _ARTIFACT_PATH.fullmatch(artifact_path)
        if match is None or uuid.UUID(match.group("release_id")) != release_id:
            raise Feature1ContractError("artifact path is not bound to the published release")
        try:
            with self._client.stream(
                "GET",
                self.origin + artifact_path,
                headers=_safe_headers(headers),
                follow_redirects=False,
            ) as response:
                if 300 <= response.status_code < 400:
                    raise Feature1HttpError(
                        response.status_code, "artifact redirects are forbidden"
                    )
                if response.status_code >= 400:
                    raise Feature1HttpError(response.status_code, _response_detail(response))
                yield response
        except httpx.TransportError as exc:
            raise Feature1HttpError(503, "Feature 1 artifact is unavailable") from exc

    def _get_json(self, path: str, *, headers: Mapping[str, str] | None) -> Mapping[str, Any]:
        try:
            response = self._client.get(
                self.origin + path,
                headers=_safe_headers(headers),
                follow_redirects=False,
            )
        except httpx.TransportError as exc:
            raise Feature1HttpError(503, "Feature 1 is unavailable") from exc
        return _checked_json(response)


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
        raise ValueError("Feature 1 origin must be an HTTP origin without credentials or a path")
    return origin.rstrip("/")


def _validate_dataset_target(dataset_id: str, target_feature: str) -> None:
    if not _DATASET_ID.fullmatch(dataset_id):
        raise ValueError("dataset_id is invalid")
    if not _TARGET_FEATURE.fullmatch(target_feature):
        raise ValueError("target_feature is invalid")


def _safe_headers(headers: Mapping[str, str] | None) -> dict[str, str]:
    return {
        key: value for key, value in (headers or {}).items() if key.lower() in _FORWARDED_HEADERS
    }


def _checked_json(response: httpx.Response) -> Mapping[str, Any]:
    if 300 <= response.status_code < 400:
        raise Feature1HttpError(response.status_code, "redirects are forbidden")
    if response.status_code >= 400:
        raise Feature1HttpError(response.status_code, _response_detail(response))
    try:
        payload = response.json()
    except ValueError as exc:
        raise Feature1ContractError("Feature 1 returned invalid JSON") from exc
    if not isinstance(payload, Mapping):
        raise Feature1ContractError("Feature 1 response must be a JSON object")
    return payload


def _response_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"Feature 1 returned HTTP {response.status_code}"
    if isinstance(payload, Mapping):
        detail = payload.get("detail")
        if isinstance(detail, str) and detail:
            return detail
    return f"Feature 1 returned HTTP {response.status_code}"
