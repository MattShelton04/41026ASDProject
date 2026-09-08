"""Loopback-only same-origin server for Shared and Feature 1 UI fixtures."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import threading
import time
import uuid
from collections import OrderedDict
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import parse_qs, unquote, urlsplit
from urllib.request import urlopen

from ai_mode.operations_api import ALLOWED_SHARED_ASSETS
from scripts.onboarding import load_enabled_projection
from scripts.ui_fixtures import (
    REQUEST_ID,
    SCENARIOS,
    fixture_response,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SHARED_FRONTEND = REPOSITORY_ROOT / "shared" / "frontend"
LOOPBACK_HOST = "127.0.0.1"
DEFAULT_PORT = 5300
SCENARIO_COOKIE = "propertyscope_ui_scenario"
SESSION_COOKIE = "propertyscope_ui_session"
MAX_SOURCE_SESSIONS = 64


def _enabled_frontends() -> tuple[tuple[str, Path], ...]:
    frontends: list[tuple[str, Path]] = []
    for feature in load_enabled_projection(REPOSITORY_ROOT).features:
        if feature.frontend is None:
            continue
        route = next((item.path for item in feature.routes if item.kind == "frontend"), None)
        if route is not None:
            frontends.append(
                (route.rstrip("/") + "/", REPOSITORY_ROOT / feature.frontend.asset_root)
            )
    return tuple(sorted(frontends))


FEATURE_FRONTENDS = _enabled_frontends()

CANARY_PAGES = {
    "/__ui-fixture__/canary/clean": """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Clean UI audit canary</title></head>
<body><main><h1>Clean UI audit canary</h1><button type="button">Safe action</button></main></body>
</html>""",
    "/__ui-fixture__/canary/overflow": """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Overflow UI audit canary</title>
<style>html,body{margin:0}.canary-overflow{width:calc(100vw + 24px);height:80px}</style></head>
<body><main><h1>Overflow UI audit canary</h1>
<div class="canary-overflow">overflow</div></main></body>
</html>""",
    "/__ui-fixture__/canary/console-error": """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Console UI audit canary</title></head>
<body><main><h1>Console UI audit canary</h1></main>
<script>console.error("ui-audit-canary");</script></body></html>""",
    "/__ui-fixture__/canary/below-fold": """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Below-fold UI audit canary</title></head>
<body><main><h1>Below-fold UI audit canary</h1>
<button style="position:absolute;top:1400px;width:20px;height:20px" type="button"></button>
</main></body></html>""",
    "/__ui-fixture__/canary/destructive-actions": """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Destructive action audit canary</title></head>
<body><nav><a data-audit-id="safe-published-nav" href="#published">Published data</a></nav>
<main><h1>Destructive action audit canary</h1>
<label>Status <select data-audit-id="safe-status-select"><option>Published</option>
<option>Rejected</option><option>Cancelled</option></select></label>
<section aria-label="Destructive triggers">
<button data-audit-id="trigger-delete">Delete</button>
<button data-audit-id="trigger-delete-definition">Delete definition</button>
<button data-audit-id="trigger-delete-version">Delete version</button>
<button data-audit-id="trigger-publish">Publish</button>
<button data-audit-id="trigger-publish-version">Publish version</button>
<button data-audit-id="trigger-reject">Reject</button>
<button data-audit-id="trigger-reject-version">Reject version</button>
<button data-audit-id="trigger-submit-for-review">Submit for review</button>
<button data-audit-id="trigger-start-update">Start update</button>
<button data-audit-id="trigger-load-earlier-data">Load earlier data</button>
<button data-audit-id="trigger-resume-update">Resume update</button>
<button data-audit-id="trigger-retry-update">Retry update</button>
<button data-audit-id="trigger-use-downloaded-file">Use downloaded file</button>
<button data-audit-id="trigger-cancel-update">Cancel update</button>
<button data-audit-id="trigger-start-ai-review">Start AI review</button>
</section>
<dialog open aria-label="Confirmation actions">
<button data-audit-id="safe-dialog-cancel">Cancel</button>
<button data-audit-id="confirm-delete">Delete</button>
<button data-audit-id="confirm-delete-definition">Delete definition</button>
<button data-audit-id="confirm-delete-version">Delete version</button>
<button data-audit-id="confirm-publish">Publish</button>
<button data-audit-id="confirm-publish-version">Publish version</button>
<button data-audit-id="confirm-reject">Reject</button>
<button data-audit-id="confirm-reject-version">Reject version</button>
<button data-audit-id="confirm-submit-for-review">Submit for review</button>
<button data-audit-id="confirm-start-update">Start update</button>
<button data-audit-id="confirm-load-earlier-data">Load earlier data</button>
<button data-audit-id="confirm-resume-update">Resume update</button>
<button data-audit-id="confirm-retry-update">Retry update</button>
<button data-audit-id="confirm-use-downloaded-file">Use downloaded file</button>
<button data-audit-id="confirm-cancel-update">Cancel update</button>
<button data-audit-id="confirm-start-ai-review">Start AI review</button>
</dialog></main></body></html>""",
    "/__ui-fixture__/canary/interaction": """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Interaction UI audit canary</title></head>
