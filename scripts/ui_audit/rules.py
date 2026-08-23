"""Classify browser telemetry and DOM measurements under viewport-specific gates."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from scripts.ui_audit.models import Finding, Viewport


def _severity(viewport: Viewport, *, core: bool = False) -> str:
    if viewport.gate == "release-critical-full-matrix" or core:
        return "error"
    return "warning"


def _finding(
    code: str,
    message: str,
    viewport: Viewport,
    *,
    core: bool = False,
    evidence: dict[str, Any] | None = None,
) -> Finding:
    return Finding(
        code=code,
        severity=_severity(viewport, core=core),  # type: ignore[arg-type]
        message=message,
        gate=viewport.gate,
        evidence=evidence or {},
    )


def classify_page(
    viewport: Viewport,
    layout: dict[str, Any],
    *,
    console: Iterable[dict[str, Any]] = (),
    page_errors: Iterable[str] = (),
    request_failures: Iterable[dict[str, Any]] = (),
) -> list[Finding]:
    """Return deterministic findings without promoting narrow dense-table diagnostics."""
    findings: list[Finding] = []
    document = layout.get("document", {})
    if isinstance(document, dict) and document.get("horizontalOverflow") is True:
        findings.append(
            _finding(
                "page-horizontal-overflow",
                "The document is wider than the viewport.",
                viewport,
                core=True,
                evidence=document,
            )
        )
    for item in _dict_rows(layout.get("outside")):
        findings.append(
            _finding(
                "element-outside-viewport",
                "A rendered element extends outside the viewport without a scroll container.",
                viewport,
                core=bool(item.get("core")),
                evidence=item,
            )
        )
    for item in _dict_rows(layout.get("containedScroll")):
        findings.append(
            Finding(
                code="contained-horizontal-scroll",
                severity="info",
                message="Content extends inside an intentional horizontal scroll container.",
                gate=viewport.gate,
                evidence=item,
            )
        )
    for item in _dict_rows(layout.get("clipped")):
        findings.append(
            _finding(
                "clipped-content",
                "Rendered content is clipped by its own or an ancestor overflow boundary.",
                viewport,
                core=bool(item.get("core")),
                evidence=item,
            )
        )
    if viewport.id in {"tablet-portrait", "mobile"}:
        for item in _dict_rows(layout.get("tinyTargets")):
            findings.append(
                _finding(
                    "touch-target-under-44px",
                    "An interactive target is smaller than 44 by 44 CSS pixels.",
                    viewport,
                    core=bool(item.get("core")),
                    evidence=item,
                )
            )
    for item in _dict_rows(layout.get("unlabeledControls")):
        findings.append(
            _finding(
                "missing-accessible-name",
                "An interactive control has no accessible name.",
                viewport,
                core=bool(item.get("core")),
                evidence=item,
            )
        )
    for item in _dict_rows(layout.get("unlabeledFields")):
        findings.append(
            _finding(
                "missing-field-label",
                "A form field has no associated or ARIA label.",
                viewport,
                core=bool(item.get("core")),
                evidence=item,
            )
        )
    for duplicate_id in layout.get("duplicateIds", []):
        if isinstance(duplicate_id, str):
            findings.append(
                _finding(
                    "duplicate-id",
                    f"The DOM contains duplicate id {duplicate_id!r}.",
                    viewport,
                    evidence={"id": duplicate_id},
                )
            )
    for message in console:
        if message.get("expected") is True:
            continue
        findings.append(
            _finding(
                "unexpected-console-error",
                str(message.get("text", "Unexpected console error")),
                viewport,
            )
        )
    for error in page_errors:
        findings.append(_finding("unexpected-page-exception", error, viewport, core=True))
    for request in request_failures:
        if request.get("expected") is True:
            findings.append(
                Finding(
                    code="expected-request-failure",
                    severity="info",
                    message=str(request.get("url", "Expected request was blocked")),
                    gate=viewport.gate,
                    evidence=request,
                )
            )
        else:
            findings.append(
                _finding(
                    "unexpected-request-failure",
                    str(request.get("url", "Unexpected request failed")),
                    viewport,
                    evidence=request,
                )
            )
    return findings


def _dict_rows(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
