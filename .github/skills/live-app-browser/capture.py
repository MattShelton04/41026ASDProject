"""Capture full-page screenshots of live routes and report browser-side problems.

Usage: uv run python .github/skills/live-app-browser/capture.py OUT_DIR name=URL [name=URL ...]
       [--width 1440] [--height 1000] [--wait-ms 1500]

For each route, prints the page title and any console errors, uncaught exceptions, failed
requests and HTTP responses of 400 or above. Each route loads in a fresh page so hash routes
render from a clean start.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import Browser, ConsoleMessage, Response, sync_playwright


def capture(
    browser: Browser, url: str, target: Path, *, viewport: dict[str, int], wait_ms: int
) -> tuple[str, list[str]]:
    """Screenshot one URL and return its title and the problems observed while loading it."""
    issues: list[str] = []

    def on_console(message: ConsoleMessage) -> None:
        if message.type == "error":
            issues.append(f"console: {message.text}")

    def on_response(response: Response) -> None:
        if response.status >= 400:
            issues.append(f"HTTP {response.status}: {response.url}")

    page = browser.new_page(viewport=viewport)  # type: ignore[arg-type]
    page.on("console", on_console)
    page.on("response", on_response)
    page.on("pageerror", lambda error: issues.append(f"exception: {error}"))
    page.on(
        "requestfailed", lambda request: issues.append(f"failed ({request.failure}): {request.url}")
    )
    try:
        page.goto(url, wait_until="networkidle")
        page.wait_for_timeout(wait_ms)
        page.screenshot(path=str(target), full_page=True)
        return page.title(), issues
    finally:
        page.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path)
    parser.add_argument("routes", nargs="+", help="name=URL pairs")
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=1000)
    parser.add_argument("--wait-ms", type=int, default=1500)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for route in args.routes:
            name, _, url = route.partition("=")
            if not url:
                parser.error(f"expected name=URL, got {route!r}")
            target = args.out / f"{name}.png"
            title, issues = capture(
                browser,
                url,
                target,
                viewport={"width": args.width, "height": args.height},
                wait_ms=args.wait_ms,
            )
            print(f"{name}: {title!r} -> {target} ({len(issues)} issue(s))")
            for issue in issues:
                print(f"    {issue[:240]}")
        browser.close()


if __name__ == "__main__":
    main()
