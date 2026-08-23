"""Visible-control inventory, fresh-context replay, and interaction state capture."""

# ruff: noqa: E501

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from playwright.sync_api import Browser, Error, Locator, Page

from scripts.ui_audit.models import AuditBatch, Finding

MAX_CONTROLS = 300
MAX_DISCOVERY_DEPTH = 2

INVENTORY_SCRIPT = r"""
(() => {
  const query = [
    'a[href]', 'button', 'summary', 'input:not([type=hidden])', 'select', 'textarea',
    '[contenteditable=true]', '[role=button]', '[role=link]', '[role=tab]', '[role=menuitem]',
    '[role=checkbox]', '[role=radio]', '[role=switch]', '[role=combobox]', '[role=textbox]',
    '[role=spinbutton]', '[tabindex]:not([tabindex="-1"])'
  ].join(',');
  const cssEscape = value => CSS.escape(String(value));
  const text = element => (element.innerText || element.textContent || '').trim()
    .replace(/\s+/g, ' ').slice(0, 180);
  const hidden = element => {
    const box = element.getBoundingClientRect(); const style = getComputedStyle(element);
    const closedDetails = element.closest('details:not([open])');
    return (!!closedDetails && element !== closedDetails.querySelector(':scope > summary'))
      || !!element.closest('[hidden],[inert],[aria-hidden="true"]') || !box.width || !box.height
      || style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0
      || box.right <= 0 || box.left >= document.documentElement.scrollWidth;
  };
  const name = element => {
    const labelledBy = element.getAttribute('aria-labelledby');
    if (labelledBy) return labelledBy.split(/\s+/).map(id => document.getElementById(id)?.textContent || '')
      .join(' ').trim();
    const labels = [...(element.labels || [])].map(text).join(' ').trim();
    return (element.getAttribute('aria-label') || labels || element.getAttribute('alt')
      || element.getAttribute('title') || text(element) || element.value || '').trim();
  };
  const selector = element => {
    const audit = element.getAttribute('data-audit-id');
    if (audit) return `[data-audit-id="${cssEscape(audit)}"]`;
    const testid = element.getAttribute('data-testid');
    if (testid) return `[data-testid="${cssEscape(testid)}"]`;
    if (element.id && document.querySelectorAll(`#${cssEscape(element.id)}`).length === 1) {
      return `#${cssEscape(element.id)}`;
    }
    const parts = []; let current = element;
    while (current && current.nodeType === 1 && current !== document.documentElement && parts.length < 8) {
      let part = current.tagName.toLowerCase();
      const siblings = current.parentElement
        ? [...current.parentElement.children].filter(item => item.tagName === current.tagName) : [];
      if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(current) + 1})`;
      parts.unshift(part); current = current.parentElement;
    }
    return parts.join(' > ');
  };
  const role = element => element.getAttribute('role') || ({
    A:'link', BUTTON:'button', SELECT:'combobox', TEXTAREA:'textbox', SUMMARY:'button'
  }[element.tagName] || (element.tagName === 'INPUT'
    ? ({checkbox:'checkbox',radio:'radio',button:'button',submit:'button',search:'searchbox',
        number:'spinbutton'}[element.type] || 'textbox') : null));
  return [...document.querySelectorAll(query)].filter(element => !hidden(element)).map((element, index) => {
    const box = element.getBoundingClientRect(); const overlay = element.closest('dialog[open],[role=dialog]');
    return {
      index, selector: selector(element), tag: element.tagName.toLowerCase(),
      type: element.getAttribute('type') || '', role: role(element), name: name(element),
      text: text(element), domId: element.id || null, testid: element.getAttribute('data-testid'),
      auditId: element.getAttribute('data-audit-id'),
      href: element.getAttribute('href'), disabled: element.matches(':disabled,[aria-disabled="true"]'),
      insideOverlay: !!overlay, overlayName: overlay ? name(overlay) : null,
      aria: {expanded:element.getAttribute('aria-expanded'), pressed:element.getAttribute('aria-pressed'),
        selected:element.getAttribute('aria-selected'), checked:element.getAttribute('aria-checked'),
        current:element.getAttribute('aria-current')},
      rect:{x:box.x,y:box.y,width:box.width,height:box.height}
    };
  });
})()
"""

