"""Playwright batch execution for deterministic rendered UI audits."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import Browser, BrowserContext, Page, Route, sync_playwright
from scripts.ui_audit.config import AuditConfig, AuditSelection, compile_batches
from scripts.ui_audit.models import AuditBatch
from scripts.ui_audit.report import load_completed_batch, summary_for, write_reports
from scripts.ui_audit.rules import classify_page
from scripts.ui_smoke import fixture_runtime

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
HELPER_PATH = Path(__file__).with_name("browser_helpers.js")
DEFAULT_OUTPUT_ROOT = REPOSITORY_ROOT / ".propertyscope-runtime" / "ui-audit"
EXPECTED_EXTERNAL_HOSTS = {"tiles.openfreemap.org"}


@dataclass(frozen=True)
class AuditRunResult:
    """Completed audit location and process result."""

    output: Path
    report: dict[str, Any]
    exit_code: int


def source_digest() -> tuple[str, str]:
    """Return git commit and a digest that invalidates resume after local edits."""
    commit = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    diff = subprocess.run(
        ("git", "diff", "--no-ext-diff", "--binary", "HEAD"),
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return commit, hashlib.sha256(diff.encode()).hexdigest()


def run_audit(
    config: AuditConfig,
    *,
    profile: str,
    port: int,
    output: Path | None = None,
    resume: Path | None = None,
    selection: AuditSelection | None = None,
    allow_destructive: bool = False,
) -> AuditRunResult:
    """Own/reuse one loopback fixture host and execute selected batches."""
    selection = selection or AuditSelection()
    commit, dirty_digest = source_digest()
    batches = compile_batches(
        config,
        profile=profile,
        selection=selection,
        source_digest=f"{commit}:{dirty_digest}",
    )
    if not batches:
        raise RuntimeError("UI audit selection produced no batches")
    output_path = resume or output or DEFAULT_OUTPUT_ROOT / _timestamp()
    output_path.mkdir(parents=True, exist_ok=True)
    with fixture_runtime(port, "populated") as base_url:
        if allow_destructive and urlparse(base_url).hostname not in {"127.0.0.1", "localhost"}:
            raise RuntimeError("destructive replay is restricted to the loopback fixture host")
        result = run_batches(
            config,
            batches=batches,
            base_url=base_url,
            output=output_path,
            profile=profile,
            commit=commit,
            dirty_digest=dirty_digest,
            selection=selection,
            allow_destructive=allow_destructive,
        )
    return result


def run_batches(
    config: AuditConfig,
    *,
    batches: tuple[AuditBatch, ...],
    base_url: str,
    output: Path,
    profile: str,
    commit: str,
    dirty_digest: str,
    selection: AuditSelection,
    allow_destructive: bool = False,
) -> AuditRunResult:
    """Execute or resume durable batch files using one browser process."""
    started = datetime.now(UTC)
    batch_results: list[dict[str, Any]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for batch in batches:
                batch_path = output / "batches" / f"{batch.id}.json"
                completed = load_completed_batch(batch_path, batch.fingerprint)
                if completed is not None:
                    completed["resumed"] = True
                    batch_results.append(completed)
                    _write_live_report(
                        config,
                        output,
                        profile,
                        started,
                        commit,
                        dirty_digest,
                        selection,
                        batch_results,
                        len(batches),
                        allow_destructive,
                    )
                    continue
                result = audit_batch(browser, batch, base_url=base_url, output=output)
                from scripts.ui_audit.report import atomic_json

                atomic_json(batch_path, result)
                batch_results.append(result)
                _write_live_report(
                    config,
                    output,
                    profile,
                    started,
                    commit,
                    dirty_digest,
                    selection,
                    batch_results,
                    len(batches),
                    allow_destructive,
                )
        finally:
            browser.close()
    report = _write_live_report(
        config,
        output,
        profile,
        started,
        commit,
        dirty_digest,
        selection,
        batch_results,
        len(batches),
        allow_destructive,
    )
    errors = report["summary"]["findings"]["bySeverity"].get("error", 0)
    failed = report["summary"]["batches"]["failed"]
    return AuditRunResult(output=output, report=report, exit_code=1 if errors or failed else 0)


def audit_batch(
    browser: Browser, batch: AuditBatch, *, base_url: str, output: Path
) -> dict[str, Any]:
    """Capture one deterministic baseline in a fresh isolated context."""
    started = time.monotonic()
    context = _context(browser, batch, base_url)
    page = context.new_page()
    telemetry = _telemetry(page, batch)
    screenshot = output / "screenshots" / batch.id / "baseline.png"
    screenshot.parent.mkdir(parents=True, exist_ok=True)
    try:
        url = _batch_url(base_url, batch)
        response = page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        page.locator(batch.case.readiness).first.wait_for(state="visible", timeout=8_000)
        page.wait_for_timeout(batch.case.settle_ms)
        loading_screenshot: Path | None = None
        if batch.case.capture_phase == "loading-and-settled":
            loading_screenshot = screenshot.with_name("loading.png")
            page.screenshot(path=loading_screenshot, full_page=True, animations="disabled")
            page.wait_for_timeout(1_500)
        _apply_setup(page, batch.case.setup)
        layout = page.evaluate(HELPER_PATH.read_text(encoding="utf-8"))
        page.screenshot(path=screenshot, full_page=True, animations="disabled")
        console_errors = [row for row in telemetry["console"] if row.get("type") == "error"]
        findings = classify_page(
            batch.viewport,
            layout,
            console=console_errors,
            page_errors=telemetry["pageErrors"],
            request_failures=telemetry["requestFailures"],
        )
        status = "failed" if any(item.severity == "error" for item in findings) else "passed"
        return {
            "id": batch.id,
            "fingerprint": batch.fingerprint,
            "workspace": batch.workspace,
            "routeGroup": batch.route_group,
            "routeId": batch.route_id,
            "case": asdict(batch.case),
            "viewport": asdict(batch.viewport),
            "status": status,
            "resumed": False,
            "durationMs": round((time.monotonic() - started) * 1000),
            "baseline": {
                "url": page.url,
                "httpStatus": response.status if response else None,
                "title": page.title(),
                "screenshot": screenshot.relative_to(output).as_posix(),
                "loadingScreenshot": (
                    loading_screenshot.relative_to(output).as_posix()
                    if loading_screenshot is not None
                    else None
                ),
            },
            "inventory": {
                "count": len(layout.get("focusables", [])),
                "controls": layout.get("focusables", []),
            },
            "interactions": [],
            "layout": layout,
            "telemetry": telemetry,
            "findings": [item.as_dict() for item in findings],
        }
    except Exception as exc:
        return {
            "id": batch.id,
            "fingerprint": batch.fingerprint,
            "workspace": batch.workspace,
            "routeGroup": batch.route_group,
            "routeId": batch.route_id,
            "case": asdict(batch.case),
            "viewport": asdict(batch.viewport),
            "status": "failed",
            "resumed": False,
            "durationMs": round((time.monotonic() - started) * 1000),
            "baseline": {},
            "inventory": {"count": 0, "controls": []},
            "interactions": [],
            "telemetry": telemetry,
            "findings": [
                {
                    "code": "batch-exception",
                    "severity": "error",
                    "message": str(exc),
                    "gate": batch.viewport.gate,
                    "evidence": {},
                }
            ],
        }
    finally:
        page.close()
        context.close()


def _context(browser: Browser, batch: AuditBatch, base_url: str) -> BrowserContext:
    viewport = batch.viewport
    context = browser.new_context(
        viewport={"width": viewport.width, "height": viewport.height},
        reduced_motion="reduce",
        color_scheme="light",
        locale="en-AU",
        timezone_id="Australia/Sydney",
        service_workers="block",
    )
    origin = urlparse(base_url).netloc

    def route_request(route: Route) -> None:
        target = urlparse(route.request.url)
        override = _matching_override(batch, route.request.method, route.request.url)
        if override is not None:
            if override.get("abort") is True:
                route.abort("blockedbyclient")
                return
            response = route.fetch()
            body: object
            if "problemCode" in override:
                status_value = int(override.get("status", 503))
                body = {
                    "type": "about:blank",
                    "title": str(override.get("title", "Fixture audit response")),
                    "status": status_value,
                    "detail": str(override.get("detail", "Deterministic UI audit case.")),
                    "code": str(override["problemCode"]),
                    "request_id": "ui-fixture-request-0001",
                }
                override = {**override, "contentType": "application/problem+json"}
            elif "body" in override:
                body = override["body"]
            else:
                try:
                    body = response.json()
                except ValueError:
                    body = response.text()
            if isinstance(body, (dict, list)):
                body = json.loads(json.dumps(body))
                for patch in override.get("patches", []):
                    if isinstance(patch, dict):
                        _json_pointer_set(body, str(patch.get("pointer", "")), patch.get("value"))
            status = override.get("status", response.status)
            content_type = override.get("contentType")
            headers = dict(response.headers)
            if isinstance(content_type, str):
                headers["content-type"] = content_type
            route.fulfill(
                status=int(status),
                headers=headers,
                body=body if isinstance(body, str) else json.dumps(body),
            )
            return
        if target.netloc and target.netloc != origin:
            route.abort("blockedbyclient")
        else:
            route.continue_()

    context.route("**/*", route_request)
    context.add_init_script(
        """
        (() => {
          const style = document.createElement('style');
          style.textContent = [
            '*,*::before,*::after{animation:none!important;',
            'transition:none!important;caret-color:transparent!important}'
          ].join('');
          const install = () => document.documentElement.appendChild(style);
          if (document.documentElement) install();
          else addEventListener('DOMContentLoaded', install, {once:true});
        })();
        """
    )
    return context


def _matching_override(batch: AuditBatch, method: str, url: str) -> dict[str, Any] | None:
    for override in batch.case.overrides:
        expected_method = override.get("method")
        if isinstance(expected_method, str) and method.upper() != expected_method.upper():
            continue
        contains = override.get("urlContains")
        if isinstance(contains, str) and contains not in url:
            continue
        pattern = override.get("urlPattern")
        if isinstance(pattern, str) and re.search(pattern, url) is None:
            continue
        if contains is None and pattern is None:
            continue
        return override
    return None


def _json_pointer_set(document: object, pointer: str, value: object) -> None:
    if not pointer.startswith("/"):
        raise RuntimeError(f"fixture override pointer must start with '/': {pointer!r}")
    parts = [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]
    current = document
    for part in parts[:-1]:
        if isinstance(current, list):
            current = current[int(part)]
        elif isinstance(current, dict):
            current = current[part]
        else:
            raise RuntimeError(f"fixture override pointer cannot traverse {pointer!r}")
    final = parts[-1]
    if isinstance(current, list):
        current[int(final)] = value
    elif isinstance(current, dict):
        current[final] = value
    else:
        raise RuntimeError(f"fixture override pointer cannot set {pointer!r}")


def _apply_setup(page: Page, steps: tuple[dict[str, Any], ...]) -> None:
    for step in steps:
        selector = step.get("selector")
        action = step.get("action")
        if not isinstance(selector, str) or not isinstance(action, str):
            raise RuntimeError("audit setup steps require selector and action")
        locator = page.locator(selector).first
        if action == "fill":
            locator.fill(str(step.get("value", "Audit value")))
        elif action == "click":
            locator.click()
        elif action == "press":
            locator.press(str(step.get("key", "Enter")))
        elif action == "check":
            locator.check()
        elif action == "select":
            locator.select_option(str(step.get("value", "")))
        else:
            raise RuntimeError(f"unsupported audit setup action: {action}")
        page.wait_for_timeout(int(step.get("settleMs", 100)))


def _telemetry(page: Page, batch: AuditBatch) -> dict[str, Any]:
    telemetry: dict[str, Any] = {"console": [], "pageErrors": [], "requestFailures": []}
    page.on(
        "console",
        lambda message: (
            telemetry["console"].append(
                {"type": message.type, "text": message.text, "expected": False}
            )
            if message.type in {"warning", "error"}
            else None
        ),
    )
    page.on("pageerror", lambda error: telemetry["pageErrors"].append(str(error)))

    def request_failed(request: Any) -> None:
        host = urlparse(request.url).hostname
        expected = host in EXPECTED_EXTERNAL_HOSTS or any(
            token in request.url for token in batch.case.expected_request_failures
        )
        telemetry["requestFailures"].append(
            {
                "url": request.url,
                "method": request.method,
                "failure": (request.failure or "request failed"),
                "expected": expected,
            }
        )

    page.on("requestfailed", request_failed)

    def response_received(response: Any) -> None:
        if response.status < 400:
            return
        expected = batch.case.scenario in {"error", "partial", "validation-error"} or any(
            token in response.url for token in batch.case.expected_request_failures
        )
        telemetry["requestFailures"].append(
            {
                "url": response.url,
                "method": response.request.method,
                "failure": f"HTTP {response.status}",
                "expected": expected,
            }
        )

    page.on("response", response_received)
    return telemetry


def _batch_url(base_url: str, batch: AuditBatch) -> str:
    if batch.path.startswith("/"):
        return f"{base_url.rstrip('/')}{batch.path}"
    prefix = "/" if batch.workspace == "shared" else "/features/data-platform/"
    path = batch.path
    if not path.startswith("#"):
        raise RuntimeError(f"audit route path must be a hash route: {path}")
    return f"{base_url.rstrip('/')}{prefix}?scenario={batch.case.scenario}{path}"


def _write_live_report(
    config: AuditConfig,
    output: Path,
    profile: str,
    started: datetime,
    commit: str,
    dirty_digest: str,
    selection: AuditSelection,
    batches: list[dict[str, Any]],
    total_planned: int,
    allow_destructive: bool,
) -> dict[str, Any]:
    finished = datetime.now(UTC)
    deferred = sum(len(route.deferred_states) for route in config.routes)
    report = {
        "schemaVersion": 1,
        "run": {
            "profile": profile,
            "startedAt": started.isoformat(),
            "finishedAt": finished.isoformat(),
            "durationMs": round((finished - started).total_seconds() * 1000),
            "gitSha": commit,
            "dirtyDigest": dirty_digest,
            "configDigest": config.digest,
            "artifactRoot": str(output.resolve()),
            "destructiveMode": allow_destructive,
            "shard": {"index": selection.shard_index, "total": selection.shard_total},
            "selectors": asdict(selection),
        },
        "summary": summary_for(batches, total_planned=total_planned, deferred_states=deferred),
        "batches": batches,
    }
    write_reports(output, report)
    return report


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
