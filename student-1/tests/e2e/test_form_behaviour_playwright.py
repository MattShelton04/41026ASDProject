"""Focused real-browser evidence for Feature 1 forms and Property Discovery.

Run explicitly after installing Chromium:

    uv run pytest student-1/tests/e2e/test_form_behaviour_playwright.py --no-cov -q

The suite owns a random loopback fixture port and never uses Docker or canonical demo ports.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from urllib.request import urlopen

import pytest
from playwright.sync_api import Browser, Page, Route, expect, sync_playwright

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FEATURE_PATH = "/features/data-platform/"
SOURCE_ID = "10000000-0000-0000-0000-000000000001"
JOB_ID = "20000000-0000-0000-0000-000000000001"
RUN_ID = "30000000-0000-0000-0000-000000000001"
CANDIDATE_ID = "60000000-0000-0000-0000-000000000011"
REVIEW_ID = "60000000-0000-0000-0000-000000000012"
PROPERTY_ID = "11111111-1111-4111-8111-111111111111"
ACCEPTED_ID = "60000000-0000-0000-0000-000000000001"
AGENT_RUN_ID = "70000000-0000-4000-8000-000000000001"


def _free_port() -> int:
    with socket.socket() as candidate:
        candidate.bind(("127.0.0.1", 0))
        return int(candidate.getsockname()[1])


@pytest.fixture(scope="module")
def fixture_origin() -> Iterator[str]:
    process: subprocess.Popen[bytes] | None = None
    origin = ""
    for _port_attempt in range(5):
        port = _free_port()
        candidate = subprocess.Popen(
            [sys.executable, "-m", "scripts.ui_fixture_server", "--port", str(port)],
            cwd=REPOSITORY_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )
        candidate_origin = f"http://127.0.0.1:{port}"
        ready = False
        for _attempt in range(100):
            if candidate.poll() is not None:
                break
            try:
                with urlopen(f"{candidate_origin}/__ui-fixture__/ready", timeout=0.2) as response:
                    if response.status == 200:
                        ready = True
                        break
            except OSError:
                time.sleep(0.05)
        if ready:
            process = candidate
            origin = candidate_origin
            break
        if candidate.poll() is None:
            candidate.terminate()
            candidate.wait(timeout=5)
    if process is None:
        raise RuntimeError("UI fixture host did not become ready after five random-port attempts")
    try:
        yield origin
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True)
        yield instance
        instance.close()


@pytest.fixture
def page(browser: Browser) -> Iterator[Page]:
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    tab = context.new_page()
    yield tab
    context.close()


def _open(page: Page, origin: str, route: str) -> None:
    page.goto(f"{origin}{FEATURE_PATH}?scenario=populated&test={time.time_ns()}#{route}")
    page.wait_for_function("expected => location.hash === `#${expected}`", arg=route)
    expect(page.locator("h1").first).to_be_visible()


def _open_row_actions(page: Page, item_name: str) -> None:
    page.get_by_role("button", name=f"More actions for {item_name}").click()


def _fail_first_write(page: Page, pattern: str, *, method: str = "POST") -> list[int]:
    writes: list[int] = []

    def intercept(route: Route) -> None:
        if route.request.method != method:
            route.continue_()
            return
        writes.append(1)
        if len(writes) == 1:
            route.fulfill(
                status=503,
                content_type="application/problem+json",
                headers={"X-Request-ID": "form-retry-request"},
                body=json.dumps(
                    {
                        "type": "about:blank",
                        "title": "Temporary fixture failure",
                        "detail": "The deterministic write failed once; retry the unchanged form.",
                    }
                ),
            )
        else:
            route.continue_()

    page.route(pattern, intercept)
    return writes


def _temporary_read_failure(route: Route, label: str) -> None:
    route.fulfill(
        status=503,
        content_type="application/problem+json",
        headers={"X-Request-ID": f"{label}-refresh-request"},
        body=json.dumps(
            {
                "type": "about:blank",
                "title": "Temporary fixture failure",
                "detail": f"The {label} fixture is temporarily unavailable.",
            }
        ),
    )


def _abort_external_map(page: Page) -> None:
    page.route("**/tiles.openfreemap.org/**", lambda route: route.abort())


def _track_table_observers(page: Page) -> None:
    page.add_init_script("""
        const NativeObserver = window.ResizeObserver;
        window.tableObservers = new Set();
        window.ResizeObserver = class extends NativeObserver {
            observe(target, options) {
                if (target.classList.contains('ps-table-region')) window.tableObservers.add(this);
                return super.observe(target, options);
            }
            disconnect() {
                window.tableObservers.delete(this);
                return super.disconnect();
            }
        };
    """)


def test_corrected_property_search_cancels_pending_request_without_waiting(
    page: Page,
    fixture_origin: str,
) -> None:
    held: list[Route] = []
    failures: list[str] = []
    page.on("requestfailed", lambda request: failures.append(request.url))

    def hold_first(route: Route) -> None:
        if not held:
            held.append(route)
        else:
            route.continue_()

    page.route("**/properties/search?**", hold_first)
    _open(page, fixture_origin, "properties")
    query = page.get_by_label("Address, suburb or postcode")
    query.fill("11 Example Street")
    query.press("Enter")
    expect(page.get_by_text("Searching NSW property records…")).to_be_visible()
    query.fill("22 Replacement Street")
    query.press("Enter")
    expect(page.locator(".result-card").first).to_be_visible()
    expect(page.locator(".property-results-heading")).to_contain_text("22 Replacement Street")
    expect(page.get_by_role("button", name="Search", exact=True)).to_have_attribute(
        "aria-busy", "false"
    )
    assert any("properties/search" in url for url in failures)
    held[0].fulfill(json={"items": [], "total": 0})
    expect(page.locator(".property-results-heading")).to_contain_text("22 Replacement Street")


def test_table_observers_are_released_after_search_and_shared_navigation(
    page: Page,
    fixture_origin: str,
) -> None:
    _track_table_observers(page)
    _open(page, fixture_origin, "properties")
    for query in ("11 Example Street", "22 Replacement Street", "Sydney 2000"):
        page.get_by_label("Address, suburb or postcode").fill(query)
        page.get_by_label("Address, suburb or postcode").press("Enter")
        expect(page.locator(".result-card").first).to_be_visible()
        assert page.evaluate("window.tableObservers.size") == 1
    page.get_by_role("link", name="Data overview", exact=True).click()
    expect(page.get_by_role("heading", name="Data overview")).to_be_visible()
    page.wait_for_function(
        "window.tableObservers.size === document.querySelectorAll('.ps-table-region').length"
    )
    page.goto(f"{fixture_origin}/?scenario=populated#evidence")
    expect(page.get_by_text("Current records loaded.")).to_be_visible()
    assert page.evaluate("window.tableObservers.size") > 0
    page.get_by_role("link", name="Home", exact=True).first.click()
    expect(page.get_by_role("heading", name="A clearer view of your next move.")).to_be_visible()
    assert page.evaluate("window.tableObservers.size") == 0


def test_release_preview_serialises_pages_disposes_tables_and_ignores_detached_results(
    page: Page,
    fixture_origin: str,
) -> None:
    _track_table_observers(page)
    held: list[Route] = []
    requests = 0

    def preview(route: Route) -> None:
        nonlocal requests
        requests += 1
        if requests > 1:
            held.append(route)
            return
        route.fulfill(
            json={
                "items": [{"address": "First preview row"}],
                "columns": ["address"],
                "count": 1,
                "limit": 1,
                "offset": 1,
                "next_offset": 2,
                "total": 3,
                "profile": "fixture",
                "release": {"status": "accepted"},
            }
        )

    page.route(f"**/dataset-releases/{ACCEPTED_ID}/records?**", preview)
    _open(page, fixture_origin, f"releases/{ACCEPTED_ID}")
    expect(page.get_by_text("First preview row")).to_be_visible()
    baseline = page.evaluate("window.tableObservers.size")
    page.get_by_role("button", name="Next page").click()
    expect(page.get_by_role("button", name="Previous page")).to_be_disabled()
    expect(page.get_by_role("button", name="Next page")).to_be_disabled()
    page.wait_for_function("document.querySelector('.panel-body[aria-busy=true]') !== null")
    assert requests == 2
    held.pop().fulfill(
        json={
            "items": [{"address": "Final preview row"}],
            "columns": ["address"],
            "count": 1,
            "limit": 1,
            "offset": 2,
            "next_offset": None,
            "total": 3,
            "profile": "fixture",
            "release": {"status": "accepted"},
        }
    )
    expect(page.get_by_text("Final preview row")).to_be_visible()
    expect(page.get_by_role("button", name="Next page")).to_be_disabled()
    expect(page.get_by_text("Showing 3\u20133 of 3")).to_be_focused()
    assert page.evaluate("window.tableObservers.size") == baseline
    page.get_by_role("button", name="Previous page").click()
    expect(page.get_by_role("button", name="Previous page")).to_be_disabled()
    page.get_by_role("link", name="Property search", exact=True).click()
    expect(page.get_by_role("heading", name="Find a NSW property")).to_be_visible()
    held.pop().fulfill(
        json={
            "items": [{"address": "Obsolete row"}],
            "columns": ["address"],
            "count": 1,
            "limit": 1,
            "offset": 1,
            "next_offset": 2,
            "total": 3,
            "profile": "fixture",
            "release": {"status": "accepted"},
        }
    )
    expect(page.get_by_text("Obsolete row")).to_have_count(0)
    assert page.evaluate("window.tableObservers.size") == 0


def test_open_action_menu_releases_global_listeners_when_route_is_replaced(
    page: Page,
    fixture_origin: str,
) -> None:
    page.add_init_script("""
        const listeners = new Set();
        window.openMenuListeners = listeners;
        const add = document.addEventListener.bind(document);
        const remove = document.removeEventListener.bind(document);
        document.addEventListener = (type, listener, options) => {
            if (type === 'pointerdown') listeners.add(listener);
            return add(type, listener, options);
        };
        document.removeEventListener = (type, listener, options) => {
            if (type === 'pointerdown') listeners.delete(listener);
            return remove(type, listener, options);
        };
    """)
    _open(page, fixture_origin, "jobs")
    baseline = page.evaluate("window.openMenuListeners.size")
    _open_row_actions(page, "Example property records update")
    assert page.evaluate("window.openMenuListeners.size") == baseline + 1
    page.evaluate("location.hash = '#properties'")
    expect(page.get_by_role("heading", name="Find a NSW property")).to_be_visible()
    assert page.evaluate("window.openMenuListeners.size") == baseline


def test_property_search_keeps_focus_and_accepts_two_sequential_queries(
    page: Page, fixture_origin: str
) -> None:
    requests: list[str] = []
    page.on(
        "request",
        lambda request: (
            requests.append(request.url) if "/properties/search" in request.url else None
        ),
    )
    page.goto(f"{fixture_origin}{FEATURE_PATH}?scenario=slow&test={time.time_ns()}#properties")
    query = page.get_by_label("Address, suburb or postcode")
    search = page.get_by_role("button", name="Search")

    query.fill("11 Example Street, Sydney NSW 2000")
    search.click()
    expect(search).to_be_focused()
    expect(search).to_have_text("Searching…")
    expect(search).to_have_attribute("aria-disabled", "true")
    expect(page.get_by_role("link", name="Open 11 Example Street, Sydney NSW 2000")).to_be_visible()
    expect(search).to_be_focused()

    query.fill("22 Replacement Street, Sydney NSW 2000")
    query.press("Enter")
    expect(page.get_by_text("Searching NSW property records…")).to_be_visible()
    expect(page.get_by_role("link", name="Open 11 Example Street, Sydney NSW 2000")).to_be_visible()
    expect(page.get_by_text("Searching NSW property records…")).to_have_count(0)
    page.wait_for_function("() => location.hash.includes('22+Replacement+Street')")
    assert len(requests) == 2
    assert (
        "q=22%20Replacement%20Street" in requests[-1] or "q=22+Replacement+Street" in requests[-1]
    )


def test_property_result_is_a_native_link_and_back_restores_origin(
    page: Page, fixture_origin: str
) -> None:
    _abort_external_map(page)
    page.set_viewport_size({"width": 1024, "height": 600})
    query = "11 Example Street"
    page.goto(
        f"{fixture_origin}{FEATURE_PATH}?scenario=large&test={time.time_ns()}"
        f"#properties?q=11%20Example%20Street"
    )
    result = page.get_by_role("link", name="Open 11 Example Street, Sydney NSW 2000")
    expect(result).to_be_visible()
    assert result.evaluate("element => element.tagName") == "A"
    expect(result).to_have_attribute("href", f"#properties/{PROPERTY_ID}?q=11+Example+Street")
    page.evaluate(
        "window.scrollTo(0, Math.min(120, document.documentElement.scrollHeight - innerHeight))"
    )
    original_scroll = page.evaluate("window.scrollY")
    assert original_scroll > 0
    assert (
        result.evaluate("element => { element.focus({ preventScroll: true }); return scrollY; }")
        == original_scroll
    )
    page.keyboard.press("Enter")
    expect(page.get_by_role("heading", name="11 Example Street, Sydney NSW 2000")).to_be_visible()

    page.get_by_role("link", name="Back to search").click()
    expect(page.get_by_role("heading", name="Find a NSW property")).to_be_visible()
    expect(result).to_be_visible()
    expect(result).to_be_focused()
    assert page.evaluate("new URLSearchParams(location.hash.split('?')[1]).get('q')") == query
    assert abs(page.evaluate("window.scrollY") - original_scroll) <= 1

    page.go_forward()
    detail_heading = page.get_by_role("heading", name="11 Example Street, Sydney NSW 2000")
    expect(detail_heading).to_be_visible()
    expect(detail_heading).to_be_focused()
    assert page.title() == "PropertyScope | 11 Example Street, Sydney NSW 2000"


def test_property_search_can_page_through_every_match(page: Page, fixture_origin: str) -> None:
    page.goto(
        f"{fixture_origin}{FEATURE_PATH}?scenario=large&test={time.time_ns()}"
        "#properties?q=11%20Example%20Street"
    )
    cards = page.locator(".result-card")

    expect(page.get_by_role("heading", name="80 properties found")).to_be_visible()
    expect(cards).to_have_count(25)
    for expected_count in (50, 75, 80):
        page.get_by_role("button", name="Show more matches").click()
        expect(cards).to_have_count(expected_count)
    expect(page.get_by_role("button", name="Show more matches")).to_have_count(0)


def test_property_deep_link_back_uses_its_query_href(page: Page, fixture_origin: str) -> None:
    _abort_external_map(page)
    page.goto(
        f"{fixture_origin}{FEATURE_PATH}?scenario=populated&test={time.time_ns()}"
        f"#properties/{PROPERTY_ID}?q=11%20Example%20Street"
    )
    expect(page.get_by_role("heading", name="11 Example Street, Sydney NSW 2000")).to_be_visible()
    assert page.evaluate("history.state?.propertyDiscoveryOrigin ?? null") is None

    page.get_by_role("link", name="Back to search").click()
    expect(page.get_by_role("heading", name="Find a NSW property")).to_be_visible()
    expect(page.get_by_label("Address, suburb or postcode")).to_have_value("11 Example Street")
    assert page.evaluate("location.hash") == "#properties?q=11+Example+Street"


def test_property_identity_renders_before_optional_calls_settle(
    page: Page, fixture_origin: str
) -> None:
    _abort_external_map(page)
    page.add_init_script(
        r"""(() => {
          const originalFetch = window.fetch.bind(window);
          const pending = [];
          window.fetch = (input, options) => {
            const url = String(input);
            if (
              /\/properties\/[^/]+\/(map-context|coverage|sale-history|seifa|report-section)(\?.*)?$/.test(url)
            ) {
              return new Promise((resolve, reject) => {
                pending.push(() => originalFetch(input, options).then(resolve, reject));
              });
            }
            return originalFetch(input, options);
          };
          window.__pendingPropertyOptionalCount = () => pending.length;
          window.__releasePropertyOptional = () =>
            pending.splice(0).forEach((release) => release());
        })()"""
    )
    page.goto(
        f"{fixture_origin}{FEATURE_PATH}?scenario=populated&test={time.time_ns()}"
        f"#properties/{PROPERTY_ID}?q=11%20Example%20Street"
    )
    expect(page.get_by_role("heading", name="11 Example Street, Sydney NSW 2000")).to_be_visible()
    expect(page.get_by_text("Identity status")).to_be_visible()
    expect(page.get_by_text("Loading spatial context…")).to_be_visible()
    assert page.evaluate("window.__pendingPropertyOptionalCount()") == 5

    page.evaluate("window.__releasePropertyOptional()")
    expect(page.get_by_role("heading", name="Research available")).to_be_visible()
    page.get_by_role("tab", name="Sale history", exact=True).click()
    expect(page.get_by_role("heading", name="Sale history")).to_be_visible()
    expect(page.get_by_text("$760,000", exact=True)).to_be_visible()
    page.get_by_role("tab", name="Area context", exact=True).click()
    expect(page.get_by_role("heading", name="Socio-economic area context")).to_be_visible()
    expect(page.get_by_text("10 of 10", exact=True).first).to_be_visible()
    expect(page.get_by_text("Based on Australian Bureau of Statistics data")).to_be_visible()
    expect(page.locator(".map-context")).to_be_visible()
    page.get_by_role("tab", name="Sources and identifiers", exact=True).click()
    expect(page.get_by_role("heading", name="Source summary")).to_be_visible()


def test_property_sections_keep_loaded_evidence_and_restore_deep_link(
    page: Page, fixture_origin: str
) -> None:
    _abort_external_map(page)
    reads: list[str] = []
    page.on("request", lambda request: reads.append(request.url))
    _open(page, fixture_origin, f"properties/{PROPERTY_ID}?q=Sydney&section=sales")
    expect(page.get_by_role("tab", name="Sale history", exact=True)).to_have_attribute(
        "aria-selected", "true"
    )
    expect(page.get_by_text("$760,000", exact=True)).to_be_visible()
    initial_reads = len([url for url in reads if f"/properties/{PROPERTY_ID}" in url])
    page.get_by_role("tab", name="Sale history", exact=True).press("ArrowRight")
    expect(page.get_by_role("tab", name="Area context", exact=True)).to_be_focused()
    expect(page.get_by_text("10 of 10", exact=True).first).to_be_visible()
    page.get_by_role("tab", name="Area context", exact=True).press("End")
    expect(page.get_by_role("heading", name="Source summary")).to_be_visible()
    assert len([url for url in reads if f"/properties/{PROPERTY_ID}" in url]) == initial_reads
    assert "q=Sydney" in page.url and "section=sources" in page.url
    page.reload()
    expect(page.get_by_role("tab", name="Sources and identifiers", exact=True)).to_have_attribute(
        "aria-selected", "true"
    )
    expect(page.get_by_role("heading", name="Source summary")).to_be_visible()


def test_evidence_pages_retain_the_selected_update(page: Page, fixture_origin: str) -> None:
    _open(page, fixture_origin, f"quality/{RUN_ID}")
    navigation = page.get_by_role("navigation", name="Evidence pages")
    expect(navigation.get_by_role("link", name="Files & history")).to_have_attribute(
        "href", f"#artifacts/{RUN_ID}"
    )
    navigation.get_by_role("link", name="Files & history").click()
    expect(page.get_by_role("heading", name="Files and history", exact=True)).to_be_visible()
    expect(page.get_by_role("link", name="← Back to this update")).to_have_attribute(
        "href", f"#runs/{RUN_ID}"
    )
    page.get_by_role("navigation", name="Evidence pages").get_by_role(
        "link", name="Published coverage"
    ).click()
    expect(page.get_by_role("heading", name="Data coverage", exact=True)).to_be_visible()


@pytest.mark.parametrize("width", [1440, 1024, 768, 390])
@pytest.mark.parametrize("long_records", [False, True], ids=["populated", "long-records"])
def test_property_sources_stay_readable_when_expanded(
    page: Page, fixture_origin: str, width: int, long_records: bool
) -> None:
    _abort_external_map(page)
    page.set_viewport_size({"width": width, "height": 1000})
    long_identifier = "GNAF-" + "0123456789" * 24
    long_alias = "Former address <script>plain text</script> " * 8

    if long_records:

        def extend_records(route: Route) -> None:
            response = route.fetch()
            payload = response.json()
            if route.request.url.endswith(f"/properties/{PROPERTY_ID}"):
                original = payload["identifiers"][0]
                payload["identifiers"].append(
                    {
                        **original,
                        "identifier_value": long_identifier,
                        "evidence_json": {"source_reference": long_identifier},
                    }
                )
                payload["aliases"] = [
                    {
                        "alias_display": long_alias,
                        "alias_kind": "historical",
                        "source_identifier": long_identifier,
                        "is_current": False,
                    }
                ]
            elif route.request.url.endswith("/report-section"):
                payload["release_evidence"][0]["release_version"] = long_identifier
            route.fulfill(response=response, json=payload)

        page.route(f"**/properties/{PROPERTY_ID}", extend_records)
        page.route(f"**/properties/{PROPERTY_ID}/report-section", extend_records)

    _open(page, fixture_origin, f"properties/{PROPERTY_ID}")
    disclosure = page.locator("#property-section-sources")
    toggle = page.get_by_role("tab", name="Sources and identifiers", exact=True)
    toggle.focus()
    toggle.press("Enter")
    expect(toggle).to_have_attribute("aria-selected", "true")
    expect(disclosure).to_be_visible()
    expect(disclosure.get_by_role("heading", name="Source summary")).to_be_visible()
    expect(disclosure.get_by_text("GNAF-FIXTURE-0001", exact=True)).to_have_count(2)
    expect(disclosure.get_by_text("-33.8688", exact=True)).to_be_visible()
    if long_records:
        expect(disclosure.get_by_text(long_alias.strip(), exact=True)).to_be_visible()
        expect(disclosure.get_by_text(long_identifier, exact=True)).to_have_count(3)
        expect(disclosure.locator("script")).to_have_count(0)
    else:
        expect(
            disclosure.get_by_text("No address aliases are recorded for this property.")
        ).to_be_visible()

    for summary in disclosure.locator("details.technical > summary").all():
        summary.click()
    expect(disclosure.locator("details.technical:not([open])")).to_have_count(0)
    # Check local containment: body overflow clipping can conceal this regression from
    # a document-width-only assertion while records paint under the adjacent panel.
    overflow = disclosure.evaluate(
        """root => {
          const bounds = root.getBoundingClientRect();
          return [...root.querySelectorAll('*')].filter(element => {
            const rect = element.getBoundingClientRect();
            return rect.width && rect.height && (
              rect.left < bounds.left - 1 || rect.right > bounds.right + 1 ||
              element.scrollWidth > element.clientWidth + 1
            );
          }).map(element => element.tagName + '.' + element.className);
        }"""
    )
    assert overflow == []
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert disclosure.locator("h3").evaluate_all(
        "elements => elements.every(element => "
        "parseFloat(getComputedStyle(element).fontSize) <= 16)"
    )
    toggle.focus()
    toggle.press("Home")
    expect(disclosure).to_be_hidden()
    research = page.get_by_role("tab", name="Research available", exact=True)
    expect(research).to_be_focused()
    expect(research).to_have_attribute("aria-selected", "true")


def test_property_partial_and_fatal_states_keep_local_recovery(
    page: Page, fixture_origin: str
) -> None:
    _abort_external_map(page)
    detail = f"properties/{PROPERTY_ID}?q=11%20Example%20Street"
    page.goto(f"{fixture_origin}{FEATURE_PATH}?scenario=partial&test={time.time_ns()}#{detail}")
    expect(page.get_by_role("heading", name="11 Example Street, Sydney NSW 2000")).to_be_visible()
    expect(
        page.get_by_text("Spatial context is temporarily unavailable", exact=False)
    ).to_be_visible()
    expect(
        page.get_by_text("Coverage details are temporarily unavailable", exact=False)
    ).to_be_visible()
    page.get_by_role("tab", name="Sources and identifiers", exact=True).click()
    expect(
        page.get_by_text("The source summary is temporarily unavailable", exact=False)
    ).to_be_visible()

    detail_calls = 0

    def fail_first_detail(route: Route) -> None:
        nonlocal detail_calls
        if not route.request.url.endswith(f"/properties/{PROPERTY_ID}"):
            route.continue_()
            return
        detail_calls += 1
        if detail_calls == 1:
            route.fulfill(
                status=503,
                content_type="application/problem+json",
                headers={"X-Request-ID": "property-detail-retry"},
                body=json.dumps(
                    {
                        "type": "about:blank",
                        "title": "Property detail unavailable",
                        "detail": "The canonical property detail failed once.",
                    }
                ),
            )
        else:
            route.continue_()

    page.route("**/api/data-platform/v1/properties/**", fail_first_detail)
    page.goto(f"{fixture_origin}{FEATURE_PATH}?scenario=populated&test={time.time_ns()}#{detail}")
    expect(page.get_by_role("heading", name="Service temporarily unavailable")).to_be_visible()
    expect(page.get_by_role("link", name="Back to search")).to_have_attribute(
        "href", "#properties?q=11+Example+Street"
    )
    page.get_by_role("button", name="Try again").click()
    detail_heading = page.get_by_role("heading", name="11 Example Street, Sydney NSW 2000")
    expect(detail_heading).to_be_visible()
    expect(detail_heading).to_be_focused()
    assert page.title() == "PropertyScope | 11 Example Street, Sydney NSW 2000"
    assert detail_calls == 2


def test_search_and_every_filter_use_native_keyboard_and_explicit_reset(
    page: Page, fixture_origin: str
) -> None:
    console_errors: list[str] = []
    page.on(
        "console",
        lambda message: console_errors.append(message.text) if message.type == "error" else None,
    )
    _open(page, fixture_origin, "properties")
    query = page.get_by_label("Address, suburb or postcode")
    query.fill("x")
    query.press("Enter")
    expect(page.locator("#property-search-error")).to_contain_text("2 to 200 characters")
    expect(query).to_be_focused()
    query.fill("y")
    expect(page.locator("#property-search-error")).to_contain_text("2 to 200 characters")
    expect(query).to_have_attribute("aria-invalid", "true")
    assert "2 to 200 characters" in query.evaluate("element => element.validationMessage")

    query.fill("11 Example Street, Sydney NSW 2000")
    expect(page.locator("#property-search-error")).to_be_empty()
    expect(query).not_to_have_attribute("aria-invalid", "true")
    assert query.evaluate("element => element.validationMessage") == ""
    query.press("Enter")
    expect(page.get_by_role("heading", name="1 property found")).to_be_visible()
    page.wait_for_function("() => location.hash.includes('q=11+Example+Street')")

    _open(page, fixture_origin, "sources")
    header_query = page.get_by_label("Search Property data")
    header_query.fill("x")
    header_query.press("Enter")
    expect(header_query).to_have_attribute("aria-invalid", "true")
    assert "2 to 200 characters" in header_query.evaluate("element => element.validationMessage")
    assert page.evaluate("location.hash") == "#sources"
    header_query.fill("y")
    expect(header_query).to_have_attribute("aria-invalid", "true")
    assert "2 to 200 characters" in header_query.evaluate("element => element.validationMessage")
    header_query.fill("1 Farrer Place Sydney")
    expect(header_query).not_to_have_attribute("aria-invalid", "true")
    assert header_query.evaluate("element => element.validationMessage") == ""
    header_query.press("Enter")
    page.wait_for_function(
        "() => location.hash.startsWith('#properties?q=1+Farrer') "
        "|| location.hash.startsWith('#properties?q=1%20Farrer')"
    )

    page.goto(f"{fixture_origin}{FEATURE_PATH}?scenario=slow&test={time.time_ns()}#properties")
    expect(page.get_by_role("heading", name="Find a NSW property")).to_be_visible()
    query = page.get_by_label("Address, suburb or postcode")
    query.fill("11 Example Street, Sydney NSW 2000")
    query.press("Enter")
    expect(page.get_by_text("Searching NSW property records…")).to_be_visible()
    query.fill("22 Replacement Street, Sydney NSW 2000")
    expect(page.get_by_role("heading", name="Search changed")).to_be_visible()
    page.wait_for_timeout(1500)
    expect(page.get_by_role("heading", name="Search changed")).to_be_visible()
    expect(page.get_by_role("button", name="Search")).to_be_enabled()

    for route in ("sources", "jobs", "runs", "releases"):
        _open(page, fixture_origin, route)
        search = page.get_by_label("Search (optional)")
        search.fill("fixture")
        search.press("Enter")
        expect(page.get_by_text("active filter", exact=False).first).to_be_visible()
        expect(page.get_by_role("button", name="Reset filters")).to_be_visible()
        page.get_by_role("button", name="Reset filters").click()
        expect(page.locator(".active-filters")).to_have_count(0)
    assert not [message for message in console_errors if "hx-disabled-elt" in message]


def test_source_filter_reset_aborts_an_in_flight_search(page: Page, fixture_origin: str) -> None:
    _open(page, fixture_origin, "sources")
    search = page.get_by_label("Search (optional)")
    expect(search).to_be_visible()
    held: list[Route] = []

    def hold_filtered_sources(route: Route) -> None:
        if "q=fixture" in route.request.url:
            held.append(route)
        else:
            route.continue_()

    page.route("**/fragments/data-platform/v1/sources?*", hold_filtered_sources)
    search.fill("fixture")
    search.press("Enter")
    expect(page.get_by_role("button", name="Apply filters")).to_be_disabled()
    assert held, "the filtered source request must still be in flight"

    with page.expect_event(
        "requestfailed", predicate=lambda request: request.url == held[0].request.url, timeout=3000
    ):
        page.get_by_role("button", name="Reset filters").click()

    expect(page.locator(".active-filters")).to_have_count(0)
    expect(search).to_have_value("")
    expect(page.get_by_label("Status (optional)")).to_have_value("all")
    expect(page).to_have_url(f"{page.url.split('#')[0]}#sources?status=all")


def test_source_job_and_release_create_edit_forms_retain_server_failures(
    page: Page, fixture_origin: str
) -> None:
    _open(page, fixture_origin, "sources")
    page.get_by_role("button", name="Create source").click()
    expect(page.locator('[name="name"]')).to_be_focused()
    page.locator("#entity-save").click()
    expect(page.locator("#entity-error")).to_contain_text("Please correct the highlighted fields")
    expect(page.locator('[name="name"]')).to_be_focused()
    source_name = f"Isolated HTMX source {time.time_ns()}"
    for name, value in {
        "name": source_name,
        "publisher": "HTMX fixture publisher",
        "source_url": "https://example.invalid/htmx-source",
        "adapter_key": "fixture-htmx",
        "cadence": "on-demand",
        "licence_id": "synthetic-test-data",
        "licence_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "redistribution_policy": "committed-synthetic-fixture",
        "notes": "Created through the HTML fragment adapter",
    }.items():
        page.locator(f'[name="{name}"]').fill(value)
    page.locator("#entity-save").click()
    expect(page.locator("#entity-dialog")).not_to_be_visible()
    expect(page.get_by_text(source_name, exact=True)).to_be_visible()

    page.get_by_role("button", name=f"Edit {source_name}").click()
    expect(page.locator('[name="version"]')).to_have_value("1")
    source_notes = page.locator('[name="notes"]')
    source_notes.fill("Updated through HTMX with retained server values")
    page.locator("#entity-save").click()
    expect(page.locator("#entity-dialog")).not_to_be_visible()
    expect(page.get_by_text(source_name, exact=True)).to_be_visible()

    page.get_by_role("button", name=f"Edit {source_name}").click()
    expect(page.locator('[name="version"]')).to_have_value("2")
    update_path = page.locator("#entity-save").get_attribute("hx-put")
    assert update_path is not None
    concurrent_values = page.locator("#entity-form").evaluate(
        "form => Object.fromEntries(new FormData(form).entries())"
    )
    concurrent_values["notes"] = "A concurrent fixture writer"
    concurrent = page.request.put(
        f"{fixture_origin}{update_path}",
        form=concurrent_values,
        headers={"HX-Request": "true", "X-Request-ID": "concurrent-source-update"},
    )
    assert concurrent.status == 200
    conflict_notes = page.locator('[name="notes"]')
    conflict_notes.fill("A stale browser edit that must be retained")
    page.locator("#entity-save").click()
    expect(page.locator("#entity-dialog")).to_be_visible()
    expect(page.locator("#entity-error")).to_contain_text("changed after this form was opened")
    expect(conflict_notes).to_have_value("A stale browser edit that must be retained")
    expect(page.locator("#entity-error")).to_be_focused()
    page.get_by_role("button", name="Cancel", exact=True).click()
    page.locator("#discard-confirm").click()
    expect(page.locator("#entity-dialog")).not_to_be_visible()

    page.get_by_role("button", name=f"Delete {source_name}").click()
    expect(page.locator("#action-dialog")).to_be_visible()
    page.locator('#action-form button[value="cancel"]:not(.close-button)').click()
    expect(page.locator("#action-dialog")).not_to_be_visible()
    page.get_by_role("button", name=f"Delete {source_name}").click()
    page.locator("#action-confirm").click()
    expect(page.locator("#action-dialog")).not_to_be_visible()
    expect(page.get_by_text(source_name, exact=True)).to_have_count(0)

    _open(page, fixture_origin, "jobs")
    page.get_by_role("button", name="Create update").click()
    page.locator("#entity-save").click()
    expect(page.locator("#entity-error")).to_contain_text("Please correct Source ID")
    page.get_by_role("button", name="Cancel").click()
    _open_row_actions(page, "Example property records update")
    page.get_by_role("button", name="Edit Example property records update").click()
    schedule = page.locator('[name="schedule_text"]')
    expect(schedule).to_have_attribute("maxlength", "200")
    expect(page.locator('[name="max_parallelism"]')).to_have_count(0)
    expect(page.locator('[name="timeout_seconds"]')).to_have_count(0)
    expect(page.locator('[name="max_objects"]')).to_have_count(0)
    expect(page.locator('[name="max_bytes"]')).to_have_count(0)
    expect(page.locator('[name="max_rows"]')).to_have_count(0)
    expect(page.locator('[name="scope_json"]')).to_have_count(0)
    schedule.fill("Retained job schedule note")
    job_writes = _fail_first_write(page, "**/api/data-platform/v1/jobs/*", method="PUT")
    page.locator("#entity-save").click()
    expect(page.locator("#entity-error")).to_contain_text("values are still here")
    expect(schedule).to_have_value("Retained job schedule note")
    page.locator("#entity-save").click()
    expect(page.locator("#entity-dialog")).not_to_be_visible()
    assert len(job_writes) == 2

    _open(page, fixture_origin, "releases")
    page.get_by_role("button", name="Create draft version").click()
    page.locator("#entity-save").click()
    expect(page.locator("#entity-error")).to_contain_text("Please correct Dataset ID")
    page.get_by_role("button", name="Cancel").click()
    _open(page, fixture_origin, f"releases/{CANDIDATE_ID}")
    page.get_by_role("button", name="Edit metadata").click()
    release_note = page.locator('[name="review_comment"]')
    expect(page.locator('[name="release_version"]')).to_have_attribute("maxlength", "100")
    release_note.fill("Retained release evidence")
    release_writes = _fail_first_write(
        page, f"**/api/data-platform/v1/dataset-releases/{CANDIDATE_ID}", method="PUT"
    )
    page.locator("#entity-save").click()
    expect(page.locator("#entity-error")).to_contain_text("values are still here")
    expect(release_note).to_have_value("Retained release evidence")
    page.locator("#entity-save").click()
    expect(page.locator("#entity-dialog")).not_to_be_visible()
    assert len(release_writes) == 2


def test_planner_release_decisions_and_ai_retry_in_the_open_form(
    page: Page, fixture_origin: str
) -> None:
    _open(page, fixture_origin, "jobs")
    page.get_by_role("button", name="Start update Example property records update").click()
    expect(page.get_by_text("Complete source history is the default", exact=False)).to_be_visible()
    run_writes = _fail_first_write(page, f"**/api/data-platform/v1/jobs/{JOB_ID}/runs")
    page.locator("#action-confirm").click()
    expect(page.locator("#action-error")).to_contain_text("values are still here")
    expect(page.get_by_text("Complete source history is the default", exact=False)).to_be_visible()
    page.locator("#action-confirm").click()
    page.wait_for_function("() => location.hash.startsWith('#runs/')")
    assert len(run_writes) == 2

    _open(page, fixture_origin, f"releases/{CANDIDATE_ID}")
    page.get_by_role("button", name="Submit for review").click()
    review_note = page.get_by_label("Reviewer context (required)")
    review_writes = _fail_first_write(
        page,
        f"**/api/data-platform/v1/dataset-releases/{CANDIDATE_ID}/submit-review",
    )
    review_note.fill("   ")
    page.locator("#action-confirm").click()
    expect(page.locator("#action-error")).to_contain_text("Please correct Reviewer context")
    expect(page.locator("#review-comment-error")).to_contain_text("not only spaces")
    assert len(review_writes) == 0
    review_note.fill("Retained reviewer context")
    expect(page.locator("#review-comment-error")).to_have_count(0)
    expect(review_note).not_to_have_attribute("aria-invalid", "true")
    expect(review_note).not_to_have_attribute("aria-describedby", "review-comment-error")
    expect(page.locator("#action-error")).to_be_empty()
    page.locator("#action-confirm").press("Enter")
    expect(page.locator("#action-error")).to_contain_text("values are still here")
    expect(review_note).to_have_value("Retained reviewer context")
    page.locator("#action-confirm").click()
    expect(page.locator("#action-dialog")).not_to_be_visible()
    assert len(review_writes) == 2

    _open(page, fixture_origin, f"releases/{REVIEW_ID}")
    page.get_by_role("button", name="Publish").click()
    page.get_by_label("Approval note (required)").fill("Browser approval evidence")
    page.locator("#action-confirm").click()
    expect(page.locator("#action-dialog")).not_to_be_visible()
    page.get_by_role("button", name="Reject").click()
    page.get_by_label("Reason for rejection (required)").fill("Browser rejection evidence")
    page.locator("#action-confirm").click()
    expect(page.locator("#action-dialog")).not_to_be_visible()

    _open(page, fixture_origin, "ai")
    selected_release = page.locator("#diagnosis-release").input_value()
    selected_objective = page.locator("#diagnosis-objective").input_value()
    ai_writes = _fail_first_write(page, "**/api/data-platform/v1/dataset-releases/*/agent-runs")
    page.get_by_role("button", name="Start AI review").click()
    expect(page.get_by_text("selected dataset and review goal are unchanged")).to_be_visible()
    expect(page.locator("#diagnosis-release")).to_have_value(selected_release)
    expect(page.locator("#diagnosis-objective")).to_have_value(selected_objective)
    page.get_by_role("button", name="Start AI review").click()
    page.wait_for_function("() => location.hash.startsWith('#ai/')")
    assert len(ai_writes) == 2


def test_guarded_confirmations_dirty_navigation_and_controller_generation(
    page: Page, fixture_origin: str
) -> None:
    _open(page, fixture_origin, "sources")
    page.get_by_role("button", name="Edit Example NSW property records").click()
    notes = page.locator('[name="notes"]')
    initial_notes = notes.input_value()
    notes.fill("Unsaved navigation evidence")
    page.evaluate("location.hash = '#jobs'")
    expect(page.locator("#discard-dialog")).to_be_visible()
    expect(page.locator("#entity-dialog")).to_be_visible()
    page.wait_for_function("() => location.hash === '#sources'")
    page.locator("#discard-cancel").click()
    expect(page.locator("#discard-dialog")).not_to_be_visible()
    page.wait_for_timeout(10)
    expect(notes).to_have_value("Unsaved navigation evidence")
    notes.fill(initial_notes)
    page.locator('#entity-form button[value="cancel"]:not(.close-button)').click()
    expect(page.locator("#entity-dialog")).not_to_be_visible()
    page.wait_for_function("() => location.hash === '#sources'")

    page.get_by_role("button", name="Edit Example NSW property records").click()
    page.locator('[name="notes"]').fill("Saved after keeping the form open")
    page.evaluate("location.hash = '#jobs'")
    expect(page.locator("#discard-dialog")).to_be_visible()
    page.wait_for_function("() => location.hash === '#sources'")
    page.locator("#discard-cancel").click()
    expect(page.locator("#discard-dialog")).not_to_be_visible()
    page.wait_for_timeout(10)
    page.locator("#entity-save").click()
    expect(page.locator("#entity-dialog")).not_to_be_visible()
    page.wait_for_function("() => location.hash === '#sources?status=all'")

    page.get_by_role("button", name="Edit Example NSW property records").click()
    page.locator('[name="notes"]').fill("Discarded for latest navigation")
    page.evaluate("location.hash = '#jobs'")
    expect(page.locator("#discard-dialog")).to_be_visible()
    page.wait_for_function("() => location.hash === '#sources'")
    page.locator("#discard-confirm").click()
    expect(page.locator("#entity-dialog")).not_to_be_visible()
    page.wait_for_function("() => location.hash === '#jobs'")

    _open(page, fixture_origin, "sources")
    page.get_by_role("button", name="Delete Example NSW property records").click()
    page.locator("#action-confirm").click()
    expect(page.locator("#action-error")).to_contain_text("Only unused draft")
    expect(page.locator("#action-dialog")).to_be_visible()
    page.locator('#action-form button[value="cancel"]:not(.close-button)').click()
    expect(page.locator("#action-dialog")).not_to_be_visible()

    page.goto(f"{fixture_origin}/healthz")
    generation_result = page.evaluate(
        """async () => {
          document.body.innerHTML = `<dialog id="test-dialog"><form method="dialog">
            <label><span>Value (required)</span><input name="value" required value="kept"></label>
            <p class="form-error" tabindex="-1"></p>
            <button type="submit" value="cancel">Cancel</button>
            <button id="save" type="submit" value="save">Save</button>
          </form></dialog>`;
          const module = await import('/features/data-platform/components/dialogs.js');
          const dialog = document.querySelector('#test-dialog');
          const form = dialog.querySelector('form');
          const save = document.querySelector('#save');
          let releaseOld;
          const oldOperation = new Promise((resolve) => { releaseOld = resolve; });
          const oldResult = module.runDialogForm({
            dialog, form, submitButton: save, errorHost: form.querySelector('.form-error'),
            acceptedValue: 'save', onSubmit: () => oldOperation,
          });
          form.requestSubmit(save);
          await new Promise((resolve) => setTimeout(resolve, 0));
          const navigationBlocked = module.requestActiveDialogClose(dialog) === false;
          dialog.close('cancel');
          await oldResult;
          const newResult = module.runDialogForm({
            dialog, form, submitButton: save, errorHost: form.querySelector('.form-error'),
            acceptedValue: 'save', onSubmit: async () => {},
          });
          releaseOld();
          await new Promise((resolve) => setTimeout(resolve, 0));
          const replacementStayedOpen = dialog.open;
          dialog.close('cancel');
          await newResult;
          return { navigationBlocked, replacementStayedOpen };
        }"""
    )
    assert generation_result == {"navigationBlocked": True, "replacementStayedOpen": True}


def test_planner_exposes_psi_archive_year_scope_and_keeps_other_jobs_full_only(
    page: Page, fixture_origin: str
) -> None:
    observed_plans: list[dict[str, object]] = []

    def capture_scoped_plan(route: Route) -> None:
        request_body = route.request.post_data_json
        assert isinstance(request_body, dict)
        observed_plans.append(request_body)
        response = route.fetch()
        payload = response.json()
        payload["scope"] = {
            "profile": "psi-year-range",
            "start_year": request_body["scope"]["start_year"],
            "end_year": request_body["scope"]["end_year"],
            "years": [2023, 2024],
            "all_records": True,
            "all_history": False,
            "include_current_weekly": False,
            "complete": False,
            "coverage_status": "partial",
        }
        route.fulfill(response=response, json=payload)

    page.route("**/api/data-platform/v1/jobs/*/plans", capture_scoped_plan)
    _open(page, fixture_origin, "jobs")
    page.get_by_role("button", name="Start update NSW PSI sales history update").click()
    expect(page.locator("#scope-profile")).to_be_visible()
    expect(page.locator("#scope-profile")).to_have_value("full-data")
    expect(page.locator("#psi-start-year")).to_be_hidden()
    page.locator("#scope-profile").select_option("psi-year-range")
    expect(page.locator("#psi-start-year")).to_be_visible()
    expect(page.get_by_text("not an exact contract-date range", exact=False)).to_be_visible()
    page.locator("#psi-start-year").fill("2023")
    page.locator("#psi-end-year").fill("2024")
    page.get_by_role("button", name="Preview update").click()
    scoped_summary = page.get_by_text("Partial PSI candidate", exact=False)
    expect(scoped_summary).to_contain_text("2023")
    expect(scoped_summary).to_contain_text("2024")

    assert observed_plans[-1]["scope"] == {
        "profile": "psi-year-range",
        "start_year": 2023,
        "end_year": 2024,
    }

    page.get_by_role("button", name="Go back").click()
    expect(page.locator("#discard-dialog")).to_be_visible()
    page.get_by_role("button", name="Discard changes").click()
    expect(page.locator("#action-dialog")).not_to_be_visible()
    page.get_by_role("button", name="Start update Example property records update").click()
    expect(page.locator("#scope-profile")).to_have_count(0)
    expect(page.locator("#maximum-records")).to_have_count(0)


def test_complete_official_profile_is_default_without_visible_row_cap(
    page: Page, fixture_origin: str
) -> None:
    observed_plans: list[dict[str, object]] = []

    def rewrite_job(route: Route) -> None:
        response = route.fetch()
        payload = response.json()
        job = payload["items"][0]
        job["profile_key"] = "gnaf-nsw-address-registry"
        job["import_profile_key"] = "gnaf-nsw"
        job["scope_json"] = {
            "profile": "showcase",
            "localities": ["PARRAMATTA"],
            "maximum_records": 5000,
        }
        job["max_rows"] = 6_500_000
        route.fulfill(response=response, json=payload)

    def capture_plan(route: Route) -> None:
        plan = route.request.post_data_json
        assert isinstance(plan, dict)
        observed_plans.append(plan)
        route.continue_()

    page.route("**/api/data-platform/v1/jobs?*", rewrite_job)
    page.route("**/api/data-platform/v1/jobs/*/plans", capture_plan)
    _open(page, fixture_origin, "jobs")
    page.get_by_role("button", name="Start update Example property records update").click()

    expect(page.locator("#scope-profile")).to_have_count(0)
    expect(page.locator("#maximum-records")).to_have_count(0)
    expect(page.get_by_text("Complete source history is the default", exact=False)).to_be_visible()
    page.get_by_role("button", name="Preview update").click()
    expect(
        page.get_by_text("Complete dataset: all available source records", exact=False)
    ).to_be_visible()

    assert observed_plans
    scope = observed_plans[-1]["scope"]
    assert isinstance(scope, dict)
    assert scope["all_records"] is True
    assert "maximum_records" not in scope
    assert "localities" not in scope


def test_operations_overview_job_and_release_states_are_truthful(
    page: Page, fixture_origin: str
) -> None:
    page.goto(f"{fixture_origin}{FEATURE_PATH}?scenario=partial&test={time.time_ns()}#overview")
    expect(page.get_by_role("heading", name="Data overview")).to_be_visible()
    expect(
        page.locator(".stat-card").filter(has_text="Updating now").locator(".stat-value")
    ).to_have_text("Unavailable")
    expect(
        page.locator(".stat-card").filter(has_text="Update problems").locator(".stat-value")
    ).to_have_text("Unavailable")
    expect(
        page.locator(".stat-card")
        .filter(has=page.get_by_text("Published sources", exact=True))
        .locator(".stat-value")
    ).to_have_text("1")
    expect(
        page.get_by_text(
            "Update history is temporarily unavailable. "
            "Published data and source information remain unchanged.",
            exact=True,
        )
    ).to_be_visible()
    expect(page.get_by_text("Example NSW property records", exact=True)).to_be_visible()

    page.goto(f"{fixture_origin}{FEATURE_PATH}?scenario=error&test={time.time_ns()}#overview")
    error_heading = page.get_by_role("heading", name="Service temporarily unavailable")
    expect(error_heading).to_be_visible()
    expect(page).to_have_title("PropertyScope | Service temporarily unavailable")
    expect(page.get_by_role("button", name="Try again")).to_be_visible()
    expect(page.locator(".stat-card")).to_have_count(0)

    # Move through a route that does not render the same service-error heading.
    # Using another failing Operations route here makes the locator ambiguous
    # between the outgoing and incoming views during the hash transition.
    page.evaluate("location.hash = '#properties'")
    expect(error_heading).to_have_count(0)
    expect(page.get_by_role("heading", name="Find a NSW property")).to_be_focused()
    page.evaluate("location.hash = '#overview'")
    expect(error_heading).to_be_visible()
    expect(error_heading).to_be_focused()
    expect(page).to_have_title("PropertyScope | Service temporarily unavailable")

    page.get_by_role("button", name="Try again").click()
    expect(error_heading).to_be_focused()
    expect(page).to_have_title("PropertyScope | Service temporarily unavailable")

    overview_paths = {
        "sources?limit=100",
        "ingestion-runs?limit=25",
        "dataset-releases?limit=100",
    }
    failed_once: set[str] = set()

    def fail_overview_feed_once(route: Route) -> None:
        relative_url = route.request.url.split("/api/data-platform/v1/", maxsplit=1)[-1]
        if relative_url in overview_paths and relative_url not in failed_once:
            failed_once.add(relative_url)
            route.fulfill(
                status=503,
                content_type="application/problem+json",
                body=json.dumps(
                    {
                        "type": "about:blank",
                        "title": "Temporary overview failure",
                        "detail": "This overview feed failed once.",
                    }
                ),
            )
            return
        route.continue_()

    overview_pattern = "**/api/data-platform/v1/**"
    page.route(overview_pattern, fail_overview_feed_once)
    page.goto(f"{fixture_origin}{FEATURE_PATH}?scenario=populated&test={time.time_ns()}#overview")
    expect(error_heading).to_be_visible()
    expect(page).to_have_title("PropertyScope | Service temporarily unavailable")
    page.get_by_role("button", name="Try again").click()
    overview_heading = page.get_by_role("heading", name="Data overview")
    expect(overview_heading).to_be_visible()
    expect(overview_heading).to_be_focused()
    expect(page).to_have_title("PropertyScope | Data overview")
    assert failed_once == overview_paths
    page.unroute(overview_pattern, fail_overview_feed_once)

    capability_pattern = f"**/api/data-platform/v1/jobs/{JOB_ID}/capabilities"

    def fail_capabilities(route: Route) -> None:
        route.fulfill(
            status=503,
            content_type="application/problem+json",
            headers={"X-Request-ID": "capability-state-test"},
            body=json.dumps(
                {
                    "type": "about:blank",
                    "title": "Capabilities unavailable",
                    "detail": "Processing options are temporarily unavailable.",
                }
            ),
        )

    page.route(capability_pattern, fail_capabilities)
    _open(page, fixture_origin, f"jobs/{JOB_ID}")
    expect(page.get_by_text("Available processing options could not be checked")).to_be_visible()
    expect(page.get_by_text("capability-state-test", exact=False)).to_be_visible()
    page.unroute(capability_pattern, fail_capabilities)

    job_pattern = f"**/api/data-platform/v1/jobs/{JOB_ID}"

    def disable_job(route: Route) -> None:
        response = route.fetch()
        payload = response.json()
        payload["job"]["status"] = "disabled"
        route.fulfill(response=response, json=payload)

    page.route(job_pattern, disable_job)
    _open(page, fixture_origin, f"jobs/{JOB_ID}")
    expect(page.get_by_text("This data update is disabled")).to_be_visible()
    expect(page.get_by_role("button", name="Start update")).to_be_disabled()
    expect(page.get_by_role("button", name="Load earlier data")).to_be_disabled()
    page.unroute(job_pattern, disable_job)

    page.set_viewport_size({"width": 1024, "height": 768})
    _open(page, fixture_origin, "releases")
    expect(page.locator("table .sub-cell").first).to_contain_text("2026.")
    _open(page, fixture_origin, f"releases/{CANDIDATE_ID}")
    lifecycle = page.locator(".notice").filter(has_text="ready for review").first
    expect(lifecycle).to_be_visible()
    expect(lifecycle.locator(".badge")).to_contain_text("Ready for review")
    _open(page, fixture_origin, f"releases/{ACCEPTED_ID}")
    published = page.locator(".notice.positive").filter(has_text="published version").first
    expect(published).to_be_visible()
    expect(published.locator(".badge")).to_contain_text("Published")

    page.set_viewport_size({"width": 390, "height": 844})
    _open(page, fixture_origin, "overview")
    for label in ("View data updates", "Manage sources"):
        box = page.get_by_role("link", name=label).bounding_box()
        assert box is not None
        assert box["height"] >= 44


def test_published_release_can_retry_downstream_without_republishing(
    page: Page, fixture_origin: str
) -> None:
    retried = False

    def detail(route: Route) -> None:
        response = route.fetch()
        payload = response.json()
        payload["release"]["status"] = "accepted"
        payload["publication_policy"] = "producer-owned"
        payload["activations"] = []
        payload["consumer_imports"] = [
            {
                "status": "queued" if retried else "failed",
                "phase_key": "connect" if retried else "complete",
                "error_json": None
                if retried
                else {"message": "Consumer declined publication: record_count exceeds 5000"},
            }
        ]
        route.fulfill(response=response, json=payload)

    def retry(route: Route) -> None:
        nonlocal retried
        assert route.request.method == "POST"
        assert route.request.headers.get("idempotency-key")
        command = route.request.post_data_json
        assert isinstance(command, dict)
        assert command["version"] >= 1
        retried = True
        route.fulfill(status=202, json={"delivery_status": "queued"})

    page.route(f"**/api/data-platform/v1/dataset-releases/{REVIEW_ID}", detail)
    page.route(f"**/api/data-platform/v1/dataset-releases/{REVIEW_ID}/retry-delivery", retry)
    _open(page, fixture_origin, f"releases/{REVIEW_ID}")
    expect(page.get_by_role("heading", name="Published dataset", exact=True)).to_be_visible()
    expect(
        page.get_by_text(
            "Published in the data platform. Downstream import needs attention:", exact=False
        )
    ).to_be_visible()
    expect(page.get_by_role("button", name="Publish", exact=True)).to_have_count(0)
    expect(page.get_by_text("Awaiting review", exact=True)).to_have_count(0)
    page.get_by_role("button", name="Retry downstream import", exact=True).click()
    expect(page.get_by_text("Downstream import continues", exact=False)).to_be_visible()
    expect(page.get_by_role("heading", name="Published dataset", exact=True)).to_be_visible()
    assert retried


def test_release_list_refresh_preserves_unsubmitted_filters(
    page: Page, fixture_origin: str
) -> None:
    published = False

    def releases(route: Route) -> None:
        response = route.fetch()
        payload = response.json()
        release = next(item for item in payload["items"] if item["id"] == CANDIDATE_ID)
        release["status"] = "accepted" if published else "awaiting_review"
        release["publication_status"] = "completed" if published else "pending"
        route.fulfill(response=response, json=payload)

    page.route("**/api/data-platform/v1/dataset-releases?*", releases)
    _open(page, fixture_origin, "releases")
    row = page.get_by_role("row").filter(has=page.locator(f'a[href="#releases/{CANDIDATE_ID}"]'))
    expect(row).to_contain_text("Publishing")
    search = page.get_by_role("searchbox", name="Search (optional)", exact=True)
    search.fill("Unsubmitted search")
    published = True
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    expect(row).to_contain_text("Published")
    expect(search).to_have_value("Unsubmitted search")
    expect(search).to_be_focused()


def test_release_state_refreshes_without_waiting_for_record_preview(
    page: Page, fixture_origin: str
) -> None:
    state = {"published": False}
    previews: list[Route] = []

    def detail(route: Route) -> None:
        response = route.fetch()
        payload = response.json()
        payload["release"]["status"] = "accepted" if state["published"] else "awaiting_review"
        payload["activations"] = [{"status": "succeeded" if state["published"] else "running"}]
        payload["consumer_imports"] = []
        route.fulfill(response=response, json=payload)

    page.route(f"**/api/data-platform/v1/dataset-releases/{REVIEW_ID}", detail)
    page.route(
        f"**/api/data-platform/v1/dataset-releases/{REVIEW_ID}/records?*",
        lambda route: previews.append(route),
    )
    _open(page, fixture_origin, f"releases/{REVIEW_ID}")
    expect(page.get_by_role("heading", name="Publishing version", exact=True)).to_be_visible()
    expect(page.get_by_text("Awaiting review", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Publish", exact=True)).to_have_count(0)
    expect(page.get_by_text("Loading record preview…", exact=True)).to_be_visible()

    state["published"] = True
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    expect(page.get_by_role("heading", name="Published dataset", exact=True)).to_be_visible()
    expect(page.get_by_text("Awaiting review", exact=True)).to_have_count(0)
    assert len(previews) == 1
    previews[0].abort()


def test_stale_submit_review_action_refreshes_before_opening_a_dialog(
    page: Page, fixture_origin: str
) -> None:
    reads = 0

    def detail(route: Route) -> None:
        nonlocal reads
        reads += 1
        response = route.fetch()
        payload = response.json()
        payload["release"]["status"] = "candidate" if reads == 1 else "awaiting_review"
        payload["activations"] = []
        payload["consumer_imports"] = []
        route.fulfill(response=response, json=payload)

    page.route(f"**/api/data-platform/v1/dataset-releases/{CANDIDATE_ID}", detail)
    _open(page, fixture_origin, f"releases/{CANDIDATE_ID}")
    page.get_by_role("button", name="Submit for review", exact=True).click()
    expect(page.get_by_role("button", name="Publish", exact=True)).to_be_visible()
    expect(page.get_by_role("dialog")).to_have_count(0)
    expect(page.get_by_role("button", name="Submit for review", exact=True)).to_have_count(0)


def test_run_poll_keeps_cached_supporting_evidence_disclosure_focus_and_scroll(
    page: Page, fixture_origin: str
) -> None:
    counts: dict[str, int] = {}

    def run_feeds(route: Route) -> None:
        path = route.request.url.partition("?")[0]
        if path.endswith(f"/ingestion-runs/{RUN_ID}"):
            response = route.fetch()
            payload = response.json()
            payload["run"]["status"] = "running"
            route.fulfill(response=response, json=payload)
            return
        labels = {
            "/tasks": "Update steps",
            "/quality-results": "Data checks",
            "/artifacts": "File and lineage details",
        }
        label = next((value for suffix, value in labels.items() if path.endswith(suffix)), "")
        if label:
            counts[label] = counts.get(label, 0) + 1
            if counts[label] > 1:
                _temporary_read_failure(route, label.lower().replace(" ", "-"))
            else:
                route.continue_()
            return
        route.continue_()

    release_count = 0

    def release_feed(route: Route) -> None:
        nonlocal release_count
        release_count += 1
        if release_count > 1:
            _temporary_read_failure(route, "published-version")
        else:
            route.continue_()

    page.route("**/api/data-platform/v1/ingestion-runs/**", run_feeds)
    page.route(
        f"**/api/data-platform/v1/dataset-releases?ingestion_run_id={RUN_ID}&limit=100",
        release_feed,
    )
    _open(page, fixture_origin, f"runs/{RUN_ID}")
    expect(page.locator(".timeline li").first).to_be_visible()
    technical_summary = page.locator("details.technical > summary").last
    technical_summary.click()
    technical_summary.scroll_into_view_if_needed()
    technical_summary.focus()
    before_scroll = page.evaluate("window.scrollY")

    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    expect(
        page.get_by_text("Update steps are temporarily unavailable", exact=False)
    ).to_be_visible()
    expect(page.get_by_text("Data checks are temporarily unavailable", exact=False)).to_be_visible()
    expect(
        page.get_by_text("File and lineage details are temporarily unavailable", exact=False)
    ).to_be_visible()
    expect(
        page.get_by_text("Published-version details are temporarily unavailable", exact=False)
    ).to_be_visible()
    expect(page.locator(".timeline li").first).to_be_visible()

    restored_summary = page.locator("details.technical > summary").last
    expect(restored_summary.locator("..")).to_have_attribute("open", "")
    expect(restored_summary).to_be_focused()
    assert abs(page.evaluate("window.scrollY") - before_scroll) <= 2
    assert page.locator("#live-region").inner_text() == ""


def test_failed_run_poll_keeps_the_current_view_and_backs_off(
    page: Page, fixture_origin: str
) -> None:
    detail_reads = 0

    def run_detail(route: Route) -> None:
        nonlocal detail_reads
        detail_reads += 1
        if detail_reads > 1:
            _temporary_read_failure(route, "run-detail")
            return
        response = route.fetch()
        payload = response.json()
        payload["run"]["status"] = "running"
        route.fulfill(response=response, json=payload)

    page.route(f"**/api/data-platform/v1/ingestion-runs/{RUN_ID}", run_detail)
    _open(page, fixture_origin, f"runs/{RUN_ID}")
    technical_summary = page.locator("details.technical > summary").last
    technical_summary.click()
    technical_summary.focus()

    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    expect(page.get_by_text("Refresh delayed · retrying automatically")).to_be_visible()
    expect(page.get_by_role("heading", name="Example property records update")).to_be_visible()
    expect(technical_summary.locator("..")).to_have_attribute("open", "")
    expect(technical_summary).to_be_focused()
    assert detail_reads == 2


def test_interrupted_run_detail_reconciles_external_resume_on_the_same_page(
    page: Page, fixture_origin: str
) -> None:
    desired_state = "interrupted"
    detail_reads = 0

    def changing_run_detail(route: Route) -> None:
        nonlocal detail_reads, desired_state
        detail_reads += 1
        response = route.fetch()
        payload = response.json()
        payload["run"]["status"] = desired_state
        route.fulfill(response=response, json=payload)

    page.route(f"**/api/data-platform/v1/ingestion-runs/{RUN_ID}", changing_run_detail)
    _open(page, fixture_origin, f"runs/{RUN_ID}")

    expect(page.get_by_role("button", name="Resume update")).to_be_visible()
    expect(page.get_by_role("button", name="Cancel update")).to_have_count(0)
    expect(
        page.get_by_text("checking periodically for recovery started elsewhere", exact=False)
    ).to_be_visible()

    desired_state = "queued"
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    expect(page.locator(".badge").filter(has_text="Queued").first).to_be_visible()
    desired_state = "staging"
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    expect(page.locator(".badge").filter(has_text="Staging").first).to_be_visible()
    desired_state = "succeeded"
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    expect(page.locator(".badge").filter(has_text="Succeeded").first).to_be_visible()

    terminal_read_count = detail_reads
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
    page.wait_for_timeout(100)
    assert detail_reads == terminal_read_count


def test_running_unknown_total_is_explicitly_indeterminate(page: Page, fixture_origin: str) -> None:
    def running_detail(route: Route) -> None:
        response = route.fetch()
        payload = response.json()
        payload["run"]["status"] = "staging"
        route.fulfill(response=response, json=payload)

    def indeterminate_tasks(route: Route) -> None:
        response = route.fetch()
        payload = response.json()
        task = payload["items"][0]
        task.update(
            {
                "status": "running",
                "stage": "import",
                "logical_key": "typed-materialisation",
                "progress_phase": "resolving exact addresses",
                "progress_rows": 100000,
                "progress_total_rows": None,
                "progress_bytes": 0,
                "progress_total_bytes": None,
                "finished_at": None,
            }
        )
        route.fulfill(response=response, json=payload)

    page.route(f"**/api/data-platform/v1/ingestion-runs/{RUN_ID}", running_detail)
    page.route(
        f"**/api/data-platform/v1/ingestion-runs/{RUN_ID}/tasks?limit=100",
        indeterminate_tasks,
    )
    _open(page, fixture_origin, f"runs/{RUN_ID}")

    expect(
        page.get_by_text("100,000 rows · remaining work indeterminate", exact=False)
    ).to_be_visible()
    expect(page.locator("progress.timeline-progress")).to_have_count(0)


def test_jobs_list_error_retry_restores_route_heading_focus(
    page: Page, fixture_origin: str
) -> None:
    reads = 0

    def fail_jobs_once(route: Route) -> None:
        nonlocal reads
        reads += 1
        if reads == 1:
            _temporary_read_failure(route, "jobs-list")
        else:
            route.continue_()

    page.route("**/api/data-platform/v1/jobs?**", fail_jobs_once)
    page.goto(f"{fixture_origin}{FEATURE_PATH}?scenario=populated&test={time.time_ns()}#jobs")
    expect(page.get_by_role("heading", name="Service temporarily unavailable")).to_be_visible()

    page.get_by_role("button", name="Try again").click()

    heading = page.get_by_role("heading", name="Data updates", exact=True)
    expect(heading).to_be_visible()
    expect(heading).to_be_focused()
    expect(page).to_have_title("PropertyScope | Data updates")
    assert reads == 2


def test_leaving_jobs_aborts_its_request_without_replacing_the_new_route(
    page: Page, fixture_origin: str
) -> None:
    held: list[Route] = []
    failed_requests: list[str] = []

    def hold_jobs(route: Route) -> None:
        held.append(route)

    page.on(
        "requestfailed",
        lambda request: (
            failed_requests.append(request.url)
            if "/api/data-platform/v1/jobs?" in request.url
            else None
        ),
    )
    page.route("**/api/data-platform/v1/jobs?*", hold_jobs)
    page.goto(f"{fixture_origin}{FEATURE_PATH}?scenario=populated&test={time.time_ns()}#jobs")
    deadline = time.monotonic() + 5
    while not held and time.monotonic() < deadline:
        page.wait_for_timeout(10)
    assert held, "the delayed Jobs request was not observed"

    page.evaluate("location.hash = '#releases'")
    heading = page.get_by_role("heading", name="Published data")
    expect(heading).to_be_visible()
    expect(heading).to_be_focused()

    deadline = time.monotonic() + 2
    while not failed_requests and time.monotonic() < deadline:
        page.wait_for_timeout(10)
    assert failed_requests, "the obsolete Jobs request was not aborted"

    expect(heading).to_be_visible()
    expect(heading).to_be_focused()
    assert page.title() == "PropertyScope | Published data"
    assert page.evaluate("location.hash") == "#releases"


def test_ai_review_history_and_specialist_routes_render_from_live_fixture_contracts(
    page: Page, fixture_origin: str
) -> None:
    _open(page, fixture_origin, "ai")
    expect(page.get_by_role("heading", name="AI review", exact=True)).to_be_visible()
    recent_reviews = page.get_by_text("Recent AI reviews", exact=True)
    expect(recent_reviews).to_be_visible()
    recent_reviews.click()
    page.get_by_role("link", name="View result").click()
    page.wait_for_function(f"() => location.hash === '#ai/{AGENT_RUN_ID}'")
    expect(page.get_by_role("heading", name="AI review result", exact=True)).to_be_visible()
    expect(page.get_by_role("heading", name="Recommended next step")).to_be_visible()

    _open(page, fixture_origin, "quality")
    expect(page.get_by_role("heading", name="Choose a data update")).to_be_visible()


def test_jobs_list_secondary_actions_use_keyboard_accessible_overflow(
    page: Page, fixture_origin: str
) -> None:
    _open(page, fixture_origin, "jobs")
    expect(
        page.get_by_role("button", name="Start update Example property records update")
    ).to_be_visible()
    expect(
        page.get_by_role("button", name="Load earlier data Example property records update")
    ).to_be_hidden()

    more = page.get_by_role("button", name="More actions for Example property records update")
    details = page.get_by_role("link", name="View details Example property records update")
    expect(details).to_be_visible()
    more.focus()
    more.press("ArrowDown")

    history = page.get_by_role("link", name="View history Example property records update")
    expect(history).to_be_visible()
    expect(history).to_be_focused()
    expect(more).to_have_attribute("aria-expanded", "true")

    history.press("Escape")
    expect(history).to_be_hidden()
    expect(details).to_be_visible()
    expect(more).to_be_focused()
    expect(more).to_have_attribute("aria-expanded", "false")


def test_ai_manual_refresh_preserves_disclosure_and_refresh_focus(
    page: Page, fixture_origin: str
) -> None:
    _open(page, fixture_origin, f"ai/{AGENT_RUN_ID}")
    technical_summary = page.get_by_text("Technical run references", exact=True)
    technical_summary.click()
    refresh = page.get_by_role("button", name="Refresh result")

    refresh.click()

    refreshed_summary = page.get_by_text("Technical run references", exact=True)
    expect(refreshed_summary.locator("..")).to_have_attribute("open", "")
    expect(page.get_by_role("button", name="Refresh result")).to_be_focused()


def test_run_and_failed_ai_details_remain_clear_at_mobile_width(
    page: Page, fixture_origin: str
) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    _open(page, fixture_origin, f"runs/{RUN_ID}")

    expect(page.get_by_role("heading", name="Example property records update")).to_be_visible()
    for label in ("Use downloaded file", "Ask AI about update", "Review candidate data"):
        expect(page.get_by_role("button", name=label)).to_be_visible()
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )

    def failed_agent_run(route: Route) -> None:
        response = route.fetch()
        payload = response.json()
        payload["run"]["status"] = "failed"
        payload["run"]["final_result"] = None
        payload["run"]["error"] = {
            "code": "fixture_failed",
            "message": "Deterministic AI review failure",
        }
        route.fulfill(response=response, json=payload)

    page.route(f"**/api/data-platform/v1/agent-runs/{AGENT_RUN_ID}", failed_agent_run)
    _open(page, fixture_origin, f"ai/{AGENT_RUN_ID}")

    expect(page.get_by_role("heading", name="AI review failed", exact=True)).to_be_visible()
    expect(
        page.get_by_text("retained activity record and cannot be changed", exact=False)
    ).to_be_visible()
    expect(page.get_by_role("heading", name="AI review in progress", exact=True)).to_have_count(0)
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )


def test_ai_active_poll_preserves_disclosure_without_stealing_external_focus(
    page: Page, fixture_origin: str
) -> None:
    detail_reads = 0

    def active_agent_run(route: Route) -> None:
        nonlocal detail_reads
        detail_reads += 1
        response = route.fetch()
        payload = response.json()
        payload["run"]["status"] = "acting"
        route.fulfill(response=response, json=payload)

    page.route(f"**/api/data-platform/v1/agent-runs/{AGENT_RUN_ID}", active_agent_run)
    _open(page, fixture_origin, f"ai/{AGENT_RUN_ID}")
    technical_summary = page.get_by_text("Technical run references", exact=True)
    technical_summary.click()
    external_focus = page.get_by_role("link", name="New AI review")
    external_focus.focus()

    page.wait_for_timeout(1_200)

    assert detail_reads >= 2
    expect(
        page.get_by_text("Technical run references", exact=True).locator("..")
    ).to_have_attribute("open", "")
    expect(external_focus).to_be_focused()
