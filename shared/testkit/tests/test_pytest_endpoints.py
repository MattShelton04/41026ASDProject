"""The opt-in endpoint plugin skips without a base URL and serves a ready client with one."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from shared_testkit.endpoints import (
    ENDPOINT_BASE_URL_ENV,
    ENDPOINT_READY_PATH_ENV,
    ENDPOINT_READY_TIMEOUT_ENV,
)

CONFTEST = """
from shared_testkit.pytest_endpoints import (
    endpoint_client,
    endpoint_ready_path,
    pytest_collection_modifyitems,
)

__all__ = ["endpoint_client", "endpoint_ready_path", "pytest_collection_modifyitems"]
"""

TESTS = """
import pytest

pytestmark = pytest.mark.endpoint


def test_marked_without_fixture():
    pass


def test_reads_items(endpoint_client):
    body = endpoint_client.get_json("/items")
    assert body == {"items": ["a"]}
"""

UNMARKED_FIXTURE_USER = """
def test_unmarked_fixture_user(endpoint_client):
    raise AssertionError("must be skipped by the fixture")


def test_plain():
    pass
"""


class _Service(BaseHTTPRequestHandler):
    """A loopback-only stand-in for a running service."""

    def do_GET(self) -> None:
        bodies = {"/health/ready": b'{"status": "healthy"}', "/items": b'{"items": ["a"]}'}
        body = bodies.get(self.path)
        self.send_response(200 if body is not None else 404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body or b"")))
        self.end_headers()
        self.wfile.write(body or b"")

    def log_message(self, format: str, *args: object) -> None:
        del format, args


@pytest.fixture
def local_service() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Service)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def endpoint_project(pytester: pytest.Pytester) -> pytest.Pytester:
    pytester.makeini("[pytest]\nmarkers =\n    endpoint: opt-in live endpoint test\n")
    pytester.makeconftest(CONFTEST)
    pytester.makepyfile(test_endpoints=TESTS, test_unmarked=UNMARKED_FIXTURE_USER)
    return pytester


def test_endpoint_tests_skip_without_a_base_url(
    endpoint_project: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(ENDPOINT_BASE_URL_ENV, raising=False)
    result = endpoint_project.runpytest("-rs", "--strict-markers", "-p", "no:cacheprovider")
    result.assert_outcomes(passed=1, skipped=3)
    result.stdout.fnmatch_lines([f"*set {ENDPOINT_BASE_URL_ENV}*"])


def test_endpoint_tests_run_against_a_live_service(
    endpoint_project: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, local_service: str
) -> None:
    monkeypatch.setenv(ENDPOINT_BASE_URL_ENV, local_service)
    monkeypatch.delenv(ENDPOINT_READY_PATH_ENV, raising=False)
    result = endpoint_project.runpytest(
        "--strict-markers", "-p", "no:cacheprovider", "test_endpoints.py"
    )
    result.assert_outcomes(passed=2)


def test_wrong_readiness_route_errors_instead_of_skipping(
    endpoint_project: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, local_service: str
) -> None:
    monkeypatch.setenv(ENDPOINT_BASE_URL_ENV, local_service)
    monkeypatch.setenv(ENDPOINT_READY_PATH_ENV, "/missing")
    monkeypatch.setenv(ENDPOINT_READY_TIMEOUT_ENV, "2")
    result = endpoint_project.runpytest(
        "--strict-markers", "-p", "no:cacheprovider", "test_endpoints.py"
    )
    result.assert_outcomes(passed=1, errors=1)
    result.stdout.fnmatch_lines(["*EndpointNotReadyError*not usable*"])
