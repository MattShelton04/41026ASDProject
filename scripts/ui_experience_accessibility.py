"""Measured names, contrast and motion checks; not a WCAG certification."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from scripts.ui_experience_audit import ROUTES, BrowserSession

HELPERS = Path(__file__).with_name("ui_audit")
ROUTE_NAMES = (
    "assistant", "properties", "property", "overview", "jobs", "run", "candidate",
    "ai-activity", "market", "suburbs", "trends", "comparisons", "site-review", "buyer-case",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:5300")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--executable")
    parser.add_argument("--injected-document", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    records = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=args.executable, headless=True)
        for width in (360, 1440):
            for name in ROUTE_NAMES:
                session = BrowserSession(args.base, "populated", args.injected_document)
                context = browser.new_context(
                    viewport={"width": width, "height": 1000}, reduced_motion="reduce"
                )
                context.route("**/*", session.intercept)
                page = context.new_page()
                session.load(page, ROUTES[name])
                page.wait_for_timeout(900)
                measured = page.evaluate(
                    (HELPERS / "browser_helpers.js").read_text(encoding="utf-8")
                )
                extra = page.evaluate(
                    (HELPERS / "experience_accessibility.js").read_text(encoding="utf-8")
                )
                page.keyboard.press("Tab")
                # Measure after paint; even a reduced-motion 0.01ms transition
                # has an initial frame before its computed endpoint is applied.
                page.evaluate("() => new Promise(resolve => "
                              "requestAnimationFrame(() => requestAnimationFrame(resolve)))")
                focus = page.evaluate("""() => {
                  const element = document.activeElement, style = getComputedStyle(element);
                  return {tag: element.tagName, text: element.textContent.trim().slice(0, 80),
                    outline: style.outlineStyle, width: style.outlineWidth,
                    visible: element.matches(':focus-visible')};
                }""")
                row = {"route": name, "width": width, **measured, **extra, "focus": focus}
                records.append(row)
                print(name, width, len(row["unlabeledControls"]),
                      len(row["contrast"]["failures"]), flush=True)
                context.unroute_all(behavior="ignoreErrors")
                context.close()
        browser.close()
    report = {
        "profile": "injected-document" if args.injected_document else "real-origin",
        "limit": "No manual assistive-technology, forced-colors or actual touch-device validation.",
        "cases": records,
    }
    (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
