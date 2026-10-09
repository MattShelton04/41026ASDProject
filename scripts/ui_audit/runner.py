"""Playwright batch execution for deterministic rendered UI audits."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse
from urllib.request import urlopen

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Error,
    Locator,
    Page,
    Route,
    sync_playwright,
)

from scripts.ui_audit.config import AuditConfig, AuditSelection, compile_batches
from scripts.ui_audit.inventory import (
    ReplayDependencies,
    audit_keyboard_traversal,
    inventory_controls,
    replay_controls,
)
from scripts.ui_audit.models import AuditBatch, ExpectedFailure, Finding
from scripts.ui_audit.report import load_completed_batch, summary_for, write_reports
from scripts.ui_audit.rules import classify_page
from scripts.ui_fixtures import FIXTURE_IDENTITY, FIXTURE_REVISION, fixture_response
from scripts.ui_smoke import fixture_runtime

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
HELPER_PATH = Path(__file__).with_name("browser_helpers.js")
DEFAULT_OUTPUT_ROOT = REPOSITORY_ROOT / ".propertyscope-runtime" / "ui-audit"
EXPECTED_ISOLATION_ABORTS = {
    (
        "GET",
        "https://tiles.openfreemap.org/styles/liberty",
        "net::ERR_BLOCKED_BY_CLIENT.Inspector",
    )
}


@dataclass(frozen=True)
class AuditRunResult:
    """Completed audit location and process result."""

    output: Path
    report: dict[str, Any]
    exit_code: int


def source_digest() -> tuple[str, str]:
    """Return git commit and a digest that invalidates resume after local edits."""
    commit = subprocess.run(
        ("git", "rev-parse", "HEAD"),  # noqa: S607 - git is resolved from the developer PATH
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    diff = subprocess.run(
        ("git", "diff", "--no-ext-diff", "--binary", "HEAD"),  # noqa: S607 - git is resolved from the developer PATH
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
    ).stdout
    untracked = subprocess.run(
        ("git", "ls-files", "--others", "--exclude-standard", "-z"),  # noqa: S607 - git is resolved from the developer PATH
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
    ).stdout.split(b"\0")
    digest = hashlib.sha256(diff)
    for raw_path in sorted(path for path in untracked if path):
        relative = Path(raw_path.decode("utf-8", errors="surrogateescape"))
        candidate = (REPOSITORY_ROOT / relative).resolve()
        if REPOSITORY_ROOT.resolve() not in candidate.parents:
            raise RuntimeError(f"untracked source escaped repository root: {relative}")
        digest.update(b"\0untracked\0")
        digest.update(relative.as_posix().encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        digest.update(candidate.read_bytes())
    return commit, digest.hexdigest()


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
        _verify_fixture_identity(base_url)
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
    if allow_destructive:
        host = urlparse(base_url).hostname
        if host not in {"127.0.0.1", "localhost"}:
            raise RuntimeError("destructive replay is restricted to a trusted loopback fixture")
        _verify_fixture_identity(base_url)
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
                        batches,
                        allow_destructive,
                    )
                    continue
                result = audit_batch(
                    browser,
                    batch,
                    base_url=base_url,
                    output=output,
                    destructive_labels=config.destructive_labels,
                    allow_destructive=allow_destructive,
                    interaction_limit=8 if profile == "quick" else None,
                )
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
                    batches,
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
        batches,
        allow_destructive,
    )
    errors = report["summary"]["findings"]["bySeverity"].get("error", 0)
    failed = report["summary"]["batches"]["failed"]
    return AuditRunResult(output=output, report=report, exit_code=1 if errors or failed else 0)


def audit_batch(
    browser: Browser,
    batch: AuditBatch,
    *,
    base_url: str,
    output: Path,
    destructive_labels: tuple[str, ...] = (),
    allow_destructive: bool = False,
    interaction_limit: int | None = None,
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
        _wait_for_readiness(page, batch.case.readiness, batch.case.settle_ms)
        loading_screenshot: Path | None = None
        if batch.case.capture_phase in {"loading", "loading-and-settled"}:
            loading_screenshot = screenshot.with_name("loading.png")
            page.screenshot(path=loading_screenshot, full_page=True, animations="disabled")
        if batch.case.capture_phase == "loading-and-settled":
            _wait_for_readiness(page, batch.case.settled_readiness, batch.case.settle_ms)
        _apply_setup(
            page,
            batch.case.setup,
            expected_failures=batch.case.expected_request_failures,
        )
        layout = page.evaluate(HELPER_PATH.read_text(encoding="utf-8"))
        page.screenshot(path=screenshot, full_page=True, animations="disabled")
        controls = inventory_controls(page)
        keyboard = audit_keyboard_traversal(page, controls)
        console_errors = [row for row in telemetry["console"] if row.get("type") == "error"]
        findings = classify_page(
            batch.viewport,
            layout,
            console=console_errors,
            page_errors=telemetry["pageErrors"],
            request_failures=telemetry["requestFailures"],
        )
        if keyboard["trapped"]:
            findings.append(
                Finding(
                    code="keyboard-trap",
                    severity="error",
                    message="Forward Tab traversal remained on one control.",
                    gate=batch.viewport.gate,
                )
            )
        interactions: list[dict[str, Any]]
        interaction_findings: list[Finding]
        if batch.case.capture_phase == "loading":
            interactions, interaction_findings = [], []
        else:
            interactions, interaction_findings = replay_controls(
                browser,
                batch,
                base_url=base_url,
                output=output,
                roots=controls,
                destructive_labels=destructive_labels,
                allow_destructive=allow_destructive,
                limit=interaction_limit,
                dependencies=ReplayDependencies(
                    context=_context,
                    url=_batch_url,
                    setup=_apply_setup,
                    telemetry=_telemetry,
                ),
            )
        findings.extend(interaction_findings)
        for interaction in interactions:
            interaction_telemetry = interaction.get("telemetry", {})
            interaction_console = [
                row
                for row in interaction_telemetry.get("console", [])
                if isinstance(row, dict) and row.get("type") == "error"
            ]
            findings.extend(
                classify_page(
                    batch.viewport,
                    {},
                    console=interaction_console,
                    page_errors=interaction_telemetry.get("pageErrors", []),
                    request_failures=interaction_telemetry.get("requestFailures", []),
                )
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
                "settledReadiness": batch.case.settled_readiness,
                "settledMarkerVisible": page.locator(
                    batch.case.settled_readiness
                ).first.is_visible(),
                "statusMessages": _visible_status_messages(page),
            },
            "inventory": {
                "count": len(controls),
                "controls": controls,
            },
            "keyboard": keyboard,
            "interactions": interactions,
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
        if target.netloc and target.netloc != origin:
            route.abort("blockedbyclient")
            return
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
        route.continue_()

    context.route("**/*", route_request)
    context.add_init_script(
        """
        (() => {
          window.__uiAuditLayoutShiftScore = 0;
          try {
            new PerformanceObserver(list => {
              for (const entry of list.getEntries()) {
                if (!entry.hadRecentInput) window.__uiAuditLayoutShiftScore += entry.value;
              }
            }).observe({type:'layout-shift', buffered:true});
          } catch {}
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


def _apply_setup(
    page: Page,
    steps: tuple[dict[str, Any], ...],
    *,
    expected_failures: tuple[ExpectedFailure, ...] = (),
) -> None:
    for step in steps:
        action = step.get("action")
        if action == "named-flow":
            _named_flow(
                page,
                str(step.get("name", "")),
                expected_failures=expected_failures,
            )
            continue
        selector = step.get("selector")
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


def _configured_edit_button(
    page: Page,
    *,
    collection: str,
    expected_failures: tuple[ExpectedFailure, ...],
) -> Locator:
    target_pattern = re.compile(rf"/{re.escape(collection)}/([0-9a-fA-F-]+)$")
    target_ids = {
        match.group(1)
        for failure in expected_failures
        if failure.method == "PUT"
        and failure.target
        and (match := target_pattern.search(failure.target))
    }
    if len(target_ids) != 1:
        raise RuntimeError(f"{collection} edit flow requires one exact configured PUT target")
    target_id = target_ids.pop()
    if urlparse(page.url).fragment.split("?", 1)[0] == f"{collection}/{target_id}":
        return page.get_by_role("button", name="Edit", exact=True).first
    row = page.locator("tr").filter(has=page.locator(f'a[href="#{collection}/{target_id}"]')).first
    # The route shell can be ready before its HTMX source fragment arrives.
    # Wait for this exact configured entity, rather than inspecting a transient count.
    row.wait_for(state="visible", timeout=5_000)
    edit = row.get_by_role("button", name=re.compile(r"^Edit(?:\s|$)")).first
    if not edit.is_visible():
        row.get_by_role("button", name=re.compile(r"^More actions for ")).click(timeout=5_000)
    return edit


def _named_flow(
    page: Page,
    name: str,
    *,
    expected_failures: tuple[ExpectedFailure, ...] = (),
) -> None:
    if name in {"edit-job-submit", "edit-source-submit", "edit-source-conflict-submit"}:
        collection = "jobs" if name == "edit-job-submit" else "sources"
        edit = _configured_edit_button(
            page,
            collection=collection,
            expected_failures=expected_failures,
        )
        edit.click(timeout=5_000)
        page.locator("#entity-dialog[open]").wait_for(state="visible")
        if name == "edit-source-conflict-submit":
            save = page.get_by_role("button", name="Save changes", exact=True)
            target = save.get_attribute("hx-put")
            if not target:
                raise RuntimeError("source conflict flow requires an HTMX PUT target")
            form = page.locator("#entity-form").evaluate(
                "form => Object.fromEntries(new FormData(form).entries())"
            )
            current = urlparse(page.url)
            concurrent = page.request.put(
                f"{current.scheme}://{current.netloc}{target}",
                form=form,
                headers={"HX-Request": "true"},
            )
            try:
                if not concurrent.ok:
                    raise RuntimeError(
                        f"source conflict setup failed with HTTP {concurrent.status}"
                    )
            finally:
                concurrent.dispose()
        page.get_by_role("button", name="Save changes", exact=True).click(timeout=5_000)
    elif name == "retry-run-confirm":
        page.locator("#view").get_by_role("button", name="Retry update", exact=True).click(
            timeout=5_000
        )
        page.locator("#action-dialog[open]").wait_for(state="visible")
        page.locator("#action-dialog").get_by_role("button", name="Retry update", exact=True).click(
            timeout=5_000
        )
    elif name == "publish-release-confirm":
        page.get_by_role("button", name="Publish", exact=True).click(timeout=5_000)
        page.locator("#action-dialog[open]").wait_for(state="visible")
        page.get_by_label("Approval note", exact=False).fill("Deterministic audit approval note")
        page.get_by_role("button", name="Publish version", exact=True).click(timeout=5_000)
    elif name == "create-release-submit":
        page.get_by_role("button", name="Create draft version", exact=True).click(timeout=5_000)
        page.locator("#entity-dialog[open]").wait_for(state="visible")
        values = {
            "dataset_id": "property-identities",
            "source_definition_id": "10000000-0000-0000-0000-000000000001",
            "ingestion_run_id": "30000000-0000-0000-0000-000000000001",
            "target_feature": "feature-1",
            "release_version": "2026.08.23-ui-audit",
            "schema_version": "propertyscope.property-snapshot.v1",
            "coverage": '{"state":"NSW","complete":true}',
            "record_count": "1",
            "content_sha256": "d" * 64,
            "artifact_record_id": "50000000-0000-0000-0000-000000000001",
            "manifest": '{"fixture":true}',
        }
        for field, value in values.items():
            page.locator(f'[name="{field}"]').fill(value)
        page.get_by_role("button", name="Save changes", exact=True).click(timeout=5_000)
    elif name == "start-ai-review":
        page.get_by_role("button", name="Send message", exact=True).click(timeout=5_000)
    else:
        raise RuntimeError(f"unknown configured audit setup flow: {name}")
    feedback = (
        page.locator(".ps-ai-chat__turn-error").last
        if name == "start-ai-review"
        else page.locator("#toast:not([hidden])")
    )
    # The audit reports a missing visible recovery state as product debt without turning
    # the otherwise completed request contract into a harness exception.
    with suppress(Error):
        feedback.wait_for(state="visible", timeout=1_500)
    page.wait_for_timeout(100)


def _telemetry(page: Page, batch: AuditBatch) -> dict[str, Any]:
    telemetry: dict[str, Any] = {
        "console": [],
        "pageErrors": [],
        "requestFailures": [],
        "expectedResponses": [],
    }

    def console_message(message: Any) -> None:
        if message.type not in {"warning", "error"}:
            return
        location = message.location if isinstance(message.location, dict) else {}
        row = {
            "type": message.type,
            "text": message.text,
            "location": location,
            "expected": message.text
            == "Failed to load resource: net::ERR_BLOCKED_BY_CLIENT.Inspector",
        }
        telemetry["console"].append(row)
        _correlate_resource_console(row, telemetry["expectedResponses"])

    page.on("console", console_message)
    page.on("pageerror", lambda error: telemetry["pageErrors"].append(str(error)))

    def request_failed(request: Any) -> None:
        failure = request.failure or "request failed"
        expected = (
            request.method,
            request.url,
            failure,
        ) in EXPECTED_ISOLATION_ABORTS or _expected_failure(
            batch, request.method, request.url, abort=True
        )
        telemetry["requestFailures"].append(
            {
                "url": request.url,
                "method": request.method,
                "failure": failure,
                "expected": expected,
            }
        )

    page.on("requestfailed", request_failed)

    def response_received(response: Any) -> None:
        if response.status < 400:
            return
        method = response.request.method
        expected = _expected_failure(
            batch, method, response.url, status=response.status
        ) or _fixture_contract_failure(batch, method, response.url, response.status)
        telemetry["requestFailures"].append(
            {
                "url": response.url,
                "method": response.request.method,
                "failure": f"HTTP {response.status}",
                "expected": expected,
            }
        )
        if expected:
            signature = {"url": response.url, "method": method, "status": response.status}
            telemetry["expectedResponses"].append(signature)
            for message in telemetry["console"]:
                _correlate_resource_console(message, telemetry["expectedResponses"])

    page.on("response", response_received)
    return telemetry


def _normalized_target(url: str) -> str:
    target = urlparse(url)
    query = urlencode(sorted(parse_qsl(target.query, keep_blank_values=True)))
    path = (
        f"{target.netloc}{target.path}"
        if target.hostname not in {None, "127.0.0.1", "localhost"}
        else target.path
    )
    return f"{path}?{query}" if query else path


def _expected_failure(
    batch: AuditBatch,
    method: str,
    url: str,
    *,
    status: int | None = None,
    abort: bool = False,
) -> bool:
    target = _normalized_target(url)
    for expected in batch.case.expected_request_failures:
        if expected.method != method.upper() or expected.abort is not abort:
            continue
        if status is not None and status not in expected.statuses:
            continue
        if expected.target == target:
            return True
        if expected.target_pattern is not None and re.fullmatch(expected.target_pattern, target):
            return True
    return False


def _fixture_contract_failure(batch: AuditBatch, method: str, url: str, status: int) -> bool:
    """Recognise only the exact response prescribed by a selected failure scenario."""
    if batch.case.scenario not in {"error", "partial", "validation-error"}:
        return False
    target = urlparse(url)
    if target.hostname not in {"127.0.0.1", "localhost"}:
        return False
    known_route = fixture_response(method, target.path, target.query, "populated")
    if int(known_route.status) >= 400:
        return False
    expected = fixture_response(method, target.path, target.query, batch.case.scenario)
    return int(expected.status) == status and status >= 400


_RESOURCE_STATUS_ERROR = re.compile(
    r"^Failed to load resource: the server responded with a status of (\d{3})(?: \([^)]*\))?\.?$"
)


def _correlate_resource_console(
    message: dict[str, Any], expected_responses: list[dict[str, Any]]
) -> None:
    """Mark only Chromium resource errors tied to an exact expected HTTP response."""
    match = _RESOURCE_STATUS_ERROR.fullmatch(str(message.get("text", "")))
    location = message.get("location")
    if match is None or not isinstance(location, dict):
        return
    url = location.get("url")
    status = int(match.group(1))
    for response in expected_responses:
        if response.get("url") == url and response.get("status") == status:
            message["expected"] = True
            message["expectedResponse"] = dict(response)
            return


def _visible_status_messages(page: Page) -> list[str]:
    rows = page.locator(
        '[role="alert"],[role="status"],#toast:not([hidden]),.toast:not([hidden]),'
        ".notice.warning,.notice.negative"
    ).evaluate_all(
        """elements => elements.filter(element => {
          const box = element.getBoundingClientRect(); const style = getComputedStyle(element);
          return box.width && box.height && style.display !== 'none'
            && style.visibility !== 'hidden';
        }).map(element => (element.innerText || element.textContent || '').trim()
          .replace(/\\s+/g, ' ').slice(0, 500))"""
    )
    return [row for row in rows if isinstance(row, str) and row]


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
    planned_batches: tuple[AuditBatch, ...],
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
        "summary": summary_for(
            batches,
            planned_batches=planned_batches,
            config=config,
            deferred_states=deferred,
        ),
        "batches": batches,
    }
    write_reports(output, report)
    return report


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _wait_for_readiness(page: Page, selector: str, settle_ms: int) -> None:
    page.locator(selector).first.wait_for(state="visible", timeout=8_000)
    page.wait_for_timeout(max(0, settle_ms))


def _verify_fixture_identity(base_url: str) -> None:
    """Refuse to reuse an arbitrary listener that merely resembles the fixture."""
    with urlopen(f"{base_url}/__ui-fixture__/ready", timeout=1) as response:  # noqa: S310 - loopback fixture URL
        payload = json.load(response)
    if (
        not isinstance(payload, dict)
        or payload.get("identity") != FIXTURE_IDENTITY
        or payload.get("revision") != FIXTURE_REVISION
    ):
        raise RuntimeError("UI audit requires the current trusted loopback fixture revision")
