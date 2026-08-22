from __future__ import annotations

import httpx
import pytest

from propertyscope_data_platform.source_transport import RegisteredSourceTransport


def test_small_source_download_is_bounded_and_allowlisted() -> None:
    def source(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "data.nsw.gov.au"
        return httpx.Response(200, content=b"a,b\n1,2\n", headers={"Content-Type": "text/csv"})

    with httpx.Client(transport=httpx.MockTransport(source)) as client:
        transport = RegisteredSourceTransport(client)
        assert (
            transport.download_bytes("https://data.nsw.gov.au/source.csv", maximum_bytes=20)
            == b"a,b\n1,2\n"
        )
        with pytest.raises(RuntimeError, match="allowlist"):
            transport.download_bytes("http://data.nsw.gov.au/source.csv", maximum_bytes=20)


@pytest.mark.parametrize(
    ("headers", "message"),
    [
        ({"Content-Type": "text/html"}, "media type"),
        ({"Content-Type": "text/csv", "Content-Length": "100"}, "byte limit"),
    ],
)
def test_small_source_rejects_unregistered_or_oversized_responses(
    headers: dict[str, str], message: str
) -> None:
    def source(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"body", headers=headers)

    with (
        httpx.Client(transport=httpx.MockTransport(source)) as client,
        pytest.raises(RuntimeError, match=message),
    ):
        RegisteredSourceTransport(client).download_bytes(
            "https://data.nsw.gov.au/source.csv", maximum_bytes=10
        )


def test_psi_range_failure_cleans_temporary_archive(tmp_path) -> None:
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
            maximum_bytes=100,
        ):
            pass

    assert list(tmp_path.iterdir()) == []