SNAPSHOT_SCRIPT = r"""
(selector => {
  const target = document.querySelector(selector);
  const describe = element => element ? {
    tag:element.tagName.toLowerCase(),id:element.id || null,
    name:(element.getAttribute('aria-label') || element.innerText || element.textContent || '').trim()
      .replace(/\s+/g,' ').slice(0,160),
    role:element.getAttribute('role'),
    rect:(() => {const r=element.getBoundingClientRect();return{x:r.x,y:r.y,width:r.width,height:r.height}})()
  } : null;
  return {
    url:location.href, focus:describe(document.activeElement), target: target ? {
      expanded:target.getAttribute('aria-expanded'), pressed:target.getAttribute('aria-pressed'),
      selected:target.getAttribute('aria-selected'), checked:target.getAttribute('aria-checked'),
      current:target.getAttribute('aria-current'), disabled:target.matches(':disabled,[aria-disabled="true"]')
    } : null,
    overlays:[...document.querySelectorAll('dialog[open],[role=dialog]')]
      .filter(element => {const r=element.getBoundingClientRect();return r.width&&r.height})
      .map(describe),
    statuses:[...document.querySelectorAll('[role=alert],[role=status],.toast')]
      .filter(element => {const r=element.getBoundingClientRect();return r.width&&r.height})
      .map(element => (element.innerText || element.textContent || '').trim().replace(/\s+/g,' ').slice(0,300)),
    scroll:{x:scrollX,y:scrollY}, layoutShiftScore:Number(window.__uiAuditLayoutShiftScore || 0)
  };
})
"""


class ContextFactory(Protocol):
    """Create one isolated browser context for a batch."""

    def __call__(self, browser: Browser, batch: AuditBatch, base_url: str) -> Any: ...


class UrlFactory(Protocol):
    """Build the deterministic URL for a batch."""

    def __call__(self, base_url: str, batch: AuditBatch) -> str: ...


class SetupRunner(Protocol):
    """Apply configured deterministic case setup."""

    def __call__(self, page: Page, steps: tuple[dict[str, Any], ...]) -> None: ...


class TelemetryFactory(Protocol):
    """Attach and return fresh-page telemetry."""

    def __call__(self, page: Page, batch: AuditBatch) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ReplayDependencies:
    """Runner callbacks kept explicit to avoid hidden browser/network state."""

    context: ContextFactory
    url: UrlFactory
    setup: SetupRunner
    telemetry: TelemetryFactory


def inventory_controls(
    page: Page, *, setup_path: tuple[dict[str, Any], ...] = ()
) -> list[dict[str, Any]]:
    """Inventory every currently visible control and attach stable identities."""
    rows = page.evaluate(INVENTORY_SCRIPT)
    controls: list[dict[str, Any]] = []
    if not isinstance(rows, list):
        return controls
    for row in rows[:MAX_CONTROLS]:
        if not isinstance(row, dict) or not isinstance(row.get("selector"), str):
            continue
        identity = "|".join(
            (
                row["selector"],
                str(row.get("role", "")),
                str(row.get("name", "")),
                "/".join(str(parent.get("id", "")) for parent in setup_path),
            )
        )
        row["id"] = hashlib.sha256(identity.encode()).hexdigest()[:20]
        row["setupPath"] = [dict(parent) for parent in setup_path]
        controls.append(row)
    return controls


def snapshot_state(page: Page, selector: str) -> dict[str, Any]:
    """Capture the bounded before/after interaction state required by the report."""
    value = page.evaluate(SNAPSHOT_SCRIPT, selector)
    return value if isinstance(value, dict) else {}


def audit_keyboard_traversal(page: Page, controls: list[dict[str, Any]]) -> dict[str, Any]:
    """Exercise forward and reverse focus traversal without assuming a DOM order."""
    if not controls:
        return {"forward": [], "reverse": [], "trapped": False}
    page.evaluate(
        "() => document.activeElement instanceof HTMLElement && document.activeElement.blur()"
    )
    forward: list[dict[str, Any] | None] = []
    limit = min(len(controls) + 2, 80)
    for _ in range(limit):
        page.keyboard.press("Tab")
        forward.append(
            page.evaluate(
                "() => ({tag:document.activeElement?.tagName,id:document.activeElement?.id||null})"
            )
        )
    reverse: list[dict[str, Any] | None] = []
    for _ in range(min(3, limit)):
        page.keyboard.press("Shift+Tab")
        reverse.append(
            page.evaluate(
                "() => ({tag:document.activeElement?.tagName,id:document.activeElement?.id||null})"
            )
        )
    distinct = {str(item) for item in forward if item}
    return {
        "forward": forward,
        "reverse": reverse,
        "trapped": len(distinct) <= 1 and len(controls) > 1,
    }


