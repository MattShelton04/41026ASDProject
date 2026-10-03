"""Native screenshot regressions for transient application announcements."""

from pathlib import Path

import pytest
from PIL import Image
from scripts.capture_release1_screenshots import _focused_image, sync_playwright


def test_announcing_toast_fades_before_native_evidence_is_photographed(tmp_path: Path) -> None:
    with sync_playwright() as playwright:
        if not Path(playwright.chromium.executable_path).is_file():
            pytest.skip("Playwright Chromium is not installed")
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1100, "height": 1000})
            page.set_content(
                """<style>
                #answer { position: relative; width: 840px; height: 300px; background: white; }
                .ps-toast { position: absolute; right: 0; bottom: 0; width: 110px;
                  height: 60px; background: black; }
                .ps-toast[data-visible="false"] { opacity: 0; }
                </style><section id="answer">Complete evidence and confidence
                <div class="ps-toast" data-visible="true" role="status">Source opened</div>
                </section><script>
                setTimeout(() => {
                  document.querySelector('.ps-toast').dataset.visible = 'false';
                }, 700);
                </script>"""
            )
            destination = tmp_path / "answer.png"
            _focused_image(page, page.locator("#answer"), destination)
            assert page.locator('.ps-toast[data-visible="true"]').count() == 0
            with Image.open(destination) as photographed:
                assert photographed.size == (840, 300)
                # This region is black while the announcement is active. The browser must
                # render its natural faded state; an overlapping toast must not be published.
                assert photographed.convert("RGB").getpixel((800, 270)) == (255, 255, 255)
        finally:
            browser.close()
