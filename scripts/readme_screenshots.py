"""Capture deterministic application screenshots used by the root README."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

from scripts.ui_fixture_server import DEFAULT_PORT
from scripts.ui_smoke import fixture_runtime

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPOSITORY_ROOT / "docs" / "images" / "readme"
VIEWPORT = {"width": 1440, "height": 1000}


@dataclass(frozen=True)
class ReadmeScreenshot:
    """One stable README capture and its rendered readiness contract."""

    filename: str
    path: str
    heading: str
    ready_selector: str | None = None


SCREENSHOTS = (
    ReadmeScreenshot(
        filename="propertyscope-home.png",
        path="/?scenario=populated#home",
        heading="Research a NSW property from published data.",
        ready_selector="#feature-area-list [data-feature-id]",
    ),
    ReadmeScreenshot(
        filename="property-search.png",
        path=("/features/data-platform/?scenario=populated#properties?q=11%20Example%20Street"),
        heading="Find a NSW property",
        ready_selector=".result-card",
    ),
    ReadmeScreenshot(
        filename="data-overview.png",
        path="/features/data-platform/?scenario=populated#overview",
        heading="Data overview",
        ready_selector='[aria-label="Data readiness summary"]',
    ),
)


def _wait_until_ready(page: Page, screenshot: ReadmeScreenshot) -> None:
    page.get_by_role("heading", name=screenshot.heading).wait_for(state="visible")
    if screenshot.ready_selector is not None:
        page.locator(screenshot.ready_selector).first.wait_for(state="visible")


def capture_readme_screenshots(*, port: int, output: Path) -> None:
    """Render stable populated fixtures and replace the committed README images."""
    output.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    with fixture_runtime(port, "populated") as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                viewport=VIEWPORT,
                color_scheme="light",
                locale="en-AU",
                timezone_id="Australia/Sydney",
                reduced_motion="reduce",
                service_workers="block",
            )
            for screenshot in SCREENSHOTS:
                failures.clear()
                page = context.new_page()
                try:
                    page.on(
                        "pageerror",
                        lambda error: failures.append(f"page exception: {error}"),
                    )
                    page.on(
                        "console",
                        lambda message: (
                            failures.append(f"console error: {message.text}")
                            if message.type == "error"
                            else None
                        ),
                    )
                    page.goto(
                        f"{base_url}{screenshot.path}",
                        wait_until="domcontentloaded",
                    )
                    _wait_until_ready(page, screenshot)
                    if failures:
                        detail = "; ".join(failures)
                        raise RuntimeError(
                            f"{screenshot.path} emitted unexpected browser errors: {detail}"
                        )
                    destination = output / screenshot.filename
                    page.screenshot(
                        path=destination,
                        full_page=False,
                        animations="disabled",
                    )
                    print(
                        f"Captured {destination}",
                        flush=True,
                    )
                finally:
                    page.close()
        finally:
            browser.close()


def main() -> int:
    """Run the README screenshot capture command."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()
    capture_readme_screenshots(port=arguments.port, output=arguments.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
