"""Transient-failure classification and bounded retries for official ArcGIS reads."""

from __future__ import annotations

import dataclasses
import logging
import re
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from propertyscope_data_platform.adapters import arcgis
from propertyscope_data_platform.adapters.arcgis import (
    ArcGISPublisherError,
    RetryPolicy,
    discover_arcgis_layer,
    is_transient_source_error,
    iter_arcgis_features,
)

URL = (
    "https://mapprod1.environment.nsw.gov.au/arcgis/rest/services/Planning/"
    "EPI_Primary_Planning_Layers/MapServer/0"
)
METADATA = {
    "fields": [{"name": "OBJECTID", "type": "esriFieldTypeOID"}],
    "advancedQueryCapabilities": {"supportsOrderBy": True},
    "extent": {"spatialReference": {"wkid": 4283}},
    "maxRecordCount": 4,
}


def _policy(sleeps: list[float], *, attempts: int = 8, jitter: float = 1.0) -> RetryPolicy:
    return RetryPolicy(attempts=attempts, sleep=sleeps.append, jitter=lambda: jitter)


def _feature(oid: int) -> dict[str, Any]:
    return {"type": "Feature", "properties": {"OBJECTID": oid}, "geometry": None}


def _read(handler: Any, policy: RetryPolicy, url: str = URL) -> dict[str, Any]:
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        return arcgis._read_json(client, url, {"f": "json"}, retry=policy)


def test_delay_is_exponential_capped_and_jittered() -> None:
    high = RetryPolicy(base_seconds=0.5, max_seconds=30.0, jitter=lambda: 1.0)
    assert [high.delay(attempt) for attempt in range(8)] == [
        0.5,
        1.0,
        2.0,
        4.0,
        8.0,
        16.0,
        30.0,
        30.0,
    ]
    low = RetryPolicy(base_seconds=0.5, max_seconds=30.0, jitter=lambda: 0.0)
    assert [low.delay(attempt) for attempt in range(3)] == [0.25, 0.5, 1.0]
    # Retry-After is a floor, never an unbounded wait.
    assert low.delay(0, retry_after=12) == 12
    assert low.delay(0, retry_after=3600) == 30.0


@pytest.mark.parametrize("jitter", [0.0, 1.0], ids=["shortest-waits", "longest-waits"])
def test_default_policy_rides_out_a_multi_minute_outage_within_its_budget(jitter: float) -> None:
    sleeps: list[float] = []
    requests: list[httpx.Request] = []
    policy = dataclasses.replace(
        arcgis.DEFAULT_RETRY_POLICY, sleep=sleeps.append, jitter=lambda: jitter
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        # Observed 2026-10-18: the portal's database refused clients for minutes.
        message = "FATAL: sorry, too many clients already"
        return httpx.Response(200, json={"error": {"code": 500, "message": message}})

    with pytest.raises(ArcGISPublisherError, match="too many clients"):
        _read(handler, policy)
    waited = sum(sleeps)
    assert len(requests) == len(sleeps) + 1
    assert 600 <= waited <= policy.budget_seconds  # Retries continue for 10-15 minutes.
    assert max(sleeps) <= policy.max_seconds
    assert len(requests) < policy.attempts


def test_budget_stops_retrying_before_the_wait_would_exceed_it() -> None:
    sleeps: list[float] = []
    policy = RetryPolicy(budget_seconds=3.0, sleep=sleeps.append, jitter=lambda: 1.0)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, content=b"busy")

    with pytest.raises(httpx.HTTPStatusError):
        _read(handler, policy)
    assert sleeps == [0.5, 1.0]  # The next 2.0 s wait would pass the 3.0 s budget.


@pytest.mark.parametrize("code", [500, 503, 504])
def test_transient_arcgis_error_bodies_are_retried_until_success(code: int) -> None:
    sleeps: list[float] = []
    error = {"error": {"code": code, "message": "Timed out", "details": []}}
    responses = [httpx.Response(200, json=error)] * 2 + [httpx.Response(200, json={"count": 7})]

    assert _read(lambda _: responses.pop(0), _policy(sleeps)) == {"count": 7}
    assert sleeps == [0.5, 1.0]


