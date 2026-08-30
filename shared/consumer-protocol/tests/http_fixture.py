"""Loopback HTTP fixture used to exercise the real transport without internet access."""

from __future__ import annotations

import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@dataclass(frozen=True, slots=True)
class FixtureResponse:
    status: int
    body: bytes = b""
    headers: Mapping[str, str] = field(default_factory=dict)
    include_content_length: bool = True


@dataclass(slots=True)
class FixtureState:
    routes: dict[str, FixtureResponse]
    requests: list[tuple[str, Mapping[str, str]]] = field(default_factory=list)


@contextmanager
def serve(routes: dict[str, FixtureResponse]) -> Iterator[tuple[str, FixtureState]]:
    """Serve fixed responses from an ephemeral loopback port."""
    state = FixtureState(routes)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            state.requests.append((self.path, dict(self.headers.items())))
            response = state.routes.get(self.path, FixtureResponse(404))
            self.send_response(response.status)
            for name, value in response.headers.items():
                self.send_header(name, value)
            if response.include_content_length and not any(
                name.lower() == "content-length" for name in response.headers
            ):
                self.send_header("Content-Length", str(len(response.body)))
            self.end_headers()
            self.wfile.write(response.body)

        def log_message(self, format: str, *args: object) -> None:
            del format, args

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
