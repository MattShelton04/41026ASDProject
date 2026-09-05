"""Loopback-only static/proxy server for the Student 3 frontend scaffold."""

from __future__ import annotations

import json
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen

FRONTEND = Path(__file__).resolve().parent
REPOSITORY = FRONTEND.parents[1]
BACKEND = os.getenv("SUBURB_BACKEND_URL", "http://127.0.0.1:5301")
MAX_REQUEST_BYTES = 65_536
MAX_RESPONSE_BYTES = 1_048_576
STATIC_SUFFIXES = {".html", ".js", ".css", ".svg", ".png", ".jpg", ".ico", ".woff", ".woff2"}
SHARED_ROOTS = {"design-system", "mapping", "browser", "ai-chat", "vendor"}


def static_path(path: str) -> Path | None:
    """Resolve allowlisted assets without directory, dotfile or symlink escapes."""
    try:
        decoded = unquote(urlsplit(path).path, errors="strict")
        parts = Path(decoded.lstrip("/")).parts
        if "\\" in decoded or any(part.startswith(".") for part in parts):
            return None
        root = (
            REPOSITORY / "shared" / "frontend" if parts and parts[0] in SHARED_ROOTS else FRONTEND
        )
        candidate = (root / decoded.lstrip("/")).resolve()
        if not candidate.is_relative_to(root.resolve()):
            return None
        if candidate.is_file():
            return candidate if candidate.suffix.lower() in STATIC_SUFFIXES else None
        if candidate.suffix or parts and parts[0] in SHARED_ROOTS:
            return None
        if parts and parts[0] in {"api", "health"}:
            return None
        return FRONTEND / "index.html"
    except (ValueError, UnicodeError, OSError):
        return None


def proxy_path(path: str) -> bool:
    """Proxy only this feature's API and its two explicit health routes."""
    pathname = urlsplit(path).path
    return pathname.startswith("/api/suburb-analytics/") or pathname in {
        "/health/live",
        "/health/ready",
    }


class Handler(SimpleHTTPRequestHandler):
    """Serve approved browser assets and forward bounded same-feature requests."""

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(15)

    def translate_path(self, path: str) -> str:
        return str(static_path(path) or FRONTEND / "__missing_asset__")

    def _serve(self, *, head: bool = False) -> None:
        if proxy_path(self.path):
            self._proxy("HEAD" if head else "GET")
        elif static_path(self.path) is None:
            self.send_error(404, "Asset not found")
        elif head:
            super().do_HEAD()
        else:
            super().do_GET()

    def do_GET(self) -> None:
        self._serve()

    def do_HEAD(self) -> None:
        self._serve(head=True)

    def do_POST(self) -> None:
        self._proxy("POST")

    def do_PUT(self) -> None:
        self._proxy("PUT")

    def do_DELETE(self) -> None:
        self._proxy("DELETE")

    def _problem(self, status: int, detail: str) -> None:
        body = json.dumps(
            {"status": status, "title": "Development proxy error", "detail": detail}
        ).encode()
        self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Type", "application/problem+json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _proxy(self, method: str) -> None:
        if not proxy_path(self.path):
            self._problem(404, "This route is not a feature API route.")
            return
        raw_length = self.headers.get("Content-Length", "0")
        if (
            self.headers.get("Transfer-Encoding")
            or not raw_length.isascii()
            or not raw_length.isdecimal()
        ):
            self._problem(
                400, "A non-negative Content-Length is required; chunked requests are unsupported."
            )
            return
        try:
            length = int(raw_length)
        except ValueError:
            self._problem(400, "Content-Length is not a supported integer.")
            return
        if length > MAX_REQUEST_BYTES:
            self._problem(413, "The request body is too large.")
            return
        try:
            data = self.rfile.read(length) if length else None
            if data is not None and len(data) != length:
                self._problem(400, "The request body is incomplete.")
                return
            headers = {"Accept": "application/json", "Content-Type": "application/json"}
            for name in ("X-Request-ID", "Idempotency-Key"):
                if value := self.headers.get(name):
                    headers[name] = value
            request = Request(
                BACKEND.rstrip("/") + self.path, data=data, method=method, headers=headers
            )
            try:
                with urlopen(request, timeout=15) as response:
                    body = response.read(MAX_RESPONSE_BYTES + 1)
                    status = response.status
                    media = response.headers.get("Content-Type", "application/json")
                    request_id = response.headers.get("X-Request-ID")
            except HTTPError as error:
                with error:
                    body = error.read(MAX_RESPONSE_BYTES + 1)
                    status = error.code
                    media = error.headers.get("Content-Type", "application/problem+json")
                    request_id = error.headers.get("X-Request-ID")
            if len(body) > MAX_RESPONSE_BYTES:
                self._problem(502, "The upstream response exceeded the development proxy limit.")
                return
        except OSError:
            self._problem(502, "The feature backend could not be reached.")
            return
        self.send_response(status)
        self.send_header("Content-Type", media)
        self.send_header("Content-Length", str(len(body)))
        if request_id:
            self.send_header("X-Request-ID", request_id)
        self.end_headers()
        if method != "HEAD":
            self.wfile.write(body)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(os.getenv("PORT", "5600"))), Handler).serve_forever()
