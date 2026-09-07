"""Exercise safe production UI interactions using isolated browser-only fixture sessions.

No interaction can reach an external service. Every write is an in-memory fixture write.
This explicitly weaker injected-document runner is not a substitute for real-origin QA.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, expect, sync_playwright

from scripts.ui_experience_audit import ROUTES, BrowserSession, inspect


def property_search(page: Page, session: BrowserSession) -> None:
    expect(page.locator(".result-card").first).to_be_visible()
    expect(page.locator(".property-results-heading")).to_contain_text("property found")
    page.locator("#property-search-query").fill("2000")
    page.locator("form.search-box").get_by_role("button", name="Search", exact=True).click()
    expect(page.locator(".property-results-heading")).to_contain_text("2000")
    page.get_by_text("Match details", exact=True).click()
    expect(page.locator(".property-results table")).to_be_visible()
    searches = [request for request in session.fixture.requests
                if request["path"].endswith("/properties/search")]
    assert len(searches) == 2


def navigation(page: Page, session: BrowserSession) -> None:
    toggle = page.locator(".ps-product-menu-toggle")
    expect(toggle).to_be_visible()
    toggle.focus()
    page.keyboard.press("Enter")
    expect(toggle).to_have_attribute("aria-expanded", "true")
    nav = page.locator(".ps-product-nav")
    expect(nav.locator("a")).to_have_count(5)
    assert nav.locator("a").first.evaluate("el => el === document.activeElement")
    page.keyboard.press("Escape")
    expect(toggle).to_have_attribute("aria-expanded", "false")
    expect(toggle).to_be_focused()
    assert not page.evaluate("document.body.classList.contains('ps-product-menu-open')")


def market(page: Page, session: BrowserSession) -> None:
    page.locator("#new-case").click()
    expect(page.locator("#case-dialog")).to_be_visible()
    expect(page.locator("#form-name")).to_be_focused()
    # Native modal must retain keyboard focus in both directions.
    for key in ["Tab"] * 12 + ["Shift+Tab"] * 12:
        page.keyboard.press(key)
        assert page.evaluate("document.activeElement.closest('dialog')?.open")
    page.locator("#form-name").fill("Keyboard research case")
    page.locator("#form-from").fill("2020-01-01")
    page.locator("#form-to").fill("2026-06-30")
    page.locator("#case-form button[type=submit]").click()
    expect(page.locator("#case-dialog")).not_to_be_visible()
    assert len(session.fixture.records["market-cases"]) == 2
    page.get_by_role("button", name="Edit", exact=True).click()
    page.locator("#form-name").fill("Revised research case")
    page.locator("#case-form button[type=submit]").click()
    expect(page.locator("#case-dialog")).not_to_be_visible()
    assert any(
        item["name"] == "Revised research case"
        for item in session.fixture.records["market-cases"]
    )
    page.get_by_role("button", name="Edit", exact=True).click()
    page.keyboard.press("Escape")
    expect(page.get_by_role("button", name="Edit", exact=True)).to_be_focused()
    page.locator("#assistant-form button").click()
    expect(page.locator("#assistant-form button")).to_be_disabled()
    expect(page.locator("#assistant-answer")).to_contain_text("incomplete coverage", timeout=15000)
    expect(page.locator("#assistant-activity")).to_be_visible()


def market_validation(page: Page, session: BrowserSession) -> None:
    page.get_by_role("button", name="Edit", exact=True).click()
    page.locator("#form-name").fill("Keep my entered title")
    page.locator("#case-form button[type=submit]").click()
    expect(page.locator("#form-error")).to_be_visible()
    expect(page.locator("#form-error")).to_be_focused()
    expect(page.locator("#form-name")).to_have_value("Keep my entered title")
    assert len(session.fixture.records["market-cases"]) == 1


def comparisons(page: Page, session: BrowserSession) -> None:
    page.locator("#new-comparison").click()
    expect(page.locator("#comparison-name")).to_be_focused()
    # Cancel must work even while a native required name field is empty.
    page.get_by_role("button", name="Cancel", exact=True).click()
    expect(page.locator("#comparison-dialog")).not_to_be_visible()
    expect(page.locator("#new-comparison")).to_be_focused()
    page.locator("#new-comparison").click()
    page.locator("#comparison-name").fill("Same-period evidence comparison")
    page.locator("#comparison-a").select_option("Parramatta")
    page.locator("#comparison-b").select_option("Parramatta")
    page.locator("#save-comparison").click()
    expect(page.locator("#form-error")).to_contain_text("different")
    expect(page.locator("#form-error")).to_be_focused()
    page.locator("#comparison-b").select_option("Newtown")
    page.locator("#save-comparison").click()
    expect(page.locator("#comparison-dialog")).not_to_be_visible()
    assert len(session.fixture.records["suburb-comparisons"]) == 2


def trends(page: Page, session: BrowserSession) -> None:
    page.locator("#locality-a").select_option("Parramatta")
    page.locator("#locality-b").select_option("Newtown")
    page.locator("#trend-form button[type=submit]").click()
    expect(page.locator("#chart svg")).to_be_visible()
    expect(page.locator("#chart-legend")).to_contain_text("Parramatta")
    expect(page.locator("#chart-legend")).to_contain_text("Newtown")
    # Unknown/missing evidence is represented by a dash, not a zero observation.
    expect(page.locator("#trend-body")).to_contain_text("—")
    page.locator("#locality-b").select_option("Parramatta")
    page.locator("#trend-form button[type=submit]").click()
    expect(page.locator("#trend-notice")).to_contain_text("different")


def site_review(page: Page, session: BrowserSession) -> None:
    page.get_by_role("button", name="Edit", exact=True).click()
    page.locator("#review-title").fill("Planning evidence reviewed")
    page.locator("#review-submit").click()
    expect(page.locator("#review-dialog")).not_to_be_visible()
    expect(page.locator("#view h1")).to_contain_text("Planning evidence reviewed")
    page.get_by_role("button", name="Generate & save questions", exact=True).click()
    expect(page.locator(".questions-status")).to_contain_text("Saved 2", timeout=15000)
    assert len(session.fixture.records["site-reviews"][0]["verification_questions"]) == 2
    expect(page.locator(".question-activity")).to_be_visible()


def buyer(page: Page, session: BrowserSession) -> None:
    page.locator("[data-add-task]").click()
    expect(page.locator("#task-title")).to_be_focused()
    page.locator("#save-task").click()
    expect(page.locator("#task-title")).to_have_attribute("aria-invalid", "true")
    page.locator("#task-title").fill("Check evidence with the professional")
    page.locator("#save-task").click()
    expect(page.locator("#task-dialog")).not_to_be_visible()
    assert len(session.fixture.records["tasks"]) == 2
    page.locator("[data-add-note]").click()
    page.locator("#note-content").fill("The missing record still needs verification.")
    page.locator("#save-note").click()
    expect(page.locator("#note-dialog")).not_to_be_visible()
    assert len(session.fixture.records["notes"]) == 2
    page.locator("[data-complete-task]").first.click()
    expect(page.locator("[data-complete-task]").first).to_have_text("Mark incomplete")
    page.locator("[data-generate-summary]").click()
    expect(page.locator("[data-summary-run]")).to_contain_text(
        "Case summary generated successfully"
    )
    expect(page.locator("[data-summary-run] .workflow-phases")).to_be_visible()
    assert not page.locator("[data-summary-run] a[href*='operations/ai-mode']").count()


def assistant(page: Page, session: BrowserSession) -> None:
    message = page.locator("#ps-ai-chat-message")
    message.fill("How do I check the source coverage?")
    message.press("Shift+Enter")
    expect(message).to_have_value("How do I check the source coverage?\n")
    message.fill("Explain source coverage.\n" * 15)
    assert message.evaluate("el => el.clientHeight") <= 200
    message.fill("How do I check the source coverage?")
    # IME Enter must not create a turn.
    message.evaluate(
        "el => el.dispatchEvent(new KeyboardEvent('keydown', "
        "{key:'Enter', isComposing:true, bubbles:true}))"
    )
    assert not session.fixture.turns
    message.press("Enter")
    expect(page.locator(".ps-ai-chat__turn")).to_have_count(1)
    message.fill("Retain this next question while the current turn runs.")
    message.press("Enter")
    assert len(session.fixture.turns) == 1
    expect(page.locator("#ps-ai-chat-scope")).to_be_disabled()
    disclosure = page.locator(".ps-ai-chat__evidence").first
    if disclosure.count():
        disclosure.locator("summary").click()
    if session.fixture.mode == "ai-failed":
        expect(page.locator(".ps-ai-chat__turn-error")).to_contain_text(
            "could not complete", timeout=15000
        )
        page.get_by_role("button", name="Prepare question again").click()
        expect(message).to_have_value("How do I check the source coverage?")
        assert len(session.fixture.turns) == 1
    elif session.fixture.mode == "ai-review":
        expect(page.locator(".ps-ai-chat__turn")).to_contain_text("review", timeout=15000)
        page.wait_for_timeout(4500)
        assert list(session.fixture.turns.values())[0]["status"] == "review_required"
    elif session.fixture.mode == "provider-unavailable":
        expect(page.locator(".ps-ai-chat__turn-error")).to_be_visible()
        assert not session.fixture.turns
    else:
        expect(page.locator(".ps-ai-chat__turn")).to_contain_text(
            "not a live model answer", timeout=20000
        )
        expect(message).to_have_value("Retain this next question while the current turn runs.")
        expect(page.locator("#ps-ai-chat-scope")).to_be_enabled()
        if disclosure.count():
            assert disclosure.evaluate("el => el.open")


def assistant_cancel(page: Page, session: BrowserSession) -> None:
    message = page.locator("#ps-ai-chat-message")
    message.fill("Check the accepted evidence.")
    message.press("Enter")
    cancel = page.locator('[data-action="cancel"]')
    expect(cancel).to_be_visible()
    cancel.click()
    expect(page.locator(".ps-ai-chat__turn")).to_contain_text("Cancelled")
    page.wait_for_timeout(1300)
    assert list(session.fixture.turns.values())[0]["cancelled"]
    expect(page.locator("#ps-ai-chat-scope")).to_be_enabled()


def activity(page: Page, session: BrowserSession) -> None:
    page.locator("#run-list button").first.click()
    expect(page.locator("#detail-content")).to_be_visible()
    expect(page.locator("#run-objective")).to_contain_text("accepted property", timeout=10000)
    page.locator("#back-to-runs").click()
    expect(page.locator("#run-list")).to_be_visible()
    page.locator(".operations-navigation > summary").click()
    expect(page.locator(".operations-nav")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.locator(".operations-navigation > summary")).to_be_focused()


def assistant_unavailable(page: Page, session: BrowserSession) -> None:
    message = page.locator("#ps-ai-chat-message")
    message.fill("Check this property evidence.")
    message.press("Enter")
    expect(page.locator(".ps-ai-chat__turn-error")).to_be_visible()
    assert not session.fixture.turns
    expect(page.locator("#ps-ai-chat-scope")).to_be_enabled()
    # A rejected submission has no durable run to replay. Its draft is restored
    # automatically and is not silently resubmitted.
    expect(message).to_have_value("Check this property evidence.")


def assistant_no_evidence(page: Page, session: BrowserSession) -> None:
    message = page.locator("#ps-ai-chat-message")
    message.fill("What evidence is available?")
    message.press("Enter")
    expect(page.locator(".ps-ai-chat__turn")).to_contain_text(
        "No matching evidence", timeout=20000
    )
    assert not page.locator(".ps-ai-chat__evidence li").count()
    expect(page.locator("#ps-ai-chat-scope")).to_be_enabled()


def assistant_capabilities(page: Page, session: BrowserSession) -> None:
    expect(page.locator("#ps-ai-chat-message")).to_be_enabled()
    expect(page.locator("main")).to_contain_text("Capability guide unavailable")
    page.locator("#ps-ai-chat-message").fill("What can this area answer?")
    page.locator("#ps-ai-chat-message").press("Enter")
    expect(page.locator(".ps-ai-chat__turn")).to_contain_text(
        "not a live model answer", timeout=20000
    )


def data_operator(page: Page, session: BrowserSession) -> None:
    page.get_by_role("button", name="Start update", exact=True).click()
    modal = page.locator("#action-dialog")
    expect(modal).to_be_visible()
    page.get_by_role("button", name="Preview update", exact=True).click()
    expect(modal).to_contain_text("Update checked")
    assert not any(item["method"] == "POST" and item["path"].endswith("/runs")
                   for item in session.fixture.requests)
    page.locator("#action-confirm").click()
    expect(modal).not_to_be_visible()
    expect(page.locator("#view h1")).to_be_visible()
    assert any(item["method"] == "POST" and item["path"].endswith("/runs")
               for item in session.fixture.requests)


def candidate_review(page: Page, session: BrowserSession) -> None:
    assert not page.get_by_role("button", name="Publish", exact=True).count()
    page.get_by_role("button", name="Submit for review", exact=True).click()
    modal = page.locator("#action-dialog")
    expect(modal).to_be_visible()
    page.locator("#action-confirm").click()
    expect(modal).to_be_visible()
    modal.locator("textarea").fill("Synthetic human review context; no real data is published.")
    page.locator("#action-confirm").click()
    expect(modal).not_to_be_visible()
    assert any(item["method"] == "POST" and item["path"].endswith("/submit-review")
               for item in session.fixture.requests)


CASES = (
    ("property-search-history-denied", "properties", "populated", property_search),
    ("data-update-preview-confirm", "job", "populated", data_operator),
    ("candidate-human-review-context", "candidate", "populated", candidate_review),
    ("navigation", "market", "populated", navigation),
    ("market-crud-assistant", "market", "populated", market),
    ("market-validation", "market", "validation-error", market_validation),
    ("comparison-validation-save-cancel", "comparisons", "populated", comparisons),
    ("trend-missing-and-validation", "trends", "partial", trends),
    ("review-edit-questions", "site-review", "populated", site_review),
    ("buyer-task-note-evidence-summary", "buyer-case", "populated", buyer),
    ("assistant-composer-duplicate-evidence", "data-assistant", "populated", assistant),
    ("assistant-failed-recovery", "data-assistant", "ai-failed", assistant),
    ("assistant-poll-outage", "data-assistant", "ai-poll-error", assistant),
    ("assistant-review-required", "data-assistant", "ai-review", assistant),
    ("assistant-cancel", "data-assistant", "populated", assistant_cancel),
    (
        "assistant-provider-unavailable", "data-assistant", "provider-unavailable",
        assistant_unavailable,
    ),
    ("assistant-invalid-context", "data-assistant", "validation-error", assistant_unavailable),
    ("assistant-no-evidence", "data-assistant", "ai-no-evidence", assistant_no_evidence),
    (
        "assistant-capabilities-unavailable", "assistant", "capabilities-error",
        assistant_capabilities,
    ),
    ("activity-storage-denied-navigation", "ai-activity", "populated", activity),
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:5300")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--executable")
    parser.add_argument("--injected-document", action="store_true")
    parser.add_argument("--cases", default="all")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=args.executable, headless=True)
        for name, route, mode, exercise in CASES:
            if args.cases != "all" and name not in args.cases.split(","):
                continue
            print(name, flush=True)
            session = BrowserSession(args.base, mode, injected=args.injected_document)
            context = browser.new_context(
                viewport={"width": 390, "height": 844}, reduced_motion="reduce"
            )
            context.set_default_timeout(6000)
            context.route("**/*", session.intercept)
            page = context.new_page()
            errors: list[str] = []
            page.on(
                "pageerror", lambda error, target=errors: target.append(error.stack or str(error))
            )
            page.on("dialog", lambda dialog: dialog.accept())
            row: dict[str, Any] = {"name": name, "route": route, "mode": mode}
            try:
                session.load(page, ROUTES[route])
                page.wait_for_timeout(600)
                exercise(page, session)
                row.update(inspect(page))
                assert not row["overflow"], "Unexpected horizontal page overflow"
                assert not errors, errors
                row["status"] = "passed"
            except Exception as error:
                row["status"] = "failed"
                row["error"] = str(error)
            row.update(page_errors=errors, requests=session.fixture.requests,
                       failed_responses=session.failures)
            page.screenshot(path=str(args.output / f"{name}.png"), full_page=True, timeout=20000)
            results.append(row)
            print(row["status"], row.get("error", "")[:160], flush=True)
            context.unroute_all(behavior="ignoreErrors")
            context.close()
        browser.close()
    profile = "injected-document" if args.injected_document else "real-origin"
    report = {"profile": profile + "; synthetic in-memory writes only", "cases": results,
              "passed": sum(row["status"] == "passed" for row in results), "total": len(results)}
    (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"{report['passed']}/{report['total']} passed")
    raise SystemExit(0 if report["passed"] == report["total"] else 1)


if __name__ == "__main__":
    main()
