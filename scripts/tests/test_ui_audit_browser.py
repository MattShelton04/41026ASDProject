"""Real Chromium canaries proving the UI audit detects intentional regressions."""

from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright
from scripts.ui_audit.config import AuditSelection, compile_batches, load_config
from scripts.ui_audit.inventory import _destructive, inventory_controls
from scripts.ui_audit.models import AuditBatch, AuditCase, Viewport
from scripts.ui_audit.runner import _batch_url, _context, audit_batch
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
                    destructive_labels=("delete record",),
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
    expected = {
        ("jobs-list", "validation"): ("PUT", 422, "/jobs/", "submitted value conflicts"),
        ("jobs-list", "conflict"): ("PUT", 409, "/jobs/", "Deterministic UI audit case"),
        ("job-detail", "validation"): ("PUT", 422, "/jobs/", "submitted value conflicts"),
        ("job-detail", "conflict"): ("PUT", 409, "/jobs/", "Deterministic UI audit case"),
        ("run-detail", "conflict"): ("POST", 409, "/retry", "Deterministic UI audit case"),
        ("releases-list", "validation"): (
            "POST",
            422,
            "/dataset-releases",
            "submitted value conflicts",
        ),
        ("releases-list", "conflict"): (
            "POST",
            409,
            "/dataset-releases",
            "Deterministic UI audit case",
        ),
        ("release-detail", "publish-conflict"): (
            "POST",
            409,
            "/publish",
            "Deterministic UI audit case",
        ),
        ("sources-list", "validation"): ("PUT", 422, "/sources/", "submitted value conflicts"),
        ("sources-list", "conflict"): (
            "PUT",
            409,
            "/sources/",
            "source changed after this form was opened",
        ),
        ("ai-review-new", "provider-unavailable"): (
            "POST",
            503,
            "/assistant/turns",
            "Deterministic UI audit case",
        ),
        ("ai-review-new", "validation"): (
            "POST",
            422,
            "/assistant/turns",
            "submitted value conflicts",
        ),
    }
    batches = tuple(
        batch
        for batch in compile_batches(
            load_config(),
            profile="full",
            selection=AuditSelection(viewports=("laptop-wide",)),
            source_digest="named-flow-test",
        )
        if (batch.route_id, batch.case.id) in expected
    )
    assert {(batch.route_id, batch.case.id) for batch in batches} == set(expected)
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
    for result in results:
        contract = expected[(result["routeId"], result["case"]["id"])]
        method, status, url_part, visible = contract
        matching = [
            row
            for row in result["telemetry"]["requestFailures"]
            if row["method"] == method
            and row["failure"] == f"HTTP {status}"
            and url_part in row["url"]
        ]
        assert matching and all(row["expected"] is True for row in matching), result
        if visible is not None:
            assert any(
                visible.lower() in message.lower()
                for message in result["baseline"]["statusMessages"]
            ), ((result["routeId"], result["case"]["id"]), result["baseline"]["statusMessages"])
        else:
            assert result["telemetry"]["pageErrors"] == ["Deterministic UI audit case."]
        codes = {finding["code"] for finding in result["findings"]}
        assert "expected-request-failure" in codes
        assert (
            not {"batch-exception", "unexpected-console-error", "unexpected-request-failure"}
            & codes
        )
        if visible is None:
            assert "unexpected-page-exception" in codes


def test_slow_shared_routes_capture_distinct_loading_and_true_settled_states(
    tmp_path: Path,
) -> None:
    wanted = {("shared-status", "loading-slow"), ("shared-evidence", "loading-slow")}
    batches = tuple(
        batch
        for batch in compile_batches(
            load_config(), profile="full", selection=AuditSelection(viewports=("laptop-wide",))
        )
        if (batch.route_id, batch.case.id) in wanted
    )
    results = _run_batches(batches, tmp_path)
    for result in results:
        baseline = result["baseline"]
        loading = tmp_path / baseline["loadingScreenshot"]
        settled = tmp_path / baseline["screenshot"]
        assert result["durationMs"] >= 1_200, result
        assert baseline["settledMarkerVisible"] is True
        assert loading.read_bytes() != settled.read_bytes()


def test_expected_http_failures_do_not_create_false_console_findings(tmp_path: Path) -> None:
    wanted = {
        ("job-detail", "capabilities-unavailable"),
        ("property-search", "error"),
        ("shared-evidence", "release-provider-partial"),
    }
    batches = tuple(
        batch
        for batch in compile_batches(
            load_config(), profile="full", selection=AuditSelection(viewports=("laptop-wide",))
        )
        if (batch.route_id, batch.case.id) in wanted
    )
    results = _run_batches(batches, tmp_path)
    for result in results:
        expected_requests = [
            row for row in result["telemetry"]["requestFailures"] if row["expected"]
        ]
        assert expected_requests, result
        assert all(
            row.get("method") and row.get("failure", "").startswith("HTTP ")
            for row in expected_requests
        )
        assert not any(
            finding["code"] == "unexpected-console-error" for finding in result["findings"]
        ), result