def test_exhausted_transient_error_keeps_code_bounded_message_and_transience() -> None:
    sleeps: list[float] = []
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        message = "Gateway\n  timeout " + "x" * 400
        return httpx.Response(200, json={"error": {"code": 504, "message": message}})

    with pytest.raises(ArcGISPublisherError) as failure:
        _read(handler, _policy(sleeps, attempts=4))
    assert len(requests) == 4
    assert sleeps == [0.5, 1.0, 2.0]
    assert failure.value.code == 504
    assert failure.value.transient is True
    assert is_transient_source_error(failure.value)
    assert str(failure.value).startswith("ArcGIS publisher returned error 504: Gateway timeout x")
    assert len(str(failure.value)) < 260
    assert isinstance(failure.value, ValueError)  # Existing callers still see a source error.


@pytest.mark.parametrize(
    "payload",
    [
        {"error": {"code": 400, "message": "Invalid or missing input parameters."}},
        {"error": {"code": 498, "message": "Invalid token."}},
        {"error": {"code": "504", "message": "String codes are not trusted"}},
        {"error": {"code": True, "message": "Booleans are not codes"}},
        {"error": {"code": [504], "message": "Unhashable codes are not codes"}},
        {"error": "unstructured"},
    ],
    ids=["invalid-query", "token", "string-code", "boolean-code", "list-code", "unstructured"],
)
def test_non_transient_arcgis_error_bodies_fail_fast(payload: dict[str, Any]) -> None:
    sleeps: list[float] = []
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=payload)

    with pytest.raises(ArcGISPublisherError) as failure:
        _read(handler, _policy(sleeps))
    assert len(requests) == 1
    assert sleeps == []
    assert failure.value.transient is False
    assert not is_transient_source_error(failure.value)


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ReadTimeout("read timed out"),
        httpx.ConnectTimeout("connect timed out"),
        httpx.ConnectError("connection refused"),
        httpx.RemoteProtocolError("peer closed connection"),
        httpx.ReadError("connection reset"),
    ],
    ids=["read-timeout", "connect-timeout", "connect-error", "protocol", "read-error"],
)
def test_transport_failures_are_retried_with_backoff(failure: httpx.TransportError) -> None:
    sleeps: list[float] = []
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls <= 3:
            raise failure
        return httpx.Response(200, json={"count": 1})

    assert _read(handler, _policy(sleeps)) == {"count": 1}
    assert sleeps == [0.5, 1.0, 2.0]
    assert is_transient_source_error(failure)


def test_each_retry_is_logged_with_path_but_without_query(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sleeps: list[float] = []
    responses = [
        httpx.Response(503, content=b"busy"),
        httpx.Response(200, json={"count": 1}),
    ]

    with (
        caplog.at_level(logging.WARNING, logger=arcgis.__name__),
        httpx.Client(transport=httpx.MockTransport(lambda _: responses.pop(0))) as client,
    ):
        arcgis._read_json(client, URL + "/query", {"where": "OBJECTID>41"}, retry=_policy(sleeps))

    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert "EPI_Primary_Planning_Layers/MapServer/0/query" in message
    assert "HTTPStatusError" in message
    assert "retry 1 in 0.5 s (0/900 s budget)" in message
    assert "OBJECTID" not in message


def test_mid_body_disconnect_is_retried_without_accepting_partial_json() -> None:
    sleeps: list[float] = []
    calls = 0

    class BrokenStream(httpx.SyncByteStream):
        def __iter__(self) -> Iterator[bytes]:
            yield b'{"count": '
            raise httpx.RemoteProtocolError("peer closed connection without sending body")

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(200, stream=BrokenStream())
        return httpx.Response(200, json={"count": 2})

    assert _read(handler, _policy(sleeps)) == {"count": 2}
    assert calls == 2
    assert sleeps == [0.5]


@pytest.mark.parametrize("status", [408, 425, 429, 500, 502, 503, 504])
def test_transient_http_statuses_are_retried_and_honour_retry_after(status: int) -> None:
    sleeps: list[float] = []
    statuses = [status, 200]

    def handler(request: httpx.Request) -> httpx.Response:
        current = statuses.pop(0)
        if current == 200:
            return httpx.Response(200, json={"count": 3})
        return httpx.Response(current, headers={"Retry-After": "7"}, content=b"busy")

    assert _read(handler, _policy(sleeps)) == {"count": 3}
    assert sleeps == [7.0]


@pytest.mark.parametrize("status", [400, 401, 403, 404, 501])
def test_permanent_http_statuses_fail_fast(status: int) -> None:
    sleeps: list[float] = []
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, content=b"no")

    with pytest.raises(httpx.HTTPStatusError) as failure:
        _read(handler, _policy(sleeps))
    assert len(requests) == 1
    assert sleeps == []
    assert not is_transient_source_error(failure.value)


