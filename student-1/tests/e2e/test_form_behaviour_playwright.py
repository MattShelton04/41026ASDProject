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
from collections.abc import Callable, Iterator
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


def _free_port() -> int:
    with socket.socket() as candidate:
        candidate.bind(("127.0.0.1", 0))
        return int(candidate.getsockname()[1])


@pytest.fixture(scope="session")
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


@pytest.fixture(scope="session")
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


def _abort_external_map(page: Page) -> None:
    page.route("**/tiles.openfreemap.org/**", lambda route: route.abort())


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
    query = page.get_by_label("NSW street address")
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
    page.set_viewport_size({"width": 1024, "height": 768})
    query = "11 Example Street"
    page.goto(
        f"{fixture_origin}{FEATURE_PATH}?scenario=populated&test={time.time_ns()}"
        f"#properties?q=11%20Example%20Street"
    )
    result = page.get_by_role("link", name="Open 11 Example Street, Sydney NSW 2000")
    expect(result).to_be_visible()
    assert result.evaluate("element => element.tagName") == "A"
    expect(result).to_have_attribute("href", f"#properties/{PROPERTY_ID}?q=11+Example+Street")
    page.evaluate("window.scrollTo(0, Math.min(180, document.documentElement.scrollHeight))")
    original_scroll = page.evaluate("window.scrollY")
    result.click()
    expect(page.get_by_role("heading", name="11 Example Street, Sydney NSW 2000")).to_be_visible()

    page.go_back()
    expect(page.get_by_role("heading", name="Explore NSW properties")).to_be_visible()
    expect(result).to_be_visible()
    expect(result).to_be_focused()
    assert page.evaluate("new URLSearchParams(location.hash.split('?')[1]).get('q')") == query
    assert abs(page.evaluate("window.scrollY") - original_scroll) <= 1


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
            if (/\/properties\/[^/]+\/(map-context|coverage|report-section)$/.test(url)) {
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
    expect(page.get_by_text("Match status")).to_be_visible()
    expect(page.get_by_text("Loading spatial context…")).to_be_visible()
    assert page.evaluate("window.__pendingPropertyOptionalCount()") == 3

    page.evaluate("window.__releasePropertyOptional()")
    expect(page.get_by_role("heading", name="Available research coverage")).to_be_visible()
    expect(page.locator(".map-context")).to_be_visible()
    page.get_by_text("Property identifiers and coordinates", exact=True).click()
    expect(page.get_by_role("heading", name="Source summary")).to_be_visible()


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
    page.get_by_text("Property identifiers and coordinates", exact=True).click()
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
    expect(page.get_by_role("heading", name="11 Example Street, Sydney NSW 2000")).to_be_visible()
    assert detail_calls == 2


def test_search_and_every_filter_use_native_keyboard_and_explicit_reset(
    page: Page, fixture_origin: str
) -> None:
    _open(page, fixture_origin, "properties")
    query = page.get_by_label("NSW street address")
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
    expect(page.get_by_text("1 match", exact=True)).to_be_visible()
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
    expect(page.get_by_role("heading", name="Explore NSW properties")).to_be_visible()
    query = page.get_by_label("NSW street address")
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


def test_source_job_and_release_create_edit_forms_retain_server_failures(
    page: Page, fixture_origin: str
) -> None:
    _open(page, fixture_origin, "sources")
    page.get_by_role("button", name="Create source").click()
    expect(page.locator('[name="name"]')).to_be_focused()
    page.locator("#entity-save").click()
    expect(page.locator("#entity-error")).to_contain_text("Please correct Source name")
    expect(page.locator('[name="name"]')).to_be_focused()
    page.get_by_role("button", name="Cancel").click()

    page.get_by_role("button", name="Edit Example NSW property records").click()
    source_notes = page.locator('[name="notes"]')
    targets = page.locator('[name="target_features"]')
    targets.fill('["one","two","three","four","five","six"]')
    page.locator("#entity-save").click()
    expect(page.locator("#entity-error")).to_contain_text("Please correct Research area keys")
    expect(targets).to_have_attribute("aria-describedby", "form-field-target_features-error")
    targets.fill('["one","one"]')
    expect(page.locator("#form-field-target_features-error")).to_contain_text("at most 5 values")
    page.locator("#entity-save").click()
    expect(page.locator("#form-field-target_features-error")).to_contain_text(
        "must not contain duplicate values"
    )
    targets.fill('["feature-1"]')
    expect(page.locator("#form-field-target_features-error")).to_have_count(0)
    expect(targets).not_to_have_attribute("aria-invalid", "true")
    expect(targets).not_to_have_attribute("aria-describedby", "form-field-target_features-error")
    expect(page.locator("#entity-error")).to_be_empty()
    source_notes.fill("Retained source evidence")
    source_writes = _fail_first_write(page, "**/api/data-platform/v1/sources/*", method="PUT")
    page.locator("#entity-save").click()
    expect(page.locator("#entity-dialog")).to_be_visible()
    expect(page.locator("#entity-error")).to_contain_text("values are still here")
    expect(source_notes).to_have_value("Retained source evidence")
    page.locator("#entity-save").click()
    expect(page.locator("#entity-dialog")).not_to_be_visible()
    assert len(source_writes) == 2

    _open(page, fixture_origin, "jobs")
    page.get_by_role("button", name="Create update").click()
    page.locator("#entity-save").click()
    expect(page.locator("#entity-error")).to_contain_text("Please correct Source ID")
    page.get_by_role("button", name="Cancel").click()
    page.get_by_role("button", name="Edit Example property records update").click()
    schedule = page.locator('[name="schedule_text"]')
    expect(schedule).to_have_attribute("maxlength", "200")
    expect(page.locator('[name="max_parallelism"]')).to_have_attribute("max", "16")
    expect(page.locator('[name="timeout_seconds"]')).to_have_attribute("max", "86400")
    expect(page.locator('[name="max_objects"]')).to_have_attribute("max", "100000")
    expect(page.locator('[name="max_bytes"]')).to_have_attribute("max", "100000000000")
    expect(page.locator('[name="max_rows"]')).to_have_attribute("max", "100000000")
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
    scope = page.locator('[name="advanced_scope"]')
    page.get_by_text("Advanced partition JSON (optional)").click()
    scope.fill("[]")
    page.get_by_role("button", name="Preview update").click()
    expect(page.locator("#action-error")).to_contain_text("Please correct Advanced partition JSON")
    expect(scope).to_be_focused()
    expect(scope).to_have_attribute("aria-describedby", "advanced-scope-error")
    scope.fill('{"profile":"showcase"}')
    expect(page.locator("#advanced-scope-error")).to_have_count(0)
    expect(scope).not_to_have_attribute("aria-invalid", "true")
    expect(page.locator("#action-error")).to_be_empty()
    run_writes = _fail_first_write(page, f"**/api/data-platform/v1/jobs/{JOB_ID}/runs")
    page.locator("#action-confirm").click()
    expect(page.locator("#action-error")).to_contain_text("values are still here")
    expect(scope).to_have_value('{"profile":"showcase"}')
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
    page.wait_for_function("() => location.hash === '#sources'")

    page.get_by_role("button", name="Edit Example NSW property records").click()
    page.locator('[name="notes"]').fill("Discarded for latest navigation")
    page.evaluate("location.hash = '#jobs'")
    expect(page.locator("#discard-dialog")).to_be_visible()
    page.wait_for_function("() => location.hash === '#sources'")
    page.evaluate("location.hash = '#runs'")
    page.wait_for_function("() => location.hash === '#sources'")
    page.locator("#discard-confirm").click()
    expect(page.locator("#entity-dialog")).not_to_be_visible()
    page.wait_for_function("() => location.hash === '#runs'")

    _open(page, fixture_origin, "sources")
    delete_writes = _fail_first_write(
        page, f"**/api/data-platform/v1/sources/{SOURCE_ID}", method="DELETE"
    )
    page.get_by_role("button", name="Delete Example NSW property records").click()
    page.locator("#action-confirm").click()
    expect(page.locator("#action-error")).to_contain_text("values are still here")
    expect(page.locator("#action-dialog")).to_be_visible()
    page.locator("#action-confirm").click()
    expect(page.locator("#action-dialog")).not_to_be_visible()
    assert len(delete_writes) == 2

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


def test_planner_year_and_address_bounds_have_associated_browser_errors(
    page: Page, fixture_origin: str
) -> None:
    pattern = "**/api/data-platform/v1/jobs?*"

    def rewrite(profile: str) -> Callable[[Route], None]:
        def handler(route: Route) -> None:
            response = route.fetch()
            payload = response.json()
            job = payload["items"][0]
            job["profile_key"] = profile
            job["import_profile_key"] = profile
            job["scope_json"] = {"profile": "showcase", "source_year": 2025, "maximum_records": 100}
            route.fulfill(response=response, json=payload)

        return handler

    psi_handler = rewrite("psi-sales")
    page.route(pattern, psi_handler)
    _open(page, fixture_origin, "jobs")
    page.get_by_role("button", name="Start update Example property records update").click()
    first_year = page.locator("#psi-start-year")
    last_year = page.locator("#psi-end-year")
    expect(first_year).to_be_visible()
    first_year.fill("2026")
    last_year.fill("2025")
    page.locator("#action-confirm").click()
    expect(page.locator("#action-error")).to_contain_text("Please correct Last annual archive")
    expect(last_year).to_have_attribute("aria-describedby", "psi-end-year-error")
    last_year.fill("2026")
    expect(page.locator("#psi-end-year-error")).to_have_count(0)
    expect(last_year).not_to_have_attribute("aria-invalid", "true")
    expect(page.locator("#action-error")).to_be_empty()
    page.keyboard.press("Escape")
    expect(page.locator("#discard-dialog")).to_be_visible()
    page.locator("#discard-confirm").click()
    expect(page.locator("#action-dialog")).not_to_be_visible()
    page.unroute(pattern, psi_handler)

    gnaf_handler = rewrite("gnaf-nsw")
    page.route(pattern, gnaf_handler)
    _open(page, fixture_origin, "jobs")
    page.get_by_role("button", name="Start update Example property records update").click()
    maximum = page.locator("#maximum-records")
    expect(maximum).to_be_visible()
    maximum.fill("1001")
    page.locator("#action-confirm").click()
    expect(page.locator("#action-error")).to_contain_text("Please correct Maximum addresses")
    expect(maximum).to_have_attribute("aria-describedby", "maximum-records-error")
    maximum.fill("1000")
    expect(page.locator("#maximum-records-error")).to_have_count(0)
    expect(maximum).not_to_have_attribute("aria-invalid", "true")
    expect(page.locator("#action-error")).to_be_empty()
