"""Render production frontends against isolated synthetic browser fixtures.

The optional injected-document profile is deliberately weaker than real-origin
navigation. It cannot validate CSP, cookies, storage, service integration or a
live model. Reports retain that distinction, failed requests and page errors.
"""

from __future__ import annotations

import argparse
import json
import re
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit
from urllib.request import urlopen

from playwright.sync_api import Page, Route, sync_playwright

from scripts.ui_experience_fixtures import BUYER_ID, REVIEW_ID, ExperienceFixtures
from scripts.ui_feature_smoke import TEST_CORS
from scripts.ui_fixture_server import UIFixtureServer

ROUTES = {
    "home": "/#home",
    "areas": "/#features",
    "status": "/#system-status",
    "sources-history": "/#evidence",
    "roadmap": "/#release-roadmap",
    "assistant": "/#assistant",
    "properties": "/features/data-platform/#properties?q=11%20Example%20Street",
    "property": "/features/data-platform/#properties/11111111-1111-4111-8111-111111111111",
    "overview": "/features/data-platform/#overview",
    "sources": "/features/data-platform/#sources",
    "jobs": "/features/data-platform/#jobs",
    "job": "/features/data-platform/#jobs/20000000-0000-0000-0000-000000000001",
    "source": "/features/data-platform/#sources/10000000-0000-0000-0000-000000000001",
    "release": "/features/data-platform/#releases/60000000-0000-0000-0000-000000000001",
    "candidate": "/features/data-platform/#releases/60000000-0000-0000-0000-000000000011",
    "quality-detail": "/features/data-platform/#quality/30000000-0000-0000-0000-000000000001",
    "artifact": "/features/data-platform/#artifacts/30000000-0000-0000-0000-000000000001",
    "data-product": "/features/data-platform/#data-products/property-identities",
    "ai-review": "/features/data-platform/#ai",
    "ai-review-detail": "/features/data-platform/#ai/70000000-0000-4000-8000-000000000001",
    "runs": "/features/data-platform/#runs",
    "run": "/features/data-platform/#runs/30000000-0000-0000-0000-000000000001",
    "releases": "/features/data-platform/#releases",
    "quality": "/features/data-platform/#quality",
    "artifacts": "/features/data-platform/#artifacts",
    "coverage": "/features/data-platform/#coverage",
    "data-products": "/features/data-platform/#data-products",
    "data-assistant": "/features/data-platform/#assistant",
    "ai-activity": "/operations/ai-mode/",
    "market": "/features/market-intelligence/#market-cases",
    "suburbs": "/features/suburb-analytics/#explore",
    "trends": "/features/suburb-analytics/#trends",
    "published": "/features/suburb-analytics/#published",
    "comparisons": "/features/suburb-analytics/#comparisons",
    "suburb-assistant": "/features/suburb-analytics/#assistant",
    "due-diligence": "/features/due-diligence/#site-reviews",
    "site-review": f"/features/due-diligence/#site-reviews/{REVIEW_ID}",
    "buyer": "/features/buyer-workspaces/#buyer-cases",
    "buyer-case": f"/features/buyer-workspaces/#buyer-cases/{BUYER_ID}",
}
CORE = ("home", "assistant", "properties", "overview", "ai-activity", "market",
        "suburbs", "trends", "site-review", "buyer-case")


class BrowserSession:
    """Only known fixture APIs may mutate; other network access is loopback-only."""

    def __init__(self, base: str, mode: str, injected: bool) -> None:
        if urlsplit(base).hostname != "127.0.0.1" or urlsplit(base).scheme != "http":
            raise ValueError("Use a loopback-only HTTP fixture host (127.0.0.1).")
        self.base = base
        self.port = urlsplit(base).port
        self.injected = injected
        self.fixture = ExperienceFixtures(mode)
        self.failures: list[dict[str, Any]] = []
        self.pending: list[tuple[Route, int, Any]] = []
        self.defer = mode == "slow"
        self.blocked_external: list[str] = []

    def fulfill(self, route: Route, status: int, body: Any) -> None:
        if status >= 400:
            self.failures.append({"method": route.request.method,
                                  "path": urlsplit(route.request.url).path,
                                  "status": status})
        options: dict[str, Any] = {"status": status}
        if self.injected:
            options["headers"] = TEST_CORS
        if status != 204:
            options["json"] = body
        route.fulfill(**options)

    def intercept(self, route: Route) -> None:
        url = urlsplit(route.request.url)
        if url.hostname != "127.0.0.1" or url.port != self.port:
            self.blocked_external.append(route.request.url)
            route.abort()
            return
        if route.request.method == "OPTIONS":
            self.fulfill(route, 204, {})
            return
        if url.path.startswith("/api/") or url.path.endswith("/health/ready"):
            # Source HTML is rendered by the canonical Flask fragment fixture,
            # not reconstructed by this browser-only JSON adapter.
            if "/ui/" not in url.path and not url.path.endswith("/ui"):
                body = route.request.post_data_json if route.request.post_data else None
                status, payload = self.fixture.response(
                    route.request.method, url.path, url.query, body
                )
                if self.defer:
                    self.pending.append((route, status, payload))
                else:
                    self.fulfill(route, status, payload)
                return
        response = route.fetch()
        headers = {**response.headers, **(TEST_CORS if self.injected else {})}
        if response.status >= 400:
            self.failures.append({"method": route.request.method,
                                  "path": url.path, "status": response.status})
        route.fulfill(response=response, headers=headers)

    def release(self) -> None:
        """Release truly deferred API responses; do not fabricate a loading screen."""
        self.defer = False
        for route, status, payload in self.pending:
            self.fulfill(route, status, payload)
        self.pending.clear()

    def load(self, page: Page, path: str) -> None:
        url = self.base + path
        if not self.injected:
            page.goto(url, wait_until="domcontentloaded")
            return
        with urlopen(url, timeout=15) as response:
            html = response.read(3_000_000).decode("utf-8")
        # about:blank has an opaque origin. Only this explicit test profile gets
        # cross-origin fixture access; production HTMX/CSP are not changed.
        html = re.sub(
            r"(<meta name=\"htmx-config\" content=')([^']+)('>)",
            lambda match: match[1] + json.dumps({**json.loads(match[2]),
                                                "selfRequestsOnly": False}) + match[3],
            html,
        )
        html = re.sub(
            r'(hx-(?:get|post)=")([^"]+)(")',
            lambda match: match[1] + urljoin(url, match[2]) + match[3], html,
        )
        setup = (
            f'<base href="{url.split("#")[0]}">'
            f'<script>window.PROPERTYSCOPE_HOME_URL={json.dumps(self.base + "/")};'
            f'location.hash={json.dumps(urlsplit(url).fragment)};</script>'
        )
        page.set_content(html.replace("<head>", "<head>" + setup, 1),
                         wait_until="domcontentloaded")


