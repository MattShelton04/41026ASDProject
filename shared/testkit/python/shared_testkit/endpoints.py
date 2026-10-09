"""HTTP client and assertions for endpoint tests against a running service.

Endpoint tests exercise a deployed backend (for example a Compose stack started by a
``student-N.yml`` workflow) instead of an in-process application. They are opt-in: the
base URL comes from ``PROPERTYSCOPE_ENDPOINT_BASE_URL`` and tests are skipped when it is
unset, so default ``pytest`` and ``check.py`` runs stay Docker-free.

The client is deliberately small and domain-neutral:

* every request carries a fresh ``X-Request-ID`` so a failure can be traced in the
  service logs, following the shared correlation convention;
* timeouts are bounded, and only connection failures (where no request reached the
  service) are retried, so non-idempotent calls are never repeated;
* :meth:`EndpointClient.wait_until_ready` absorbs container start-up by polling a health
  route through connection errors and ``5xx`` responses until a deadline.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Mapping
from types import TracebackType
from typing import Any, Self
from urllib.parse import urlsplit

import httpx

from shared_contracts import (
    PROBLEM_DETAIL_MEDIA_TYPE,
    REQUEST_ID_HEADER,
    ProblemDetail,
    is_valid_request_id,
)

ENDPOINT_BASE_URL_ENV = "PROPERTYSCOPE_ENDPOINT_BASE_URL"
ENDPOINT_READY_PATH_ENV = "PROPERTYSCOPE_ENDPOINT_READY_PATH"
ENDPOINT_READY_TIMEOUT_ENV = "PROPERTYSCOPE_ENDPOINT_READY_TIMEOUT"
ENDPOINT_MARKER = "endpoint"
DEFAULT_READY_PATH = "/health/ready"
DEFAULT_READY_TIMEOUT_SECONDS = 60.0
DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=3.0)
DEFAULT_CONNECT_RETRIES = 3
JSON_MEDIA_TYPE = "application/json"
_BODY_EXCERPT_CHARS = 500


class EndpointConfigurationError(ValueError):
    """The endpoint-test environment is set but unusable."""


class EndpointNotReadyError(RuntimeError):
    """The service did not become ready before the readiness deadline."""


def endpoint_base_url(environ: Mapping[str, str]) -> str | None:
    """Return the configured service origin without a trailing slash, or ``None``.

    A blank value counts as unset. A value that is not an absolute ``http(s)`` URL is a
    configuration error rather than a reason to skip, so a typo cannot silently turn a
    CI endpoint run into a no-op.
    """
    raw = environ.get(ENDPOINT_BASE_URL_ENV, "").strip()
    if not raw:
        return None
    parts = urlsplit(raw)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise EndpointConfigurationError(
            f"{ENDPOINT_BASE_URL_ENV} must be an absolute http(s) URL, got {raw!r}"
        )
    if parts.query or parts.fragment:
        raise EndpointConfigurationError(
            f"{ENDPOINT_BASE_URL_ENV} must not contain a query or fragment"
        )
    return raw.rstrip("/")


def endpoint_ready_path(environ: Mapping[str, str]) -> str:
    """Return the readiness route polled before the first endpoint test."""
    path = environ.get(ENDPOINT_READY_PATH_ENV, "").strip() or DEFAULT_READY_PATH
    if not path.startswith("/"):
        raise EndpointConfigurationError(f"{ENDPOINT_READY_PATH_ENV} must start with '/'")
    return path


def endpoint_ready_timeout(environ: Mapping[str, str]) -> float:
    """Return the bounded readiness deadline in seconds."""
    raw = environ.get(ENDPOINT_READY_TIMEOUT_ENV, "").strip()
    if not raw:
        return DEFAULT_READY_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError as exc:
        raise EndpointConfigurationError(f"{ENDPOINT_READY_TIMEOUT_ENV} must be a number") from exc
    if not 0 < value <= 600:
        raise EndpointConfigurationError(f"{ENDPOINT_READY_TIMEOUT_ENV} must be within (0, 600]")
    return value


def _media_type(response: httpx.Response) -> str:
    content_type = str(response.headers.get("content-type", ""))
    return content_type.split(";", 1)[0].strip().lower()


def _describe(response: httpx.Response) -> str:
    request = response.request
    body = response.text[:_BODY_EXCERPT_CHARS]
    return (
        f"{request.method} {request.url} -> {response.status_code} "
        f"({_media_type(response) or 'no content-type'}; "
        f"{REQUEST_ID_HEADER}={request.headers.get(REQUEST_ID_HEADER, '-')}): {body}"
    )


def expect_status(response: httpx.Response, status: int) -> httpx.Response:
    """Fail with the method, URL, request ID and a body excerpt when the status differs."""
    if response.status_code != status:
        raise AssertionError(f"expected HTTP {status}, got {_describe(response)}")
    return response


def expect_json(response: httpx.Response, *, status: int = 200) -> dict[str, Any]:
    """Assert a JSON object response with the expected status and return its body."""
    expect_status(response, status)
    if _media_type(response) != JSON_MEDIA_TYPE:
        raise AssertionError(f"expected {JSON_MEDIA_TYPE}, got {_describe(response)}")
    try:
        body: object = response.json()
    except ValueError as exc:
        raise AssertionError(f"response is not valid JSON: {_describe(response)}") from exc
    if not isinstance(body, dict):
        raise AssertionError(f"expected a JSON object, got {_describe(response)}")
    return body


def expect_problem(
    response: httpx.Response,
    *,
    status: int,
    code: str,
    request_id: str | None = None,
) -> ProblemDetail:
    """Assert a shared Problem Details error and return the validated contract.

    When ``request_id`` is given, the problem must echo it so failures stay traceable.
    """
    expect_status(response, status)
    if _media_type(response) != PROBLEM_DETAIL_MEDIA_TYPE:
        raise AssertionError(f"expected {PROBLEM_DETAIL_MEDIA_TYPE}, got {_describe(response)}")
    problem = ProblemDetail.model_validate(response.json())
    if problem.status != status:
        raise AssertionError(f"problem status {problem.status} does not match HTTP {status}")
    if problem.code != code:
        raise AssertionError(f"expected problem code {code!r}, got {problem.code!r}")
    if request_id is not None and problem.request_id != request_id:
        raise AssertionError(
            f"problem request_id {problem.request_id!r} does not echo {request_id!r}"
        )
    return problem


class EndpointClient:
    """A bounded ``httpx`` client for one running service origin."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        connect_retries: int = DEFAULT_CONNECT_RETRIES,
        retry_delay_seconds: float = 0.5,
        request_id_prefix: str = "endpoint-test",
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if connect_retries < 0:
            raise ValueError("connect_retries must not be negative")
        if not is_valid_request_id(f"{request_id_prefix}-0"):
            raise ValueError("request_id_prefix must form a valid shared request ID")
        self._base_url = base_url.rstrip("/")
        self._connect_retries = connect_retries
        self._retry_delay_seconds = retry_delay_seconds
        self._request_id_prefix = request_id_prefix
        self._sleep = sleep
        self._clock = clock
        self._client = httpx.Client(
            base_url=self._base_url,
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
            headers={"Accept": f"{JSON_MEDIA_TYPE}, {PROBLEM_DETAIL_MEDIA_TYPE}"},
        )

    @property
    def base_url(self) -> str:
        return self._base_url

    def new_request_id(self) -> str:
        """Return a unique, contract-valid correlation ID for one request."""
        return f"{self._request_id_prefix}-{uuid.uuid4().hex}"

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str | int] | None = None,
        json: object = None,
        content: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        request_id: str | None = None,
    ) -> httpx.Response:
        """Send one request, retrying only connection failures that sent nothing."""
        if not path.startswith("/"):
            raise ValueError("endpoint paths must start with '/'")
        request_headers = dict(headers or {})
        request_headers[REQUEST_ID_HEADER] = request_id or self.new_request_id()
        attempt = 0
        while True:
            try:
                return self._client.request(
                    method,
                    path,
                    params=params,
                    json=json,
                    content=content,
                    headers=request_headers,
                )
            except (httpx.ConnectError, httpx.ConnectTimeout):
                if attempt >= self._connect_retries:
                    raise
                attempt += 1
                self._sleep(self._retry_delay_seconds * attempt)

    def get(self, path: str, **options: Any) -> httpx.Response:
        return self.request("GET", path, **options)

    def post(self, path: str, **options: Any) -> httpx.Response:
        return self.request("POST", path, **options)

    def put(self, path: str, **options: Any) -> httpx.Response:
        return self.request("PUT", path, **options)

    def delete(self, path: str, **options: Any) -> httpx.Response:
        return self.request("DELETE", path, **options)

    def get_json(
        self,
        path: str,
        *,
        params: Mapping[str, str | int] | None = None,
        status: int = 200,
    ) -> dict[str, Any]:
        """GET a JSON object and assert its status."""
        return expect_json(self.get(path, params=params), status=status)

    def wait_until_ready(
        self,
        path: str = DEFAULT_READY_PATH,
        *,
        timeout_seconds: float = DEFAULT_READY_TIMEOUT_SECONDS,
        interval_seconds: float = 1.0,
    ) -> httpx.Response:
        """Poll ``path`` until it answers ``2xx``; tolerate start-up errors until a deadline.

        Connection failures, timeouts and ``5xx`` responses are expected while containers
        start. A ``4xx`` means the readiness route itself is wrong and fails immediately.
        """
        deadline = self._clock() + timeout_seconds
        last_observation = "no attempt was made"
        while True:
            try:
                response = self._client.get(
                    path, headers={REQUEST_ID_HEADER: self.new_request_id()}
                )
            except httpx.TransportError as exc:
                last_observation = f"{type(exc).__name__}: {exc}"
            else:
                if response.is_success:
                    return response
                if response.status_code < 500:
                    raise EndpointNotReadyError(
                        f"readiness route is not usable: {_describe(response)}"
                    )
                last_observation = f"HTTP {response.status_code}"
            if self._clock() >= deadline:
                raise EndpointNotReadyError(
                    f"{self._base_url}{path} was not ready within {timeout_seconds:g}s "
                    f"(last: {last_observation})"
                )
            self._sleep(interval_seconds)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


def open_endpoint_client(
    environ: Mapping[str, str],
    *,
    ready_path: str | None = None,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> EndpointClient | None:
    """Create a client from the environment and wait for readiness.

    Returns ``None`` when no base URL is configured, so callers can skip.
    """
    base_url = endpoint_base_url(environ)
    if base_url is None:
        return None
    client = EndpointClient(base_url, transport=transport, sleep=sleep, clock=clock)
    try:
        client.wait_until_ready(
            ready_path or endpoint_ready_path(environ),
            timeout_seconds=endpoint_ready_timeout(environ),
        )
    except BaseException:
        client.close()
        raise
    return client
