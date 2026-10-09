"""A small standard-library GitHub REST client for the trusted visual publisher."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from scripts.visual.policy import SHA

API_ROOT = "https://api.github.com"
MAX_ARTIFACT_BYTES = 400_000_000


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


class GitHub:
    """Authenticated calls scoped to one repository."""

    def __init__(self, repo: str, token: str) -> None:
        owner, _, name = repo.partition("/")
        if not owner or not name or "/" in name:
            raise ValueError("invalid repository name")
        self.repo = repo
        self._token = token

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "propertyscope-visual-publisher",
        }

    def request(self, path: str, *, method: str = "GET", body: object = None) -> Any:
        """Call ``/repos/<repo><path>`` and return decoded JSON (``None`` for 204)."""
        data = json.dumps(body).encode() if body is not None else None
        headers = self._headers()
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(  # noqa: S310 - GitHub API https URLs only
            f"{API_ROOT}/repos/{self.repo}{path}", data=data, headers=headers, method=method
        )
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - GitHub API https URLs only
            payload = response.read()
        return json.loads(payload) if payload else None

    def download_artifact(self, artifact_id: int) -> bytes:
        """Download an artifact zip without forwarding the token to the storage redirect."""
        request = urllib.request.Request(  # noqa: S310 - GitHub API https URLs only
            f"{API_ROOT}/repos/{self.repo}/actions/artifacts/{artifact_id}/zip",
            headers=self._headers(),
        )
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            opener.open(request, timeout=60)
            raise RuntimeError("expected a redirect to artifact storage")
        except urllib.error.HTTPError as redirect:
            if redirect.code not in (301, 302, 303, 307, 308):
                raise
            location = redirect.headers.get("Location", "")
        if not location.startswith("https://"):
            raise RuntimeError("artifact storage URL is not HTTPS")
        with urllib.request.urlopen(location, timeout=120) as response:  # noqa: S310 - GitHub API https URLs only
            data = response.read(MAX_ARTIFACT_BYTES + 1)
        if len(data) > MAX_ARTIFACT_BYTES:
            raise RuntimeError("artifact download exceeds its size limit")
        return bytes(data)


def wait_until_served(url: str, *, timeout_seconds: float = 300, interval: float = 10) -> bool:
    """Poll a public Pages URL until it responds, so comment images are not cached as broken."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=20) as response:  # noqa: S310 - GitHub API https URLs only
                if response.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError):
            pass
        time.sleep(interval)
    return False


def valid_sha(value: object) -> bool:
    """True for a full lowercase commit SHA."""
    return isinstance(value, str) and bool(SHA.fullmatch(value))
