"""Real Chromium canaries proving the UI audit detects intentional regressions."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright
from scripts.ui_audit.models import AuditBatch, AuditCase, Viewport
from scripts.ui_audit.runner import audit_batch
from scripts.ui_fixture_server import LOOPBACK_HOST, UIFixtureServer


def _batch(kind: str) -> AuditBatch:
    return AuditBatch(
        id=f"canary--{kind}",
        workspace="shared",
        route_group="canary",
        route_id=f"canary-{kind}",
        path=f"/__ui-fixture__/canary/{kind}",
        case=AuditCase(id=kind, scenario="populated", states=(kind,), readiness="h1"),
        viewport=Viewport(
            id="laptop-wide",
            width=1440,
            height=1000,
            gate="release-critical-full-matrix",
        ),
        fingerprint=kind * 8,
    )


@pytest.mark.parametrize(
    ("kind", "expected_status", "expected_code"),
    (
        ("clean", "passed", None),
        ("overflow", "failed", "page-horizontal-overflow"),
        ("console-error", "failed", "unexpected-console-error"),
    ),
)
def test_browser_canary(
    kind: str, expected_status: str, expected_code: str | None, tmp_path: Path
) -> None:
    server = UIFixtureServer(0, "populated")
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        with sync_playwright() as playwright:
            executable = Path(playwright.chromium.executable_path)
            if not executable.is_file():
                pytest.skip("Playwright Chromium is not installed")
            browser = playwright.chromium.launch(headless=True)
            try:
                result = audit_batch(
                    browser,
                    _batch(kind),
                    base_url=f"http://{LOOPBACK_HOST}:{server.server_port}",
                    output=tmp_path,
                )
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert result["status"] == expected_status
    codes = {finding["code"] for finding in result["findings"]}
    if expected_code is None:
        assert not codes
    else:
        assert expected_code in codes