def test_invalid_json_and_ordinary_errors_are_not_transient() -> None:
    sleeps: list[float] = []
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=b'{"count": ')

    with pytest.raises(ValueError):
        _read(handler, _policy(sleeps))
    assert len(requests) == 1
    assert not is_transient_source_error(httpx.UnsupportedProtocol("ftp"))
    assert not is_transient_source_error(ValueError("ArcGIS acquisition is incomplete"))


def test_html_query_capacity_is_still_classified_after_three_attempts() -> None:
    sleeps: list[float] = []
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500, content=b"<html>Error performing query operation</html>")

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(arcgis._ArcGISPageCapacityError),
    ):
        arcgis._read_json(
            client,
            URL + "/query",
            {"f": "json", "returnGeometry": "true", "resultRecordCount": "4"},
            retry=_policy(sleeps),
        )
    # The capacity decision does not wait for the whole transient budget.
    assert len(requests) == arcgis._CAPACITY_PROBE_ATTEMPTS
    assert sleeps == [0.5, 1.0]


@pytest.mark.parametrize("workers", [1, 4])
def test_intermittent_failures_still_yield_one_complete_layer_at_unchanged_page_size(
    monkeypatch: pytest.MonkeyPatch, workers: int
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(arcgis, "DEFAULT_RETRY_POLICY", _policy(sleeps, jitter=0.0))
    failures = [
        httpx.Response(200, json={"error": {"code": 504, "message": "Timed out"}}),
        httpx.Response(503, content=b"<html>Service Unavailable</html>"),
        httpx.Response(200, json={"error": {"code": 500, "message": "Unable to complete"}}),
    ]
    sizes: list[int] = []
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls % 4 == 0 and failures:
            # Every fourth request of any kind fails once: metadata, counts and pages.
            return failures.pop(0)
        params = request.url.params
        if not request.url.path.endswith("/query"):
            return httpx.Response(200, json=METADATA)
        if params.get("returnCountOnly"):
            return httpx.Response(200, json={"count": 20})
        if params.get("outStatistics"):
            return httpx.Response(
                200, json={"features": [{"attributes": {"min_oid": 1, "max_oid": 20}}]}
            )
        lower_match = re.search(r"OBJECTID>(\d+)", params["where"])
        upper_match = re.search(r"OBJECTID<=(\d+)", params["where"])
        lower = int(lower_match[1]) if lower_match else 0
        upper = int(upper_match[1]) if upper_match else 20
        size = int(params["resultRecordCount"])
        sizes.append(size)
        features = [_feature(oid) for oid in range(lower + 1, min(upper, lower + size) + 1)]
        return httpx.Response(200, json={"type": "FeatureCollection", "features": features})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        descriptor = discover_arcgis_layer(client, URL, "example", workers=workers)
        records = list(iter_arcgis_features(client, descriptor))
    ids = [row["properties"]["OBJECTID"] for row in records]
    assert sorted(ids) == list(range(1, 21))
    assert len(ids) == len(set(ids))
    assert failures == []
    assert len(sleeps) == 3
    assert set(sizes) == {4}  # Transient failures retry at the same bound; pages never shrink.


def test_retries_never_mask_a_source_count_change(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(arcgis, "DEFAULT_RETRY_POLICY", _policy(sleeps))
    counts = iter([3, 4])

    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if not request.url.path.endswith("/query"):
            return httpx.Response(200, json=METADATA)
        if params.get("returnCountOnly"):
            return httpx.Response(200, json={"count": next(counts)})
        lower_match = re.search(r"OBJECTID>(\d+)", params["where"])
        lower = int(lower_match[1]) if lower_match else 0
        features = [_feature(oid) for oid in range(lower + 1, min(3, lower + 4) + 1)]
        return httpx.Response(200, json={"type": "FeatureCollection", "features": features})

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(ValueError, match="incomplete or source count changed"),
    ):
        list(iter_arcgis_features(client, discover_arcgis_layer(client, URL, "example")))
    assert sleeps == []