def replay_controls(
    browser: Browser,
    batch: AuditBatch,
    *,
    base_url: str,
    output: Path,
    roots: list[dict[str, Any]],
    destructive_labels: tuple[str, ...],
    allow_destructive: bool,
    limit: int | None,
    dependencies: ReplayDependencies,
) -> tuple[list[dict[str, Any]], list[Finding]]:
    """Replay every discovered control from a new context, recursively including overlays."""
    queue = [dict(control) for control in roots]
    results: list[dict[str, Any]] = []
    findings: list[Finding] = []
    seen: set[str] = set()
    known_selectors = {str(control.get("selector")) for control in roots}
    maximum = min(MAX_CONTROLS, limit) if limit is not None else MAX_CONTROLS
    while queue and len(results) < maximum:
        control = queue.pop(0)
        control_id = str(control.get("id", ""))
        if not control_id or control_id in seen:
            continue
        seen.add(control_id)
        result, discovered, replay_findings = _replay_one(
            browser,
            batch,
            base_url=base_url,
            output=output,
            control=control,
            destructive_labels=destructive_labels,
            allow_destructive=allow_destructive,
            dependencies=dependencies,
            ordinal=len(results) + 1,
            known_selectors=known_selectors,
        )
        results.append(result)
        findings.extend(replay_findings)
        if len(control.get("setupPath", [])) < MAX_DISCOVERY_DEPTH:
            queue.extend(discovered)
    return results, findings


