"""Local static/proxy server for the Student 3 frontend scaffold."""

from __future__ import annotations

import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

FRONTEND = Path(__file__).resolve().parent
REPOSITORY = FRONTEND.parents[1]
BACKEND = os.getenv("SUBURB_BACKEND_URL", "http://127.0.0.1:5301")


class Handler(SimpleHTTPRequestHandler):
    """Serve feature files, approved shared browser assets and backend routes."""

    def translate_path(self, path: str) -> str:
        relative = path.split("?", 1)[0].lstrip("/")
        if relative.startswith("design-system/"):
            return str(REPOSITORY / "shared" / "frontend" / relative)
        if relative.startswith(("mapping/", "browser/", "ai-chat/")):
            return str(REPOSITORY / "shared" / "frontend" / relative)
        candidate = FRONTEND / relative
        return str(candidate if candidate.is_file() else FRONTEND / "index.html")

    def do_GET(self) -> None:
        if self.path.startswith(("/api/suburb-analytics/", "/health/")):
            self._proxy("GET")
            return
        super().do_GET()

    def do_POST(self) -> None:
        self._proxy("POST")

    def do_PUT(self) -> None:
        self._proxy("PUT")

    def do_DELETE(self) -> None:
        self._proxy("DELETE")

    def _proxy(self, method: str) -> None:
        length = min(int(self.headers.get("Content-Length", "0")), 65_536)
        request = Request(
            BACKEND + self.path,
            data=self.rfile.read(length) if length else None,
            method=method,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=15) as response:
                body, status, media = (
                    response.read(1_048_576),
                    response.status,
                    response.headers.get("Content-Type", "application/json"),
                )
        except HTTPError as error:
            body, status, media = (
                error.read(65_536),
                error.code,
                error.headers.get("Content-Type", "application/problem+json"),
            )
        self.send_response(status)
        self.send_header("Content-Type", media)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(os.getenv("PORT", "5300"))), Handler).serve_forever()
