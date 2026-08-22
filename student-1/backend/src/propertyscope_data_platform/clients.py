"""Injected HTTP clients for database-service and AI-mode boundaries."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import ValidationError
from werkzeug.datastructures import Headers

from propertyscope_data_platform.domain import (
    ConsumerPublicationRequest,
    PublicationReceiptResult,
    SafeError,
)
from propertyscope_data_platform.http_headers import forwarded_headers


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
            request_headers.update(forwarded_headers(headers))
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
                headers=forwarded_headers(headers),
            )
        except httpx.TransportError as exc:
            raise DependencyUnavailableError(
                "AI mode is unavailable; direct data operations remain usable"
            ) from exc

    def get(
        self,
        path: str,
        headers: Mapping[str, str] | Headers,
        *,
        params: Mapping[str, Any] | None = None,
    ) -> httpx.Response:
        try:
            return self._client.get(
                f"{self._origin}{path}",
                headers=forwarded_headers(headers),
                params=params,
            )
        except httpx.TransportError as exc:
            raise DependencyUnavailableError(
                "AI mode is unavailable; direct data operations remain usable"
            ) from exc


@dataclass(frozen=True)
class ConsumerEndpoint:
    """One code-owned consumer route; release data can never select a URL or path."""

    base_url: str
    import_path: str

    def __post_init__(self) -> None:
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("consumer base_url must be an HTTP origin")
        if not self.import_path.startswith("/api/") or any(
            marker in self.import_path for marker in ("?", "#", "..", "\\")
        ):
            raise ValueError("consumer import_path must be a fixed API path")


class ConsumerImportClient:
    """Call only fixed target-feature import routes and return typed safe receipts."""

    def __init__(
        self,
        endpoints: Mapping[str, ConsumerEndpoint],
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self._endpoints = dict(endpoints)
        self._client = client or httpx.Client(timeout=10, follow_redirects=False)

    def publish(
        self,
        target_feature: str,
        publication: ConsumerPublicationRequest,
        headers: Mapping[str, str] | Headers,
    ) -> PublicationReceiptResult:
        endpoint = self._endpoints.get(target_feature)
        if endpoint is None:
            raise ValueError(f"target feature is not registered for publication: {target_feature}")
        safe_headers = forwarded_headers(headers)
        safe_headers["Idempotency-Key"] = publication.idempotency_key
        try:
            response = self._client.post(
                f"{endpoint.base_url.rstrip('/')}{endpoint.import_path}",
                headers=safe_headers,
                json=publication.model_dump(mode="json"),
            )
        except httpx.TransportError:
            return self._failed(publication, "consumer_unavailable", "Consumer is unavailable")
        try:
            payload = response.json()
            try:
                result = PublicationReceiptResult.model_validate(payload)
            except ValidationError:
                result = None
            if result is not None:
                if not self._matches_publication(result, publication, response.status_code):
                    return self._failed(
                        publication,
                        "consumer_evidence_mismatch",
                        "Consumer receipt does not match the published release",
                    )
                return result
            if response.status_code < 400:
                return self._failed(
                    publication,
                    "consumer_response_invalid",
                    "Consumer returned an invalid publication receipt",
                )
            code = (
                str(payload.get("code", "consumer_rejected"))
                if isinstance(payload, dict)
                else "consumer_rejected"
            )
        except (ValueError, ValidationError):
            code = "consumer_response_invalid"
        message = (
            "Consumer rejected the release"
            if response.status_code < 500
            else "Consumer import failed"
        )
        return self._failed(publication, code, message)

    @staticmethod
    def _matches_publication(
        result: PublicationReceiptResult,
        publication: ConsumerPublicationRequest,
        status_code: int,
    ) -> bool:
        if (
            result.consumer_operation_id != publication.idempotency_key
            or result.schema_version != publication.schema_version
            or result.content_sha256 != publication.content_sha256
            or result.rows_received > publication.record_count
        ):
            return False
        if result.status == "accepted":
            return (
                status_code < 400
                and result.rows_received == publication.record_count
                and result.rows_accepted == publication.record_count
                and result.rows_rejected == 0
            )
        return True

    @staticmethod
    def _failed(
        publication: ConsumerPublicationRequest, code: str, message: str
    ) -> PublicationReceiptResult:
        return PublicationReceiptResult(
            consumer_operation_id=publication.idempotency_key,
            status="failed" if code != "consumer_rejected" else "rejected",
            schema_version=publication.schema_version,
            content_sha256=publication.content_sha256,
            rows_received=0,
            rows_accepted=0,
            rows_rejected=0,
            error=SafeError(code=code, message=message, retryable=code == "consumer_unavailable"),
        )