def _replay_one(
    browser: Browser,
    batch: AuditBatch,
    *,
    base_url: str,
    output: Path,
    control: dict[str, Any],
    destructive_labels: tuple[str, ...],
    allow_destructive: bool,
    dependencies: ReplayDependencies,
    ordinal: int,
    known_selectors: set[str],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[Finding]]:
    started = time.monotonic()
    context = dependencies.context(browser, batch, base_url)
    page = context.new_page()
    telemetry = dependencies.telemetry(page, batch)
    screenshot = (
        output
        / "screenshots"
        / batch.id
        / "interactions"
        / (f"{ordinal:03d}-{control.get('id', 'control')}.png")
    )
    screenshot.parent.mkdir(parents=True, exist_ok=True)
    findings: list[Finding] = []
    discovered: list[dict[str, Any]] = []
    try:
        _goto_with_retry(page, dependencies.url(base_url, batch), telemetry)
        _wait_for_replay_readiness(page, batch)
        dependencies.setup(page, batch.case.setup)
        for parent in control.get("setupPath", []):
            parent_locator = _locator(page, parent)
            parent_locator.click(timeout=5_000)
            page.wait_for_timeout(120)
        locator = _locator(page, control)
        locator.scroll_into_view_if_needed(timeout=5_000)
        if locator.count() == 0 or not locator.first.is_visible():
            return (
                _result(control, "unreachable", started, telemetry, reason="not visible on replay"),
                [],
                [],
            )
        if bool(control.get("disabled")) or locator.first.is_disabled():
            return (
                _result(control, "unreachable", started, telemetry, reason="control is disabled"),
                [],
                [],
            )
        before = snapshot_state(page, str(control["selector"]))
        destructive = _destructive(control, destructive_labels)
        final_confirmation = destructive and bool(control.get("insideOverlay"))
        if final_confirmation and not allow_destructive:
            return (
                _result(
                    control,
                    "skipped-destructive",
                    started,
                    telemetry,
                    before=before,
                    reason="final destructive confirmation is default-off",
                ),
                [],
                [],
            )
        if destructive and not allow_destructive:
            page.route(
                "**/*",
                lambda route: (
                    route.abort("blockedbyclient")
                    if route.request.method not in {"GET", "HEAD", "OPTIONS"}
                    else route.fallback()
                ),
            )
        _activate(locator.first, control)
        page.wait_for_timeout(180)
        after = snapshot_state(page, str(control["selector"]))
        after_controls = inventory_controls(page)
        before_overlays = before.get("overlays", [])
        after_overlays = after.get("overlays", [])
        target_before_raw = before.get("target")
        target_after_raw = after.get("target")
        target_before: dict[str, Any] = (
            target_before_raw if isinstance(target_before_raw, dict) else {}
        )
        target_after: dict[str, Any] = (
            target_after_raw if isinstance(target_after_raw, dict) else {}
        )
        reveals_controls = (
            len(after_overlays) > len(before_overlays)
            or control.get("tag") == "summary"
            or (target_before.get("expanded") != "true" and target_after.get("expanded") == "true")
        )
        new_controls = (
            [
                item
                for item in after_controls
                if item.get("insideOverlay") or str(item.get("selector")) not in known_selectors
            ]
            if reveals_controls
            else []
        )
        child_path = (*control.get("setupPath", []), _setup_parent(control))
        for child in new_controls:
            child["setupPath"] = [dict(item) for item in child_path]
            identity = "|".join(
                (
                    str(child.get("selector")),
                    str(child.get("role")),
                    str(child.get("name")),
                    control["id"],
                )
            )
            child["id"] = hashlib.sha256(identity.encode()).hexdigest()[:20]
            discovered.append(child)
        page.screenshot(path=screenshot, full_page=True, animations="disabled")
        escape: dict[str, Any] | None = None
        if len(after_overlays) > len(before_overlays):
            page.keyboard.press("Escape")
            page.wait_for_timeout(100)
            escape = snapshot_state(page, str(control["selector"]))
            if len(escape.get("overlays", [])) >= len(after_overlays):
                findings.append(
                    Finding(
                        code="overlay-escape-failed",
                        severity=_interaction_severity(batch),
                        message="Escape did not close the newly opened overlay.",
                        gate=batch.viewport.gate,
                        evidence={"control": control},
                    )
                )
            elif not _focus_matches(page, str(control["selector"])):
                findings.append(
                    Finding(
                        code="overlay-focus-not-restored",
                        severity=_interaction_severity(batch),
                        message="Closing the overlay with Escape did not restore focus to its trigger.",
                        gate=batch.viewport.gate,
                        evidence={"control": control},
                    )
                )
        if control.get("insideOverlay") and len(after_overlays) < len(before_overlays):
            setup_path = control.get("setupPath", [])
            parent_selector = setup_path[-1].get("selector") if setup_path else None
            if isinstance(parent_selector, str) and not _focus_matches(page, parent_selector):
                findings.append(
                    Finding(
                        code="dialog-focus-not-restored",
                        severity=_interaction_severity(batch),
                        message="Closing the dialog did not restore focus to its trigger.",
                        gate=batch.viewport.gate,
                        evidence={"control": control},
                    )
                )
        focus = after.get("focus")
        if (
            before.get("url") == after.get("url")
            and not after_overlays
            and isinstance(focus, dict)
            and focus.get("tag") in {None, "body"}
            and control.get("tag") != "a"
        ):
            findings.append(
                Finding(
                    code="focus-lost-after-interaction",
                    severity=_interaction_severity(batch),
                    message="Focus moved to the document body after a non-navigation interaction.",
                    gate=batch.viewport.gate,
                    evidence={"control": control},
                )
            )
        before_scroll = before.get("scroll", {}).get("y", 0)
        after_scroll = after.get("scroll", {}).get("y", 0)
        if (
            before.get("url") == after.get("url")
            and isinstance(before_scroll, (int, float))
            and isinstance(after_scroll, (int, float))
            and abs(after_scroll - before_scroll) > batch.viewport.height
            and control.get("tag") != "a"
        ):
            findings.append(
                Finding(
                    code="unexpected-scroll-jump",
                    severity=_interaction_severity(batch),
                    message="The interaction moved the page by more than one viewport.",
                    gate=batch.viewport.gate,
                    evidence={"before": before_scroll, "after": after_scroll, "control": control},
                )
            )
        shift_delta = float(after.get("layoutShiftScore", 0)) - float(
            before.get("layoutShiftScore", 0)
        )
        if shift_delta > 0.1 and not after_overlays and control.get("tag") != "a":
            findings.append(
                Finding(
                    code="unexpected-layout-shift",
                    severity=_interaction_severity(batch),
                    message="The interaction caused a cumulative layout shift above 0.1.",
                    gate=batch.viewport.gate,
                    evidence={"score": shift_delta, "control": control},
                )
            )
        if destructive and not final_confirmation and not after_overlays:
            findings.append(
                Finding(
                    code="destructive-confirmation-missing",
                    severity="error",
                    message="A destructive trigger did not open a confirmation overlay.",
                    gate=batch.viewport.gate,
                    evidence={"control": control},
                )
            )
        result = _result(
            control,
            "exercised",
            started,
            telemetry,
            before=before,
            after=after,
            escape=escape,
            screenshot=screenshot.relative_to(output).as_posix(),
            discovered=len(discovered),
        )
        return result, discovered, findings
    except Exception as exc:
        return (
            _result(control, "error", started, telemetry, reason=str(exc)),
            [],
            [
                Finding(
                    code="interaction-replay-error",
                    severity=_interaction_severity(batch),
                    message=str(exc),
                    gate=batch.viewport.gate,
                    evidence={"control": control},
                )
            ],
        )
    finally:
        page.close()
        context.close()


