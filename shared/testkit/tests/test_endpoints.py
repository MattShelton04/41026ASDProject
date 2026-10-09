"""Endpoint-test client behaviour, exercised entirely through httpx.MockTransport."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator

import httpx
import pytest

from shared_contracts import PROBLEM_DETAIL_MEDIA_TYPE, REQUEST_ID_HEADER, is_valid_request_id
from shared_testkit.endpoints import (
    DEFAULT_READY_PATH,
    DEFAULT_READY_TIMEOUT_SECONDS,
    ENDPOINT_BASE_URL_ENV,
    ENDPOINT_READY_PATH_ENV,
    ENDPOINT_READY_TIMEOUT_ENV,
    EndpointClient,
    EndpointConfigurationError,
    EndpointNotReadyError,
    endpoint_base_url,
    endpoint_ready_path,
    endpoint_ready_timeout,
    expect_json,
    expect_problem,
    expect_status,
    open_endpoint_client,
)

Handler = Callable[[httpx.Request], httpx.Response]


class FakeClock:
    """Deterministic monotonic clock advanced by the injected sleep."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _client(
    handler: Handler,
    clock: FakeClock | None = None,
    *,
    connect_retries: int = 3,
    retry_delay_seconds: float = 0.5,
) -> EndpointClient:
    fake = clock or FakeClock()
    return EndpointClient(
        "http://service.test/",
        transport=httpx.MockTransport(handler),
        sleep=fake.sleep,
        clock=fake,
        connect_retries=connect_retries,
        retry_delay_seconds=retry_delay_seconds,
    )


def _problem(request: httpx.Request, status: int, code: str) -> httpx.Response:
    return httpx.Response(
        status,
        json={
            "type": f"https://example.test/problems/{code}",
            "title": code.title(),
            "status": status,
            "detail": "rejected",
            "code": code,
            "request_id": request.headers[REQUEST_ID_HEADER],
        },
        headers={"content-type": PROBLEM_DETAIL_MEDIA_TYPE},
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("   ", None),
        ("http://127.0.0.1:5200", "http://127.0.0.1:5200"),
        (" https://edge.test/base/ ", "https://edge.test/base"),
    ],
)
def test_base_url_is_optional_and_normalised(value: str | None, expected: str | None) -> None:
    environ = {} if value is None else {ENDPOINT_BASE_URL_ENV: value}
    assert endpoint_base_url(environ) == expected


@pytest.mark.parametrize(
    "value", ["localhost:5200", "ftp://host.test", "http://", "http://host.test/?a=1"]
)
def test_unusable_base_url_is_a_configuration_error(value: str) -> None:
    with pytest.raises(EndpointConfigurationError, match=ENDPOINT_BASE_URL_ENV):
        endpoint_base_url({ENDPOINT_BASE_URL_ENV: value})


def test_ready_path_and_timeout_have_bounded_defaults() -> None:
    assert endpoint_ready_path({}) == DEFAULT_READY_PATH
    assert endpoint_ready_path({ENDPOINT_READY_PATH_ENV: "/healthz"}) == "/healthz"
    assert endpoint_ready_timeout({}) == DEFAULT_READY_TIMEOUT_SECONDS
    assert endpoint_ready_timeout({ENDPOINT_READY_TIMEOUT_ENV: "12.5"}) == 12.5
    with pytest.raises(EndpointConfigurationError):
        endpoint_ready_path({ENDPOINT_READY_PATH_ENV: "healthz"})
    for invalid in ("soon", "0", "601"):
        with pytest.raises(EndpointConfigurationError):
            endpoint_ready_timeout({ENDPOINT_READY_TIMEOUT_ENV: invalid})


def test_requests_carry_unique_valid_correlation_ids_and_json() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={"echo": request.content.decode()})

    with _client(handler) as client:
        assert client.base_url == "http://service.test"
        response = client.post("/items", json={"name": "x"}, params={"dry_run": "true"})
        client.get("/items")
        client.put("/items/1", json={})
        client.delete("/items/1", request_id="chosen-id")
    assert expect_json(response, status=201) == {"echo": '{"name":"x"}'}
    assert [request.method for request in seen] == ["POST", "GET", "PUT", "DELETE"]
    assert seen[0].url == "http://service.test/items?dry_run=true"
    ids = [request.headers[REQUEST_ID_HEADER] for request in seen]
    assert len(set(ids)) == 4
    assert ids[-1] == "chosen-id"
    assert all(is_valid_request_id(value) for value in ids)
    assert ids[0].startswith("endpoint-test-")
    assert "application/json" in seen[0].headers["accept"]


def test_connection_failures_are_retried_with_backoff_then_raised() -> None:
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) < 3:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, json={})

    clock = FakeClock()
    with _client(handler, clock, connect_retries=2, retry_delay_seconds=0.5) as client:
        assert client.get("/items").status_code == 200
    assert clock.sleeps == [0.5, 1.0]

    def always_down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with _client(always_down, connect_retries=1) as client, pytest.raises(httpx.ConnectError):
        client.get("/items")


def test_server_errors_and_read_timeouts_are_not_retried() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/slow":
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(503, json={})

    with _client(handler) as client:
        assert client.post("/items", json={}).status_code == 503
        with pytest.raises(httpx.ReadTimeout):
            client.get("/slow")
    assert calls == ["/items", "/slow"]


