"""Browser smoke for all five production feature shells with stubbed APIs.

This does not test the live Docker stack, authenticated CRUD or real providers.
The optional injected-document mode exercises DOM/CSS/modules in about:blank;
it does not verify real-origin navigation, cookies, CSP or storage persistence.
"""

from __future__ import annotations

import argparse
import json
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.request import urlopen

from playwright.sync_api import Page, Route, sync_playwright

from scripts.ui_fixture_server import UIFixtureServer

FEATURES = (
    ("data-platform", "properties"),
    ("market-intelligence", "market-cases"),
    ("suburb-analytics", "explore"),
    ("due-diligence", "site-reviews"),
    ("buyer-workspaces", "buyer-cases"),
)
WIDTHS = (320, 390, 768, 1440)
TEST_CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "*",
    "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
}


def intercept(route: Route, *, mode: str, port: int, injected: bool = False) -> None:
    """Allow only the fixture host; never make external/provider requests."""
    url = urlsplit(route.request.url)
    if url.hostname != "127.0.0.1" or url.port != port:
        route.abort()
        return
    headers = TEST_CORS if injected else {}
    if injected and route.request.method == "OPTIONS":
        route.fulfill(status=204, headers=headers)
        return
    path = url.path
    if path.startswith("/api/") or path.endswith("/health/ready"):
        if mode == "unavailable":
            route.fulfill(
                status=503,
                headers=headers,
                json={
                    "status": 503,
                    "code": "service_unavailable",
                    "detail": "Deterministic unavailable service.",
                },
            )
            return
        if not path.startswith(("/api/data-platform/", "/api/shared-health/")):
            body: dict[str, Any] = {
                "items": [],
                "count": 0,
                "page": {"total": 0},
                "available": False,
            }
            if path.endswith("/health/ready"):
                body = {"status": "healthy"}
            elif path.endswith("/capabilities"):
                body = {"available": False, "suggested_questions": [], "tools": []}
            route.fulfill(json=body, headers=headers)
            return
    if injected:
        # CORS exists only in this intercepted test context, not in application configuration.
        response = route.fetch()
        route.fulfill(response=response, headers={**response.headers, **headers})
    else:
        route.continue_()


def load_document(page: Page, *, base: str, feature: str, fragment: str, injected: bool) -> None:
    url = f"{base}/features/{feature}/?scenario=empty#{fragment}"
    if not injected:
        page.goto(url, wait_until="networkidle")
        return
    with urlopen(url, timeout=10) as response:
        html = response.read(2_000_000).decode("utf-8")
    setup = (
        f'<base href="{base}/features/{feature}/">'
        f"<script>window.PROPERTYSCOPE_HOME_URL={json.dumps(base + '/')};"
        f"location.hash={json.dumps(fragment)};</script>"
    )
    page.set_content(html.replace("<head>", "<head>" + setup, 1), wait_until="networkidle")


def exercise_mobile(page: Page, feature: str) -> None:
    if feature in {"market-intelligence", "buyer-workspaces"}:
        page.locator("#new-case").click()
        dialog = page.locator("#case-dialog")
    elif feature == "due-diligence":
        page.get_by_role("button", name="New site review", exact=True).click()
        dialog = page.locator("#review-dialog")
    elif feature == "suburb-analytics":
        page.locator("#show-bookmarks").click()
        dialog = page.locator("#bookmark-dialog")
    else:
        page.locator("#nav-toggle").click()
        assert page.locator("#nav-toggle").get_attribute("aria-expanded") == "true"
        page.keyboard.press("Escape")
        assert page.locator("#nav-toggle").get_attribute("aria-expanded") == "false"
        return
    assert dialog.is_visible()
    page.keyboard.press("Escape")
    assert not dialog.is_visible()
    if feature == "suburb-analytics":
        page.evaluate("location.hash = 'unknown-route'")
        page.wait_for_timeout(100)
        assert page.locator("#explore-view").is_visible()