<body><main><h1>Interaction UI audit canary</h1>
<details><summary>More actions</summary><button type="button">Nested safe action</button></details>
<button id="open-dialog" type="button">Open actions</button>
<dialog id="action-dialog" aria-labelledby="dialog-title"><h2 id="dialog-title">Actions</h2>
<button id="delete-record" type="button">Delete record</button>
<button id="cancel-dialog" type="button">Cancel</button></dialog></main>
<script>
const dialog=document.querySelector('#action-dialog');
document.querySelector('#open-dialog').addEventListener('click',()=>dialog.showModal());
document.querySelector('#cancel-dialog').addEventListener('click',()=>dialog.close());
</script></body></html>""",
}


class UIFixtureServer(ThreadingHTTPServer):
    """HTTP server carrying the immutable default fixture scenario."""

    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, port: int, scenario: str) -> None:
        super().__init__((LOOPBACK_HOST, port), UIFixtureRequestHandler)
        self.fixture_scenario = scenario
        self.source_fragment_apps: OrderedDict[str, Any] = OrderedDict()
        self.source_fragment_lock = threading.RLock()

    def source_fragment_app(self, session_key: str, scenario: str) -> Any:
        """Return one bounded Flask fragment app over session-isolated in-memory data."""
        cache_key = f"{scenario}:{session_key}"
        with self.source_fragment_lock:
            if app := self.source_fragment_apps.get(cache_key):
                self.source_fragment_apps.move_to_end(cache_key)
                return app
            from propertyscope_data_platform.app import create_app as create_feature_app
            from scripts.ui_fixture_sources import FixtureSourceStoreClient

            app = create_feature_app(
                store_client=FixtureSourceStoreClient(
                    session_key=session_key,
                    scenario=scenario,
                ),
                feature_root=REPOSITORY_ROOT / "student-1",
            )
            app.config.update(TESTING=True)
            self.source_fragment_apps[cache_key] = app
            while len(self.source_fragment_apps) > MAX_SOURCE_SESSIONS:
                self.source_fragment_apps.popitem(last=False)
            return app


class UIFixtureRequestHandler(BaseHTTPRequestHandler):
    """Serve production frontend source and contract-shaped fixture responses."""

    server: UIFixtureServer
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        self._handle(include_body=True)

    def do_HEAD(self) -> None:
        self._handle(include_body=False)

    def do_POST(self) -> None:
        self._handle(include_body=True)

    def do_PUT(self) -> None:
        self._handle(include_body=True)

    def do_PATCH(self) -> None:
        self._handle(include_body=True)

    def do_DELETE(self) -> None:
        self._handle(include_body=True)

    def log_message(self, format: str, *args: Any) -> None:
        if os.environ.get("PROPERTYSCOPE_UI_FIXTURE_LOG") == "1":
            super().log_message(format, *args)

    def handle(self) -> None:
        try:
            super().handle()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            # Fresh browser contexts can close an HTTP/1.1 socket after receiving enough data.
            # These exact peer-disconnect exceptions are expected and need no server traceback.
            return

    def _handle(self, *, include_body: bool) -> None:
        if not self._safe_host():
            self._send_bytes(
                HTTPStatus.FORBIDDEN,
                b"Loopback Host header required.\n",
                "text/plain; charset=utf-8",
                include_body=include_body,
            )
            return
        if not self._consume_request_body(include_body=include_body):
            return
        target = urlsplit(self.path)
        scenario, selected_by_query = self._scenario(target.query)
        self._response_fixture_session = self._fixture_session(target.query)
        if target.path in CANARY_PAGES:
            self._send_bytes(
                HTTPStatus.OK,
                CANARY_PAGES[target.path].encode(),
                "text/html; charset=utf-8",
                include_body=include_body,
            )
            return
        if target.path == "/healthz":
            self._send_bytes(
                HTTPStatus.OK,
                b"ok\n",
                "text/plain; charset=utf-8",
                include_body=include_body,
            )
            return
        if target.path.startswith("/fragments/data-platform/v1/sources"):
            if scenario == "slow":
                time.sleep(1.25)
            response = self._source_fragment_response(target.path, target.query, scenario)
            self._send_bytes(
                response.status_code,
                response.get_data(),
                response.content_type,
                include_body=include_body,
                scenario=scenario if selected_by_query else None,
                request_id=response.headers.get("X-Request-ID") or REQUEST_ID,
                extra_headers={
                    name: response.headers[name]
                    for name in (
                        "Cache-Control",
                        "HX-Retarget",
                        "HX-Reswap",
                        "HX-Trigger-After-Swap",
                    )
                    if name in response.headers
                },
            )
            return
        if target.path.startswith("/api/") or target.path in {
            "/health/ready",
            "/__ui-fixture__/ready",
        }:
            response = fixture_response(self.command, target.path, target.query, scenario)
            if response.delay_seconds:
                time.sleep(response.delay_seconds)
            payload = (
                b""
                if response.status == HTTPStatus.NO_CONTENT
                else json.dumps(response.body, sort_keys=True, separators=(",", ":")).encode()
            )
            self._send_bytes(
                response.status,
                payload,
                f"{response.content_type}; charset=utf-8",
                include_body=include_body,
                scenario=scenario if selected_by_query else None,
                request_id=self.headers.get("X-Request-ID")
                or response.body.get("request_id")
                or REQUEST_ID,
            )
            return
        for feature_prefix, _feature_root in FEATURE_FRONTENDS:
            if target.path == feature_prefix.rstrip("/"):
                self.send_response(HTTPStatus.PERMANENT_REDIRECT)
                self.send_header("Location", f"{feature_prefix}{self._query_suffix(target.query)}")
                self._send_session_cookie()
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
        path = self._static_path(target.path)
        if path is None or not path.is_file():
            self._send_bytes(
                HTTPStatus.NOT_FOUND,
                b"Fixture asset not found.\n",
                "text/plain; charset=utf-8",
                include_body=include_body,
            )
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self._send_bytes(
            HTTPStatus.OK,
            path.read_bytes(),
            content_type,
            include_body=include_body,
            scenario=scenario if selected_by_query else None,
        )

    def _safe_host(self) -> bool:
        host = self.headers.get("Host", "").partition(":")[0].strip("[]").lower()
        return host in {"127.0.0.1", "localhost", "::1"}

    def _consume_request_body(self, *, include_body: bool) -> bool:
        self.request_body = b""
        if self.command in {"GET", "HEAD"}:
            return True
        raw_length = self.headers.get("Content-Length", "0")
        if not raw_length.isdigit() or int(raw_length) > 1_000_000:
            self._send_bytes(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                b"Fixture request body must be at most 1 MB.\n",
                "text/plain; charset=utf-8",
                include_body=include_body,
            )
            return False
        self.request_body = self.rfile.read(int(raw_length))
        return True

    def _fixture_session(self, query: str) -> str:
        selected = parse_qs(query).get("test", [None])[0]
        if selected:
            return str(uuid.uuid5(uuid.NAMESPACE_URL, f"propertyscope-ui:{selected[:200]}"))
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        if morsel := cookie.get(SESSION_COOKIE):
            try:
                return str(uuid.UUID(morsel.value))
            except ValueError:
                pass
        return str(uuid.uuid4())

    def _source_fragment_response(self, path: str, query: str, scenario: str) -> Any:
        app = self.server.source_fragment_app(self._response_fixture_session, scenario)
        forwarded = {
            name: self.headers[name]
            for name in (
                "HX-Request",
                "HX-Target",
                "HX-Trigger",
                "X-Request-ID",
                "Idempotency-Key",
                "traceparent",
            )
            if name in self.headers
        }
        forwarded.setdefault("X-Request-ID", REQUEST_ID)
        content_type = self.headers.get("Content-Type")
        return app.test_client().open(
            f"{path}{self._query_suffix(query)}",
            method=self.command,
            data=self.request_body,
            headers=forwarded,
            content_type=content_type,
        )

    def _scenario(self, query: str) -> tuple[str, bool]:
        selected = parse_qs(query).get("scenario", [None])[0]
        if selected is not None:
            return selected, True
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        if morsel := cookie.get(SCENARIO_COOKIE):
            return morsel.value, False
        header = self.headers.get("X-PropertyScope-UI-Scenario")
        return (header or self.server.fixture_scenario), False

    def _static_path(self, request_path: str) -> Path | None:
        decoded = unquote(request_path)
        operations_assets = "/operations/ai-mode/assets/"
        operations_tokens = "/operations/ai-mode/design-system/"
        operations_shared = "/operations/ai-mode/shared/"
        if decoded.startswith(operations_assets):
            relative = decoded.removeprefix(operations_assets)
            root = SHARED_FRONTEND / "operations" / "ai-mode"
        elif decoded.startswith(operations_tokens):
            relative = decoded.removeprefix(operations_tokens)
            root = SHARED_FRONTEND / "design-system"
        elif decoded.startswith(operations_shared):
            relative = decoded.removeprefix(operations_shared)
            if relative not in ALLOWED_SHARED_ASSETS:
                return None
            root = SHARED_FRONTEND
        elif matched := next(
            ((prefix, root) for prefix, root in FEATURE_FRONTENDS if decoded.startswith(prefix)),
            None,
        ):
            feature_prefix, feature_root = matched
            relative = decoded.removeprefix(feature_prefix) or "index.html"
            if relative.startswith(
                ("ai-chat/", "browser/", "design-system/", "mapping/", "vendor/")
            ):
                root = SHARED_FRONTEND
            else:
                root = feature_root
        else:
            relative = decoded.lstrip("/") or "index.html"
            root = SHARED_FRONTEND
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError:
            return None
        if candidate.is_dir():
            candidate /= "index.html"
        return candidate

    @staticmethod
    def _query_suffix(query: str) -> str:
        return f"?{query}" if query else ""

    def _send_bytes(
        self,
        status: int,
        payload: bytes,
        content_type: str,
        *,
        include_body: bool,
        scenario: str | None = None,
        request_id: object = None,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        if request_id:
            self.send_header("X-Request-ID", str(request_id))
        for name, value in (extra_headers or {}).items():
            if name.lower() not in {"content-length", "content-type", "set-cookie"}:
                self.send_header(name, value)
        if scenario is not None:
            self.send_header(
                "Set-Cookie",
                f"{SCENARIO_COOKIE}={scenario}; Path=/; SameSite=Strict",
            )
        self._send_session_cookie()
        self.end_headers()
        if include_body:
            try:
                self.wfile.write(payload)
            except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                return

    def _send_session_cookie(self) -> None:
        session_key = getattr(self, "_response_fixture_session", None)
        if session_key:
            self.send_header(
                "Set-Cookie",
                f"{SESSION_COOKIE}={session_key}; Path=/; SameSite=Strict; HttpOnly",
            )


def _wait_until_ready(port: int, timeout_seconds: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    url = f"http://{LOOPBACK_HOST}:{port}/__ui-fixture__/ready"
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=0.5) as response:
                if response.status == HTTPStatus.OK:
                    return
        except (OSError, URLError):
            time.sleep(0.05)
    raise RuntimeError(f"UI fixture server did not become ready at {url}")


def serve_ui_fixtures(*, port: int, scenario: str) -> None:
    """Serve until interrupted, and always close the listening socket."""
    if scenario not in SCENARIOS:
        raise RuntimeError(f"scenario must be one of: {', '.join(SCENARIOS)}")
    if not 1 <= port <= 65535:
        raise RuntimeError("UI fixture port must be between 1 and 65535")
    try:
        server = UIFixtureServer(port, scenario)
    except OSError as exc:
        raise RuntimeError(
            f"UI fixture port {port} is unavailable on {LOOPBACK_HOST}. "
            "Set PROPERTYSCOPE_UI_FIXTURE_PORT or pass --port with a free port."
        ) from exc
    thread = threading.Thread(target=server.serve_forever, name="ui-fixture-server")
    thread.start()
    try:
        _wait_until_ready(port)
        print(f"UI fixture scenario: {scenario}", flush=True)
        print(
            f"Shared:             http://{LOOPBACK_HOST}:{port}/?scenario={scenario}#home",
            flush=True,
        )
        print(
            "Property Discovery: "
            f"http://{LOOPBACK_HOST}:{port}/features/data-platform/"
            f"?scenario={scenario}#properties",
            flush=True,
        )
        print(
            "Data Operations:    "
            f"http://{LOOPBACK_HOST}:{port}/features/data-platform/"
            f"?scenario={scenario}#overview",
            flush=True,
        )
        print("Press Ctrl+C to stop the fixture server.", flush=True)
        while thread.is_alive():
            thread.join(0.5)
    except KeyboardInterrupt:
        print("\nStopping UI fixture server.", flush=True)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PROPERTYSCOPE_UI_FIXTURE_PORT", DEFAULT_PORT)),
    )
    parser.add_argument(
        "--scenario",
        choices=SCENARIOS,
        default=os.environ.get("PROPERTYSCOPE_UI_SCENARIO", "populated"),
    )
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    try:
        serve_ui_fixtures(port=arguments.port, scenario=arguments.scenario)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
