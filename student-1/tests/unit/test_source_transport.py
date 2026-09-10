from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from propertyscope_data_platform.runner import _safe_task_error
from propertyscope_data_platform.source_transport import (
    RegisteredSourceTransport,
    SourceAccessError,
)


class _ChunkStream(httpx.SyncByteStream):
    def __iter__(self) -> Iterator[bytes]:
        yield b"ab"
        yield b"cde"


def test_source_download_is_complete_and_allowlisted() -> None:
    def source(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "data.nsw.gov.au"
        return httpx.Response(200, content=b"a,b\n1,2\n", headers={"Content-Type": "text/csv"})

    with httpx.Client(transport=httpx.MockTransport(source)) as client:
        transport = RegisteredSourceTransport(client)
        assert transport.download_bytes("https://data.nsw.gov.au/source.csv") == b"a,b\n1,2\n"
        with pytest.raises(RuntimeError, match="allowlist"):
            transport.download_bytes("http://data.nsw.gov.au/source.csv")


def test_source_progress_reports_byte_deltas_not_cumulative_totals(tmp_path: Path) -> None:
    def source(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            stream=_ChunkStream(),
            headers={"Content-Type": "application/zip"},
        )

    progress: list[int] = []
    with httpx.Client(transport=httpx.MockTransport(source)) as client:
        transport = RegisteredSourceTransport(client)
        with transport.psi_archive_path(
            "https://www.valuergeneral.nsw.gov.au/source.zip",
            directory=tmp_path,
            progress=progress.append,
        ) as path:
            assert path.read_bytes() == b"abcde"

    assert progress == [2, 3]


def test_source_rejects_an_unregistered_media_type() -> None:
    def source(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"body", headers={"Content-Type": "text/html"})

    with (
        httpx.Client(transport=httpx.MockTransport(source)) as client,
        pytest.raises(RuntimeError, match="media type"),
    ):
        RegisteredSourceTransport(client).download_bytes("https://data.nsw.gov.au/source.csv")


def test_psi_range_failure_cleans_temporary_archive(tmp_path: Path) -> None:
    def source(request: httpx.Request) -> httpx.Response:
        if "Range" not in request.headers:
            return httpx.Response(403)
        return httpx.Response(206, content=b"bad", headers={"Content-Range": "invalid"})

    with (
        httpx.Client(transport=httpx.MockTransport(source)) as client,
        pytest.raises(RuntimeError, match="invalid content range"),
    ):
        transport = RegisteredSourceTransport(client)
        with transport.psi_archive_path(
            "https://www.valuergeneral.nsw.gov.au/source.zip",
            directory=tmp_path,
        ):
            pass

    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("range_challenged", [False, True])
def test_publisher_challenge_stops_retries_and_reports_safe_recovery(
    tmp_path: Path, range_challenged: bool
) -> None:
    calls = 0

    def source(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        headers = {"cf-mitigated": "challenge"}
        if range_challenged and "Range" not in request.headers:
            headers = {}
        return httpx.Response(403, headers=headers, text="private challenge body")

    with (
        httpx.Client(transport=httpx.MockTransport(source)) as client,
        pytest.raises(SourceAccessError) as failure,
        RegisteredSourceTransport(client).psi_archive_path(
            "https://www.valuergeneral.nsw.gov.au/__psi/weekly/20260907.zip",
            directory=tmp_path,
        ),
    ):
        pytest.fail("a challenge is not a source archive")
    assert calls == (2 if range_challenged else 1)
    assert list(tmp_path.iterdir()) == []
    error = _safe_task_error({"stage": "acquire"}, failure.value)
    assert error["code"] == "source_access_challenged"
    assert error["retryable"] is True
    assert "20260907.zip" in str(error["message"])
    assert "private" not in str(error)