def run(
    output: Path,
    executable: str | None = None,
    *,
    injected: bool = False,
    feature_name: str | None = None,
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    server = UIFixtureServer(0, "empty")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    cases: list[dict[str, Any]] = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=executable)
            try:
                for feature, fragment in FEATURES:
                    if feature_name and feature_name != feature:
                        continue
                    for mode in ("empty", "unavailable"):
                        for width in WIDTHS:
                            print(f"Checking {feature} {mode} {width}", flush=True)
                            context = browser.new_context(
                                viewport={"width": width, "height": 1000},
                                reduced_motion="reduce",
                            )
                            context.set_default_timeout(3000)
                            context.route(
                                "**/*",
                                lambda route, mode=mode: intercept(
                                    route, mode=mode, port=server.server_port, injected=injected
                                ),
                            )
                            page = context.new_page()
                            errors: list[str] = []
                            page.on(
                                "pageerror",
                                lambda error, errors=errors: errors.append(str(error)),
                            )
                            row: dict[str, Any] = {
                                "feature": feature,
                                "mode": mode,
                                "width": width,
                            }
                            try:
                                load_document(
                                    page,
                                    base=base,
                                    feature=feature,
                                    fragment=fragment,
                                    injected=injected,
                                )
                                page.wait_for_timeout(150)
                                nav = page.locator(".ps-product-nav a")
                                assert nav.count() == 5, "Expected five shared product links"
                                toggle = page.locator(".ps-product-menu-toggle")
                                if toggle.is_visible():
                                    assert not nav.first.is_visible()
                                    toggle.click()
                                    assert toggle.get_attribute("aria-expanded") == "true"
                                    assert all(nav.nth(i).is_visible() for i in range(5))
                                    page.keyboard.press("Escape")
                                    assert toggle.get_attribute("aria-expanded") == "false"
                                    assert toggle.evaluate("el => el === document.activeElement")
                                else:
                                    assert all(nav.nth(i).is_visible() for i in range(5))
                                for href in nav.evaluate_all("links => links.map(a => a.href)"):
                                    assert href.startswith(f"{base}/#"), href
                                overflow = page.evaluate(
                                    "Math.max(0, document.documentElement.scrollWidth-innerWidth)"
                                )
                                row["horizontal_overflow_px"] = overflow
                                assert overflow <= 1, f"Page overflows by {overflow}px"
                                assert not errors, errors
                                if mode == "empty" and width == 390:
                                    exercise_mobile(page, feature)
                                if mode == "empty" and width in (390, 1440):
                                    page.screenshot(
                                        path=str(output / f"{feature}-{width}.png"), full_page=True
                                    )
                                row["status"] = "passed"
                            except Exception as error:
                                row["status"] = "failed"
                                row["error"] = str(error)
                                page.screenshot(
                                    path=str(output / f"FAILED-{feature}-{mode}-{width}.png"),
                                    full_page=True,
                                )
                            print(row.get("status"), row.get("error", ""), flush=True)
                            row["page_errors"] = errors
                            cases.append(row)
                            context.unroute_all(behavior="ignoreErrors")
                            context.close()
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    report = {
        "scope": "Production assets with empty/unavailable APIs; not live Docker or CRUD",
        "document_mode": "injected about:blank" if injected else "fixture-origin navigation",
        "cases": cases,
        "passed": sum(row["status"] == "passed" for row in cases),
        "failed": sum(row["status"] == "failed" for row in cases),
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".propertyscope-runtime/feature-smoke"))
    parser.add_argument(
        "--chromium", help="Installed Chromium path; defaults to Playwright's browser"
    )
    parser.add_argument(
        "--injected-document", action="store_true", help="DOM-only, not origin testing"
    )
    parser.add_argument("--feature", choices=[name for name, _ in FEATURES])
    options = parser.parse_args()
    report = run(
        options.output,
        options.chromium,
        injected=options.injected_document,
        feature_name=options.feature,
    )
    print(f"Feature smoke: {report['passed']} passed, {report['failed']} failed")
    return int(report["failed"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