def inspect(page: Page) -> dict[str, Any]:
    source = Path(__file__).with_name("ui_audit") / "experience_inventory.js"
    return page.evaluate(source.read_text(encoding="utf-8"))


def run(args: argparse.Namespace) -> dict[str, Any]:
    args.output.mkdir(parents=True, exist_ok=True)
    server = None
    base = args.base
    if not base:
        server = UIFixtureServer(0, "populated")
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_port}"
    rows = []
    route_names = list(ROUTES) if args.routes == "all" else args.routes.split(",")
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=args.executable, headless=True
            )
            for mode in args.scenarios.split(","):
                for width in [int(value) for value in args.widths.split(",")]:
                    for name in route_names:
                        print(f"{name} | {mode} | {width}", flush=True)
                        session = BrowserSession(base, mode, args.injected_document)
                        context = browser.new_context(
                            viewport={"width": width, "height": 1000},
                            reduced_motion="reduce" if not args.motion else "no-preference",
                        )
                        context.set_default_timeout(5000)
                        context.route("**/*", session.intercept)
                        page = context.new_page()
                        errors: list[str] = []
                        console: list[str] = []
                        page.on(
                            "pageerror",
                            lambda error, target=errors: target.append(error.stack or str(error)),
                        )
                        page.on("console", lambda msg, target=console:
                                target.append(msg.text) if msg.type == "error" else None)
                        row: dict[str, Any] = {"route": name, "path": ROUTES[name],
                                               "mode": mode, "width": width}
                        if args.injected_document and name in {"home", "sources", "source"}:
                            row["coverage_limit"] = (
                                "Opaque-origin profile cannot execute the real-origin HTMX "
                                "fragment flow. Capture is not a functional route pass."
                            )
                        prefix = args.output / f"{name}-{mode}-{width}"
                        try:
                            session.load(page, ROUTES[name])
                            page.wait_for_timeout(350)
                            if mode == "slow":
                                page.screenshot(path=f"{prefix}-loading.png", full_page=True, timeout=20000)
                                row["loading"] = inspect(page)
                                session.release()
                            page.wait_for_timeout(650)
                            row.update(inspect(page))
                            row["initial_scroll_y"] = page.evaluate("scrollY")
                            page.evaluate("scrollTo(0, 0)")
                            page.screenshot(path=f"{prefix}.png", full_page=True, timeout=20000)
                        except Exception as error:
                            row["error"] = str(error)
                        row.update(page_errors=errors, console_errors=console,
                                   failed_responses=session.failures,
                                   blocked_external=session.blocked_external,
                                   requests=session.fixture.requests)
                        rows.append(row)
                        context.unroute_all(behavior="ignoreErrors")
                        context.close()
            browser.close()
    finally:
        if server:
            server.shutdown()
            server.server_close()
    report = {
        "profile": "injected-document" if args.injected_document else "real-origin",
        "data": "Synthetic browser-only fixtures; not backend integration or live AI",
        "cases": rows,
        "counts": {"cases": len(rows), "overflow": sum(bool(row.get("overflow")) for row in rows),
                   "page_errors": sum(len(row["page_errors"]) for row in rows),
                   "exceptions": sum("error" in row for row in rows),
                   "profile_limited": sum("coverage_limit" in row for row in rows),
                   "failed_responses": sum(len(row["failed_responses"]) for row in rows),
                   "blocked_external": sum(len(row["blocked_external"]) for row in rows)},
    }
    (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["counts"]))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="Existing loopback fixture host, e.g. a clean baseline")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--routes", default=",".join(CORE))
    parser.add_argument("--scenarios", default="populated")
    parser.add_argument("--widths", default="390,1440")
    parser.add_argument("--executable")
    parser.add_argument("--injected-document", action="store_true")
    parser.add_argument("--motion", action="store_true")
    args = parser.parse_args()
    report = run(args)
    if any(report["counts"][key] for key in ("overflow", "page_errors", "exceptions")):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