def test_client_rejects_invalid_configuration_and_relative_paths() -> None:
    with pytest.raises(ValueError, match="connect_retries"):
        EndpointClient("http://service.test", connect_retries=-1)
    with pytest.raises(ValueError, match="request_id_prefix"):
        EndpointClient("http://service.test", request_id_prefix="bad prefix")
    with _client(lambda request: httpx.Response(200)) as client, pytest.raises(ValueError):
        client.get("items")


def test_get_json_and_expect_json_report_actionable_failures() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        match request.url.path:
            case "/object":
                return httpx.Response(200, json={"items": []})
            case "/list":
                return httpx.Response(200, json=[1])
            case "/html":
                return httpx.Response(200, text="<p>", headers={"content-type": "text/html"})
            case "/broken":
                return httpx.Response(
                    200, content=b"{", headers={"content-type": "application/json"}
                )
            case _:
                return httpx.Response(404, text="missing")

    with _client(handler) as client:
        assert client.get_json("/object") == {"items": []}
        with pytest.raises(AssertionError, match=r"expected HTTP 200.*GET http://service.test/x"):
            client.get_json("/x")
        with pytest.raises(AssertionError, match="JSON object"):
            client.get_json("/list")
        with pytest.raises(AssertionError, match="expected application/json"):
            client.get_json("/html")
        with pytest.raises(AssertionError, match="not valid JSON"):
            client.get_json("/broken")
        assert expect_status(client.get("/x"), 404).text == "missing"


def test_expect_problem_validates_media_type_contract_and_correlation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/plain":
            return httpx.Response(422, json={"title": "x", "status": 422, "code": "bad"})
        if request.url.path == "/mismatch":
            response = _problem(request, 422, "bad")
            return httpx.Response(
                400, content=response.content, headers={"content-type": PROBLEM_DETAIL_MEDIA_TYPE}
            )
        return _problem(request, 422, "invalid_request")

    with _client(handler) as client:
        problem = expect_problem(
            client.get("/search", request_id="trace-1"),
            status=422,
            code="invalid_request",
            request_id="trace-1",
        )
        assert problem.detail == "rejected"
        with pytest.raises(AssertionError, match="problem code"):
            expect_problem(client.get("/search"), status=422, code="other")
        with pytest.raises(AssertionError, match="does not echo"):
            expect_problem(
                client.get("/search"), status=422, code="invalid_request", request_id="other"
            )
        with pytest.raises(AssertionError, match=re.escape(PROBLEM_DETAIL_MEDIA_TYPE)):
            expect_problem(client.get("/plain"), status=422, code="bad")
        with pytest.raises(AssertionError, match="does not match HTTP 400"):
            expect_problem(client.get("/mismatch"), status=400, code="bad")


def test_wait_until_ready_tolerates_start_up_failures() -> None:
    script: Iterator[str] = iter(["refused", "502", "timeout", "200"])

    def handler(request: httpx.Request) -> httpx.Response:
        assert is_valid_request_id(request.headers[REQUEST_ID_HEADER])
        step = next(script)
        if step == "refused":
            raise httpx.ConnectError("refused", request=request)
        if step == "timeout":
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(int(step), json={"status": "healthy"})

    clock = FakeClock()
    with _client(handler, clock) as client:
        response = client.wait_until_ready(timeout_seconds=10, interval_seconds=2)
    assert response.json() == {"status": "healthy"}
    assert clock.sleeps == [2, 2, 2]


def test_wait_until_ready_stops_at_the_deadline_and_on_client_errors() -> None:
    clock = FakeClock()
    with (
        _client(lambda request: httpx.Response(503), clock) as client,
        pytest.raises(EndpointNotReadyError, match=r"within 3s \(last: HTTP 503\)"),
    ):
        client.wait_until_ready("/ready", timeout_seconds=3, interval_seconds=1)
    assert clock.sleeps == [1, 1, 1]
    with (
        _client(lambda request: httpx.Response(404, text="nope")) as client,
        pytest.raises(EndpointNotReadyError, match="not usable"),
    ):
        client.wait_until_ready()


def test_open_endpoint_client_reads_environment_and_waits() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, json={})

    assert open_endpoint_client({}) is None
    environ = {ENDPOINT_BASE_URL_ENV: "http://service.test", ENDPOINT_READY_PATH_ENV: "/healthz"}
    client = open_endpoint_client(environ, transport=httpx.MockTransport(handler))
    assert client is not None
    client.close()
    client = open_endpoint_client(
        environ, ready_path="/custom", transport=httpx.MockTransport(handler)
    )
    assert client is not None
    client.close()
    assert paths == ["/healthz", "/custom"]


def test_open_endpoint_client_closes_the_client_when_never_ready() -> None:
    clock = FakeClock()
    environ = {ENDPOINT_BASE_URL_ENV: "http://service.test", ENDPOINT_READY_TIMEOUT_ENV: "1"}
    with pytest.raises(EndpointNotReadyError):
        open_endpoint_client(
            environ,
            transport=httpx.MockTransport(lambda request: httpx.Response(500)),
            sleep=clock.sleep,
            clock=clock,
        )
