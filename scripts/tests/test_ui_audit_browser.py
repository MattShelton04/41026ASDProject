"""Real Chromium canaries proving the UI audit detects intentional regressions."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright
from scripts.ui_audit.config import AuditSelection, compile_batches, load_config
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


def test_interaction_canary_recurses_and_skips_destructive_confirmation(tmp_path: Path) -> None:
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
                    _batch("interaction"),
                    base_url=f"http://{LOOPBACK_HOST}:{server.server_port}",
                    output=tmp_path,
                    destructive_labels=("delete",),
                )
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    statuses = {item["control"]["name"]: item["status"] for item in result["interactions"]}
    assert statuses["Delete record"] == "skipped-destructive"
    assert statuses["Open actions"] == "exercised"
    assert statuses["Nested safe action"] == "exercised"
    assert any(item.get("screenshot") for item in result["interactions"])


def test_configured_named_flows_reach_their_response_state(tmp_path: Path) -> None:
    wanted = {
        ("jobs-list", "validation"),
        ("run-detail", "conflict"),
        ("releases-list", "validation"),
        ("release-detail", "publish-conflict"),
        ("sources-list", "validation"),
        ("ai-review-new", "validation"),
    }
    batches = tuple(
        batch
        for batch in compile_batches(
            load_config(),
            profile="full",
            selection=AuditSelection(viewports=("laptop-wide",)),
            source_digest="named-flow-test",
        )
        if (batch.route_id, batch.case.id) in wanted
    )
    assert {(batch.route_id, batch.case.id) for batch in batches} == wanted
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
                results = [
                    audit_batch(
                        browser,
                        batch,
                        base_url=f"http://{LOOPBACK_HOST}:{server.server_port}",
                        output=tmp_path,
                        interaction_limit=0,
                    )
                    for batch in batches
                ]
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    failures = [
        {
            "route": result["routeId"],
            "case": result["case"]["id"],
            "findings": result["findings"],
            "telemetry": result["telemetry"],
        }
        for result in results
        if not result["baseline"].get("screenshot")
    ]
    if failures:
        pytest.fail(json.dumps(failures, indent=2))
    assert all(
        finding["code"] != "batch-exception" for result in results for finding in result["findings"]
    )
