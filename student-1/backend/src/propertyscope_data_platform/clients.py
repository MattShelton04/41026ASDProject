"""Injected HTTP clients for database-service and AI-mode boundaries."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError
from werkzeug.datastructures import Headers

from propertyscope_data_platform.domain import (
    ConsumerImportAcknowledgement,
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
        request_options: dict[str, Any] = {
            "headers": request_headers,
            "params": params,
            "json": json,
        }
        if timeout is not None:
            request_options["timeout"] = timeout
        try:
            return self._client.request(
                method,
                f"{self._origin}{path}",
                **request_options,
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

    def cancel_run(self, run_id: str, headers: Mapping[str, str] | Headers) -> httpx.Response:
        """Request cancellation without exposing a general upstream POST proxy."""
        try:
            return self._client.post(
                f"{self._origin}/api/v1/agent-runs/{run_id}/cancel",
                headers=forwarded_headers(headers),
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
    status_path: str | None = None

    def __post_init__(self) -> None:
        try:
            origin = urlsplit(self.base_url)
            _ = origin.port
        except ValueError as exc:
            raise ValueError("consumer base_url must be an HTTP(S) origin") from exc
        if (
            origin.scheme not in {"http", "https"}
            or not origin.netloc
            or origin.hostname is None
            or origin.username is not None
            or origin.password is not None
            or origin.path
            or origin.query
            or origin.fragment
        ):
            raise ValueError("consumer base_url must be an HTTP(S) origin")
        if not self.import_path.startswith("/api/") or any(
            marker in self.import_path for marker in ("?", "#", "..", "\\")
        ):
            raise ValueError("consumer import_path must be a fixed API path")
        status_path = self.status_path or f"{self.import_path}/{{operation_id}}"
        if (
            not status_path.startswith("/api/")
            or status_path.count("{operation_id}") != 1
            or any(marker in status_path for marker in ("?", "#", "..", "\\"))
        ):
            raise ValueError("consumer status_path must bind one operation id on a fixed API path")
        object.__setattr__(self, "status_path", status_path)


@dataclass(frozen=True)
class ConsumerDeliveryOutcome:
    """One bounded consumer exchange; absent IDs are never synthesized."""

    status: str
    consumer_operation_id: str | None = None
    receipt: PublicationReceiptResult | None = None
    error: SafeError | None = None


class ConsumerImportClient:
    """Call only fixed target-feature import routes and return typed safe receipts."""

    CONNECT_TIMEOUT_SECONDS = 5.0
    STATUS_TIMEOUT_SECONDS = 5.0
    MAX_RESPONSE_BYTES = 64 * 1024

    def __init__(
        self,
        endpoints: Mapping[str, ConsumerEndpoint],
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self._endpoints = dict(endpoints)
        self._client = client or httpx.Client(
            timeout=self.CONNECT_TIMEOUT_SECONDS, follow_redirects=False
        )

    def connect(
        self,
        target_feature: str,
        publication: ConsumerPublicationRequest,
        headers: Mapping[str, str] | Headers,
    ) -> ConsumerDeliveryOutcome:
        endpoint = self._endpoints.get(target_feature)
        if endpoint is None:
            raise ValueError(f"target feature is not registered for publication: {target_feature}")
        safe_headers = forwarded_headers(headers)
        safe_headers["Idempotency-Key"] = publication.idempotency_key
        try:
            response = self._bounded_request(
                "POST",
                f"{endpoint.base_url.rstrip('/')}{endpoint.import_path}",
                headers=safe_headers,
                json=publication.model_dump(mode="json"),
                timeout=self.CONNECT_TIMEOUT_SECONDS,
            )
        except httpx.TransportError:
            return self._failed("consumer_unavailable", "Consumer is unavailable", retryable=True)
        if isinstance(response, ConsumerDeliveryOutcome):
            return response
        return self._response_outcome(response, publication)

    def poll(
        self,
        target_feature: str,
        consumer_operation_id: str,
        publication: ConsumerPublicationRequest,
        headers: Mapping[str, str] | Headers,
    ) -> ConsumerDeliveryOutcome:
        endpoint = self._endpoints.get(target_feature)
        if endpoint is None:
            raise ValueError(f"target feature is not registered for publication: {target_feature}")
        if endpoint.status_path is None:
            raise AssertionError("validated consumer endpoint has no status path")
        if not consumer_operation_id or any(
            marker in consumer_operation_id for marker in ("/", "\\", "?", "#", "..")
        ):
            return self._failed("consumer_operation_invalid", "Consumer operation id is unsafe")
        path = endpoint.status_path.replace("{operation_id}", consumer_operation_id)
        try:
            response = self._bounded_request(
                "GET",
                f"{endpoint.base_url.rstrip('/')}{path}",
                headers=forwarded_headers(headers),
                timeout=self.STATUS_TIMEOUT_SECONDS,
            )
        except httpx.TransportError:
            return self._failed(
                "consumer_status_unavailable", "Consumer status is unavailable", retryable=True
            )
        if isinstance(response, ConsumerDeliveryOutcome):
            return response
        outcome = self._response_outcome(response, publication, allow_legacy_receipt=False)
        if (
            outcome.consumer_operation_id is not None
            and outcome.consumer_operation_id != consumer_operation_id
        ):
            return self._failed(
                "consumer_evidence_mismatch", "Consumer status operation id changed"
            )
        return outcome

    def _bounded_request(
        self, method: str, url: str, **kwargs: Any
    ) -> httpx.Response | ConsumerDeliveryOutcome:
        bounded_headers = dict(kwargs.pop("headers", {}))
        bounded_headers.setdefault("Accept-Encoding", "identity")
        kwargs["headers"] = bounded_headers
        with self._client.stream(method, url, **kwargs) as response:
            if response.is_redirect:
                return self._failed("consumer_redirect_rejected", "Consumer redirects are rejected")
            content_encoding = response.headers.get("Content-Encoding", "identity").lower().strip()
            if content_encoding not in {"", "identity"}:
                return self._failed(
                    "consumer_response_encoding_rejected",
                    "Compressed consumer control responses are rejected",
                )
            declared_length = response.headers.get("Content-Length")
            if declared_length is not None:
                try:
                    content_length = int(declared_length)
                    if content_length < 0:
                        return self._failed(
                            "consumer_response_invalid", "Consumer Content-Length is invalid"
                        )
                    if content_length > self.MAX_RESPONSE_BYTES:
                        return self._failed(
                            "consumer_response_too_large", "Consumer response exceeds limit"
                        )
                except ValueError:
                    return self._failed(
                        "consumer_response_invalid", "Consumer Content-Length is invalid"
                    )
            content = bytearray()
            chunks = (response.content,) if response.is_stream_consumed else response.iter_raw()
            for chunk in chunks:
                if len(content) + len(chunk) > self.MAX_RESPONSE_BYTES:
                    return self._failed(
                        "consumer_response_too_large", "Consumer response exceeds limit"
                    )
                content.extend(chunk)
            return httpx.Response(
                response.status_code,
                headers=response.headers,
                content=bytes(content),
                request=response.request,
            )

    def publish(
        self,
        target_feature: str,
        publication: ConsumerPublicationRequest,
        headers: Mapping[str, str] | Headers,
    ) -> PublicationReceiptResult:
        """Compatibility helper for bounded consumers that return a final receipt immediately."""
        outcome = self.connect(target_feature, publication, headers)
        if outcome.receipt is not None:
            return outcome.receipt
        raise DependencyUnavailableError(
            outcome.error.message if outcome.error else "Consumer import remains asynchronous"
        )

    def _response_outcome(
        self,
        response: httpx.Response,
        publication: ConsumerPublicationRequest,
        *,
        allow_legacy_receipt: bool = True,
    ) -> ConsumerDeliveryOutcome:
        if response.is_redirect:
            return self._failed("consumer_redirect_rejected", "Consumer redirects are rejected")
        if len(response.content) > self.MAX_RESPONSE_BYTES:
            return self._failed("consumer_response_too_large", "Consumer response exceeds limit")
        try:
            payload = response.json()
        except ValueError:
            return self._failed("consumer_response_invalid", "Consumer response is not JSON")
        operation_payload = payload.get("operation") if isinstance(payload, dict) else None
        candidate = operation_payload if isinstance(operation_payload, dict) else payload
        try:
            acknowledgement = ConsumerImportAcknowledgement.model_validate(candidate)
        except ValidationError:
            acknowledgement = None
        if acknowledgement is not None:
            if not self._matches_acknowledgement(acknowledgement, publication):
                return self._failed(
                    "consumer_evidence_mismatch", "Consumer operation evidence does not match"
                )
            if (
                acknowledgement.status in {"queued", "running", "accepted"}
                and response.status_code >= 400
            ):
                return self._failed(
                    "consumer_response_invalid", "Consumer status conflicts with HTTP status"
                )
            return ConsumerDeliveryOutcome(
                status=acknowledgement.status,
                consumer_operation_id=acknowledgement.consumer_operation_id,
                receipt=acknowledgement.receipt(),
                error=acknowledgement.error,
            )
        if allow_legacy_receipt:
            try:
                receipt = PublicationReceiptResult.model_validate(payload)
            except ValidationError:
                receipt = None
            if receipt is not None:
                if not self._matches_publication(receipt, publication, response.status_code):
                    return self._failed(
                        "consumer_evidence_mismatch",
                        "Consumer receipt does not match the published release",
                    )
                return ConsumerDeliveryOutcome(
                    status=receipt.status,
                    consumer_operation_id=receipt.consumer_operation_id,
                    receipt=receipt,
                    error=receipt.error,
                )
        return self._failed("consumer_response_invalid", "Consumer response is contract-invalid")

    @staticmethod
    def _matches_acknowledgement(
        result: ConsumerImportAcknowledgement, publication: ConsumerPublicationRequest
    ) -> bool:
        return (
            str(result.release_id) == str(publication.release_id)
            and result.dataset_id == publication.dataset_id
            and result.target_feature == publication.manifest.get("target_feature")
            and result.schema_version == publication.schema_version
            and result.content_sha256 == publication.content_sha256
            and result.record_count == publication.record_count
        )

    @staticmethod
    def _matches_publication(
        result: PublicationReceiptResult,
        publication: ConsumerPublicationRequest,
        status_code: int,
    ) -> bool:
        if (
            result.schema_version != publication.schema_version
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
    def _failed(code: str, message: str, *, retryable: bool = False) -> ConsumerDeliveryOutcome:
        return ConsumerDeliveryOutcome(
            status="failed",
            error=SafeError(code=code, message=message, retryable=retryable),
        )
