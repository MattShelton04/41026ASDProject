"""Minimal Playwright smoke for Shared, Property Discovery, and Data Operations."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, sync_playwright

from scripts.ui_fixture_server import DEFAULT_PORT, LOOPBACK_HOST
from scripts.ui_fixtures import (
    AGENT_RUN_ID,
    CANDIDATE_RELEASE_ID,
    DATASET_ID,
    FIXTURE_IDENTITY,
    FIXTURE_REVISION,
    JOB_ID,
    PROPERTY_ID,
    RELEASE_ID,
    RUN_ID,
    SCENARIOS,
    SOURCE_ID,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _ready(base_url: str) -> bool:
    try:
        with urlopen(f"{base_url}/__ui-fixture__/ready", timeout=0.4) as response:  # noqa: S310 - loopback fixture URL
            payload = json.load(response)
            return (
                response.status == 200
                and payload.get("scenario") in SCENARIOS
                and payload.get("identity") == FIXTURE_IDENTITY
                and payload.get("revision") == FIXTURE_REVISION
            )
    except (OSError, URLError, ValueError):
        return False


@contextmanager
def fixture_runtime(port: int, scenario: str) -> Iterator[str]:
    """Reuse a matching local host or own and clean up a new fixture child."""
    base_url = f"http://{LOOPBACK_HOST}:{port}"
    child: subprocess.Popen[bytes] | None = None
    try:
        if not _ready(base_url):
            child = subprocess.Popen(  # noqa: S603 - fixed python argv, no shell
                (
                    sys.executable,
                    "-m",
                    "scripts.ui_fixture_server",
                    "--port",
                    str(port),
                    "--scenario",
                    scenario,
                ),
                cwd=REPOSITORY_ROOT,
            )
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline and not _ready(base_url):
                if child.poll() is not None:
                    raise RuntimeError("UI fixture child exited before its readiness check passed")
                time.sleep(0.1)
            if not _ready(base_url):
                raise RuntimeError(
                    f"UI fixture child did not become ready at {base_url}/__ui-fixture__/ready"
                )
        yield base_url
    finally:
        if child is not None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)


def _verify_page(
    page: Page,
    url: str,
    expected_heading: str,
    *,
    ready_selector: str | None = None,
) -> None:
    failures: list[str] = []
    page.on("pageerror", lambda error: failures.append(f"page exception: {error}"))
    page.on(
        "console",
        lambda message: (
            failures.append(f"console error: {message.text}") if message.type == "error" else None
        ),
    )
    page.goto(url, wait_until="networkidle")
    page.locator("h1", has_text=expected_heading).wait_for(state="visible")
    if ready_selector:
        page.locator(ready_selector).first.wait_for(state="visible")
    if failures:
        raise RuntimeError(f"{url} emitted unexpected browser errors: {'; '.join(failures)}")
    print(f"PASS {expected_heading}: {url}", flush=True)


def _verify_ai_submit(page: Page, base_url: str, scenario: str) -> None:
    failures: list[str] = []
    page.on("pageerror", lambda error: failures.append(f"page exception: {error}"))
    page.on(
        "console",
        lambda message: (
            failures.append(f"console error: {message.text}") if message.type == "error" else None
        ),
    )
    url = (
        f"{base_url}/features/data-platform/?scenario={scenario}#ai/release:{CANDIDATE_RELEASE_ID}"
    )
    page.goto(url, wait_until="networkidle")
    submit = page.get_by_role("button", name="Send message", exact=True)
    submit.wait_for(state="visible")
    with page.expect_response(
        lambda response: (
            response.request.method == "POST" and response.url.endswith("/assistant/turns")
        )
    ) as response_info:
        submit.click()
    if response_info.value.status != 202:
        raise RuntimeError(f"AI review fixture returned HTTP {response_info.value.status}, not 202")
    page.wait_for_url(f"**#ai/{AGENT_RUN_ID}")
    page.locator(f'[data-run-id="{AGENT_RUN_ID}"] .ps-ai-chat__answer-section--summary').wait_for(
        state="visible"
    )
    if failures:
        raise RuntimeError(f"{url} emitted unexpected browser errors: {'; '.join(failures)}")
    print(f"PASS AI submit-to-detail: {url}", flush=True)


def _populated_routes(base_url: str, scenario: str) -> tuple[tuple[str, str, str | None], ...]:
    shared = f"{base_url}/?scenario={scenario}"
    feature = f"{base_url}/features/data-platform/?scenario={scenario}"
    return (
        (f"{shared}#system-status", "Data status", ".health-card"),
        (f"{shared}#evidence", "Sources and history", ".evidence-grid"),
        (f"{feature}#properties/{PROPERTY_ID}", "11 Example Street", None),
        (f"{feature}#sources", "Data sources", None),
        (f"{feature}#sources/{SOURCE_ID}", "Example NSW property records", None),
        (f"{feature}#jobs", "Data updates", None),
        (f"{feature}#jobs/{JOB_ID}", "Example property records update", None),
        (f"{feature}#runs", "Update history", None),
        (f"{feature}#runs/{RUN_ID}", "Example property records update", None),
        (f"{feature}#releases", "Published data", None),
        (
            f"{feature}#releases/{RELEASE_ID}",
            "property-identities",
            None,
        ),
        (f"{feature}#data-products", "Dataset publishing settings", None),
        (f"{feature}#data-products/{DATASET_ID}", "Property identity register", None),
        (f"{feature}#quality", "Data checks", None),
        (f"{feature}#quality/{RUN_ID}", "Data checks", None),
        (f"{feature}#artifacts", "Files and history", None),
        (f"{feature}#artifacts/{RUN_ID}", "Files and history", None),
        (f"{feature}#coverage", "Data coverage", None),
        (f"{feature}#ai", "AI review", None),
        (f"{feature}#ai/{AGENT_RUN_ID}", "AI review", None),
        (
            f"{base_url}/operations/ai-mode/?feature_key="
            f"student-1-propertyscope-data-platform&run={AGENT_RUN_ID}",
            "Activity history",
            "#detail-content:not([hidden])",
        ),
    )


def run_smoke(*, port: int, scenario: str, all_routes: bool = False) -> None:
    """Run three representative routes against one deterministic same-origin host."""
    with fixture_runtime(port, scenario) as base_url:
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    context = browser.new_context(viewport={"width": 1440, "height": 1000})
                    page = context.new_page()
                    fragment_statuses: list[int] = []
                    page.on(
                        "response",
                        lambda response: (
                            fragment_statuses.append(response.status)
                            if response.url.endswith("/fragments/research-areas.html")
                            else None
                        ),
                    )
                    _verify_page(
                        page,
                        f"{base_url}/?scenario={scenario}#home",
                        "Research a property",
                        ready_selector="#feature-area-list [data-feature-id]",
                    )
                    if fragment_statuses != [200]:
                        raise RuntimeError(
                            "Shared research-area HTMX fragment did not return exactly one HTTP 200"
                        )
                    if page.locator("#feature-area-list [data-feature-id]").count() != 5:
                        raise RuntimeError(
                            "Shared research-area HTMX fragment did not render five rows"
                        )
                    if page.locator("#feature-area-list a").count() != 1:
                        raise RuntimeError(
                            "Shared research-area HTMX fragment did not retain one enabled link"
                        )
                    if page.locator(
                        "#feature-area-list [data-feature-state=planned] :is(a, button)"
                    ).count():
                        raise RuntimeError("A planned research area became interactive")
                    page.close()
                    page = context.new_page()
                    _verify_page(
                        page,
                        f"{base_url}/features/data-platform/"
                        f"?scenario={scenario}#properties?q=11%20Example%20Street",
                        "Find a NSW property",
                        ready_selector=".result-card",
                    )
                    page.close()
                    page = context.new_page()
                    _verify_page(
                        page,
                        f"{base_url}/features/data-platform/?scenario={scenario}#overview",
                        "Data overview",
                    )
                    page.close()
                    if all_routes:
                        for url, heading, selector in _populated_routes(base_url, scenario):
                            page = context.new_page()
                            _verify_page(page, url, heading, ready_selector=selector)
                            if heading == "Sources and history":
                                page.get_by_text("2026.08.23-fixture", exact=False).first.wait_for(
                                    state="visible"
                                )
                                if page.get_by_text(
                                    "2026.08.24-fixture-candidate", exact=False
                                ).count():
                                    raise RuntimeError(
                                        "Shared Evidence rendered a candidate despite "
                                        "status=accepted"
                                    )
                            page.close()
                        page = context.new_page()
                        _verify_ai_submit(page, base_url, scenario)
                        page.close()
                    context.close()
                finally:
                    browser.close()
        except PlaywrightError as exc:
            if "Executable doesn't exist" in str(exc):
                raise RuntimeError(
                    "Playwright Chromium is missing. Run `uv run playwright install chromium` "
                    "once, then rerun the smoke command."
                ) from exc
            raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--scenario", choices=SCENARIOS, default="populated")
    parser.add_argument(
        "--all-routes",
        action="store_true",
        help="Also exercise Shared status/evidence/AI activity and every populated route family",
    )
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    try:
        run_smoke(
            port=arguments.port,
            scenario=arguments.scenario,
            all_routes=arguments.all_routes,
        )
    except (PlaywrightError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
