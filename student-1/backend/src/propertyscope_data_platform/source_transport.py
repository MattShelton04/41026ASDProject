"""Disk-backed acquisition for registered Feature 1 sources."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlparse

import httpx

ProgressCallback = Callable[[int], None]

ALLOWED_SOURCE_HOSTS = frozenset(
    {
        "data.nsw.gov.au",
        "bocsarblob.blob.core.windows.net",
        "www.valuergeneral.nsw.gov.au",
    }
)
ALLOWED_MEDIA_TYPES = frozenset(
    {
        "text/csv",
        "application/csv",
        "application/octet-stream",
        "application/zip",
        "application/x-zip-compressed",
    }
)


class RegisteredSourceTransport:
    """Acquire only allowlisted HTTPS sources."""

    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def download_bytes(self, url: str) -> bytes:
        """Return a registered source payload for non-bulk profiles."""
        chunks: list[bytes] = []
        self._ordinary_download(
            url,
            write=chunks.append,
            progress=None,
        )
        return b"".join(chunks)

    @contextmanager
    def psi_archive_path(
        self,
        url: str,
        *,
        directory: Path,
        progress: ProgressCallback | None = None,
    ) -> Iterator[Path]:
        """Download one PSI archive to a temporary file and remove it after use."""
        directory.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            prefix="psi-source-", suffix=".zip", dir=directory, delete=False
        ) as temporary:
            path = Path(temporary.name)
        try:
            with path.open("wb") as destination:
                ordinary_succeeded = self._ordinary_download(
                    url,
                    write=destination.write,
                    progress=progress,
                    allow_forbidden=True,
                )
                if not ordinary_succeeded:
                    self._range_download(
                        url,
                        write=destination.write,
                        progress=progress,
                    )
            yield path
        finally:
            path.unlink(missing_ok=True)

    def _ordinary_download(
        self,
        url: str,
        *,
        write: Callable[[bytes], object],
        progress: ProgressCallback | None,
        allow_forbidden: bool = False,
    ) -> bool:
        self._validate_url(url)
        with self._client.stream(
            "GET", url, headers={"Accept": "*/*", "User-Agent": "PropertyScope/1.0"}
        ) as response:
            if allow_forbidden and response.status_code == 403:
                return False
            response.raise_for_status()
            media_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
            if media_type not in ALLOWED_MEDIA_TYPES:
                raise RuntimeError("Registered source returned an unexpected media type")
            for chunk in response.iter_bytes():
                write(chunk)
                if progress is not None:
                    progress(len(chunk))
        return True

    def _range_download(
        self,
        url: str,
        *,
        write: Callable[[bytes], object],
        progress: ProgressCallback | None,
    ) -> None:
        offset = 0
        expected_total: int | None = None
        chunk_size = 4 * 1024 * 1024
        while expected_total is None or offset < expected_total:
            end = offset + chunk_size - 1
            response: httpx.Response | None = None
            for _attempt in range(4):
                candidate = self._client.get(
                    url,
                    headers={
                        "Accept": "application/zip",
                        "Range": f"bytes={offset}-{end}",
                        "User-Agent": "PropertyScope/1.0",
                    },
                )
                if candidate.status_code == 206:
                    response = candidate
                    break
                if candidate.status_code != 403:
                    candidate.raise_for_status()
            if response is None:
                raise RuntimeError("PSI source rejected range acquisition")
            match = re.fullmatch(
                r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("content-range", "")
            )
            if match is None or int(match.group(1)) != offset:
                raise RuntimeError("PSI source returned an invalid content range")
            range_end, total = int(match.group(2)), int(match.group(3))
            invalid_length = len(response.content) != range_end - offset + 1
            if range_end >= total or invalid_length:
                raise RuntimeError("PSI source returned an invalid byte range")
            if expected_total is not None and total != expected_total:
                raise RuntimeError("PSI source changed during ranged acquisition")
            expected_total = total
            write(response.content)
            offset = range_end + 1
            if progress is not None:
                progress(len(response.content))

    @staticmethod
    def _validate_url(url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_SOURCE_HOSTS:
            raise RuntimeError("Source URL is outside the registered HTTPS allowlist")