def test_below_fold_controls_are_in_baseline_measurements(tmp_path: Path) -> None:
    result = _run_batches((_batch("below-fold"),), tmp_path)[0]
    assert result["layout"]["focusables"]
    assert result["layout"]["unlabeledControls"]
    assert result["layout"]["tinyTargets"]
    assert result["layout"]["unlabeledControls"][0]["rect"]["y"] >= 1_400


def test_real_config_destructive_actions_use_exact_button_semantics(tmp_path: Path) -> None:
    config = load_config()
    batches = compile_batches(
        config, profile="full", selection=AuditSelection(viewports=("laptop-wide",))
    )
    draft = next(
        batch for batch in batches if (batch.route_id, batch.case.id) == ("release-detail", "draft")
    )
    listing = next(
        batch
        for batch in batches
        if (batch.route_id, batch.case.id) == ("releases-list", "populated")
    )
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
                base_url = f"http://{LOOPBACK_HOST}:{server.server_port}"
                context = _context(browser, listing, base_url)
                page = context.new_page()
                page.goto(_batch_url(base_url, listing), wait_until="domcontentloaded")
                page.locator(listing.case.readiness).first.wait_for(state="visible")
                listing_controls = inventory_controls(page)
                published_nav = next(
                    (
                        row
                        for row in listing_controls
                        if row["tag"] == "a" and "published data" in row["name"].lower()
                    ),
                    None,
                )
                assert published_nav is not None, [
                    row["name"] for row in listing_controls if row["tag"] == "a"
                ]
                status_select = next(row for row in listing_controls if row["tag"] == "select")
                assert not _destructive(published_nav, config.destructive_labels)
                assert not _destructive(status_select, config.destructive_labels)
                page.get_by_role("button", name="Create draft version", exact=True).click()
                page.locator("#entity-dialog[open]").wait_for(state="visible")
                entity_dialog = [row for row in inventory_controls(page) if row["insideOverlay"]]
                dialog_cancel = next(row for row in entity_dialog if row["name"] == "Cancel")
                assert not _destructive(dialog_cancel, config.destructive_labels)
                context.close()

                context = _context(browser, draft, base_url)
                page = context.new_page()
                page.goto(_batch_url(base_url, draft), wait_until="domcontentloaded")
                page.locator(draft.case.readiness).first.wait_for(state="visible")
                delete = next(row for row in inventory_controls(page) if row["name"] == "Delete")
                assert _destructive(delete, config.destructive_labels)
                page.locator(delete["selector"]).click()
                page.locator("#action-dialog[open]").wait_for(state="visible")
                dialog = [row for row in inventory_controls(page) if row["insideOverlay"]]
                cancel = next((row for row in dialog if row["name"] == "Go back"), None)
                confirm = next((row for row in dialog if row["name"] == "Delete version"), None)
                assert cancel is not None and confirm is not None, [row["name"] for row in dialog]
                assert not _destructive(cancel, config.destructive_labels)
                assert _destructive(confirm, config.destructive_labels)
                context.close()
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_every_configured_destructive_action_has_rendered_trigger_and_confirmation(
    tmp_path: Path,
) -> None:
    config = load_config()
    result = _run_batches((_batch("destructive-actions"),), tmp_path)[0]
    controls = result["inventory"]["controls"]
    triggers = [row for row in controls if str(row.get("auditId", "")).startswith("trigger-")]
    confirmations = [row for row in controls if str(row.get("auditId", "")).startswith("confirm-")]

    configured = set(config.destructive_labels)
    assert {row["name"].lower() for row in triggers} == configured
    assert {row["name"].lower() for row in confirmations} == configured
    assert all(_destructive(row, config.destructive_labels) for row in triggers)
    assert all(_destructive(row, config.destructive_labels) for row in confirmations)
    assert all(row["insideOverlay"] is False for row in triggers)
    assert all(row["insideOverlay"] is True for row in confirmations)

    false_positives = [row for row in controls if str(row.get("auditId", "")).startswith("safe-")]
    assert {row["auditId"] for row in false_positives} == {
        "safe-dialog-cancel",
        "safe-published-nav",
        "safe-status-select",
    }
    assert not any(_destructive(row, config.destructive_labels) for row in false_positives)


def test_fixture_server_suppresses_expected_client_disconnect_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    server = UIFixtureServer(0, "slow")
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        connection = socket.create_connection((LOOPBACK_HOST, server.server_port))
        connection.sendall(b"GET /api/shared-health/ai-mode HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
        connection.close()
        time.sleep(1.4)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert "Traceback" not in capsys.readouterr().err


def _run_batches(batches: tuple[AuditBatch, ...], tmp_path: Path) -> list[dict[str, object]]:
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
                return [
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