def _locator(page: Page, control: dict[str, Any]) -> Locator:
    audit_id = control.get("auditId")
    if isinstance(audit_id, str) and audit_id:
        return page.locator(f'[data-audit-id="{_css_attribute(audit_id)}"]').first
    testid = control.get("testid")
    if isinstance(testid, str) and testid:
        return page.get_by_test_id(testid).first
    dom_id = control.get("domId")
    if isinstance(dom_id, str) and dom_id:
        return page.locator(f'[id="{_css_attribute(dom_id)}"]').first
    return page.locator(str(control["selector"])).first


def _activate(locator: Locator, control: dict[str, Any]) -> None:
    tag, kind, role = control.get("tag"), control.get("type"), control.get("role")
    if tag in {"input", "textarea"} and kind not in {"button", "submit", "checkbox", "radio"}:
        value = "2026-08-23" if kind == "date" else "750000" if kind == "number" else "Audit value"
        locator.fill(value)
    elif tag == "select":
        options = locator.locator("option")
        if options.count() > 1:
            locator.select_option(index=1)
        else:
            locator.focus()
            locator.press("ArrowDown")
    elif kind in {"checkbox", "radio"} or role in {"checkbox", "radio", "switch"}:
        locator.focus()
        locator.press("Space")
        if role == "radio":
            locator.press("ArrowRight")
    elif role in {"tab", "menuitem"}:
        locator.focus()
        locator.press("Enter")
        locator.press("ArrowRight")
    elif tag == "summary":
        locator.focus()
        locator.press("Space")
    else:
        locator.focus()
        locator.press("Enter")


def _destructive(control: dict[str, Any], labels: tuple[str, ...]) -> bool:
    value = f"{control.get('name', '')} {control.get('text', '')}".lower()
    return any(label in value for label in labels)


def _setup_parent(control: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": control.get("id"),
        "selector": control.get("selector"),
        "name": control.get("name"),
        "role": control.get("role"),
    }


def _wait_for_replay_readiness(page: Page, batch: AuditBatch) -> None:
    selector = (
        batch.case.settled_readiness
        if batch.case.capture_phase == "loading-and-settled"
        else batch.case.readiness
    )
    page.locator(selector).first.wait_for(state="visible", timeout=8_000)
    page.wait_for_timeout(max(0, batch.case.settle_ms))


def _interaction_severity(batch: AuditBatch) -> Literal["error", "warning"]:
    return "error" if batch.viewport.gate == "release-critical-full-matrix" else "warning"


def _focus_matches(page: Page, selector: str) -> bool:
    return bool(
        page.locator(selector).first.evaluate("element => document.activeElement === element")
    )


def _css_attribute(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _goto_with_retry(page: Page, url: str, telemetry: dict[str, Any]) -> None:
    for attempt in range(3):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            return
        except Error as exc:
            if "ERR_NO_BUFFER_SPACE" not in str(exc) or attempt == 2:
                raise
            telemetry["requestFailures"] = [
                item
                for item in telemetry.get("requestFailures", [])
                if "ERR_NO_BUFFER_SPACE" not in str(item.get("failure", ""))
            ]
            page.wait_for_timeout(250 * (attempt + 1))


def _result(
    control: dict[str, Any],
    status: str,
    started: float,
    telemetry: dict[str, Any],
    **values: Any,
) -> dict[str, Any]:
    return {
        "control": control,
        "status": status,
        "durationMs": round((time.monotonic() - started) * 1000),
        "telemetry": telemetry,
        **values,
    }
