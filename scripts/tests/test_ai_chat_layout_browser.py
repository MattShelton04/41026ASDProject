"""Real Chromium regressions for assistant panels in narrow feature columns."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, expect, sync_playwright
from scripts.ui_fixture_server import LOOPBACK_HOST, UIFixtureServer


@pytest.fixture(scope="module")
def assistant_origin() -> Iterator[str]:
    server = UIFixtureServer(0, "populated")
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield f"http://{LOOPBACK_HOST}:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture(scope="module")
def assistant_browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        if not Path(playwright.chromium.executable_path).is_file():
            pytest.skip("Playwright Chromium is not installed")
        browser = playwright.chromium.launch(headless=True)
        try:
            yield browser
        finally:
            browser.close()


@pytest.mark.parametrize(
    ("viewport", "host_width", "layout"),
    [(1440, 435, "page"), (1440, 1260, "page"), (390, 358, "page"), (1440, 435, "embedded")],
)
def test_sources_use_the_chat_container_without_covering_evidence(
    assistant_browser: Browser, assistant_origin: str, viewport: int, host_width: int, layout: str
) -> None:
    page = assistant_browser.new_page(viewport={"width": viewport, "height": 1000})
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        page.goto(assistant_origin + "/__ui-fixture__/canary/clean")
        page.set_content(f"""<!doctype html><html lang="en"><head>
          <link rel="stylesheet" href="/design-system/tokens.css">
          <link rel="stylesheet" href="/design-system/base.css">
          <link rel="stylesheet" href="/design-system/components.css">
          <link rel="stylesheet" href="/ai-chat/styles.css">
        </head><body>
          <div id="chat" style="width:{host_width}px;max-width:100%"></div>
        </body></html>""")
        page.evaluate(
            """async layout => {
          const {createAiChat} = await import('/ai-chat/index.js');
          const run = {
            id: 'layout-test-run', status: 'succeeded',
            final_result: {
              summary: 'The retained guidance describes source coverage.',
              confidence: 'moderate', confidence_reason: 'Project guidance only.',
              grounding_status: 'ready', findings: [], citations: [{
                citation_id: 'layout-test-source', document_id: 'coverage', chunk_id: 'chunk-1',
                title: 'Source coverage', evidence_kind: 'project_guidance',
                excerpt: 'Missing records are a coverage gap, not proof of no sale. '.repeat(30),
                corpus_id: 'operator-guidance', corpus_version: 'retained-version',
                source_uri: 'https://example.org/source', source_date: '2026-10-03'
              }]
            }
          };
          window.layoutChat = createAiChat({root: document.querySelector('#chat'), layout,
            client: {getTurn: async () => ({body: run}),
                     getEvents: async () => ({body: {items: []}})},
            initialTurns: [{run, message: 'What does source coverage establish?'}]
          });
        }""",
            layout,
        )
        inspection = page.get_by_role("complementary", name="Answer sources and activity")
        trigger = page.get_by_role("button", name="Sources & activity", exact=True)
        trigger.click()
        expect(inspection).to_be_visible()
        inspection.locator("details.ps-ai-chat__source > summary").click()
        panel = inspection.bounding_box()
        shell = page.locator(".ps-ai-chat")
        chat = shell.bounding_box()
        assert panel and chat
        columns = shell.evaluate(
            "node => getComputedStyle(node).gridTemplateColumns.split(' ').length"
        )
        if host_width >= 1100 and layout == "page":
            assert columns == 2
            assert panel["width"] >= 360
            assert panel["x"] > chat["x"] + chat["width"] / 2
        else:
            assert columns == 1
            assert panel["width"] >= chat["width"] - 2
            if layout == "page":
                composer = page.locator(".ps-ai-chat__composer")
                assert composer.evaluate("node => getComputedStyle(node).position") == "static"
                composer_box = composer.bounding_box()
                assert composer_box and composer_box["y"] >= panel["y"] + panel["height"]
            else:
                expect(page.get_by_role("region", name="Assistant conversation")).to_be_hidden()
                expect(
                    page.get_by_role("textbox", name="Message PropertyScope assistant")
                ).to_be_hidden()
        assert shell.evaluate("node => node.scrollWidth <= node.clientWidth + 1")
        if viewport == 1440 and layout == "page":
            # Resizing the feature column should reflow the open panel without remounting
            # the controller or losing keyboard focus on its native source disclosure.
            source_summary = inspection.locator("details.ps-ai-chat__source > summary")
            source_summary.focus()
            resized = 435 if host_width >= 1100 else 1260
            page.locator("#chat").evaluate(
                "(node, width) => node.style.width = `${width}px`", resized
            )
            page.wait_for_function(
                "count => getComputedStyle(document.querySelector('.ps-ai-chat'))"
                ".gridTemplateColumns.split(' ').length === count",
                arg=1 if resized < 1100 else 2,
            )
            expect(source_summary).to_be_focused()
            assert shell.evaluate("node => node.scrollWidth <= node.clientWidth + 1")
        inspection.get_by_role(
            "button", name="Back to answer" if layout == "embedded" else "Close details"
        ).press("Escape")
        expect(inspection).to_be_hidden()
        expect(trigger).to_be_focused()
        assert not errors
    finally:
        page.evaluate("window.layoutChat?.destroy()")
        page.close()
