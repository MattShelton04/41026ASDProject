"""Render the trusted, self-contained pages: a run gallery, the history index and a landing page.

Artifact text reaches these pages only as escaped HTML or as JSON inside a data block that cannot
close its script element. Each page allows only its own stylesheet and scripts by hash.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from string import Template
from typing import Any
from urllib.parse import urlsplit

from scripts.visual.policy import FIXED_TIME, SECTIONS, VIEWPORT_WIDTH

ASSETS = Path(__file__).with_name("gallery")
# The PropertyScope mark from shared/frontend/design-system/brand/propertyscope-mark.svg.
MARK = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" aria-hidden="true" '
    'color="#285442">'
    '<path d="M18 4H4v14M14 28h14V14" fill="none" stroke="currentColor" stroke-width="2.5"/>'
    '<path d="M10 10h12v8h-5v5h-7z" fill="currentColor"/></svg>'
)
FAVICON = "data:image/svg+xml," + MARK.replace('"', "'").replace("#", "%23").replace(
    "<", "%3C"
).replace(">", "%3E")
CAPTURE_SUMMARY = (
    "Real frontends · Shared and Feature 1 on deterministic fixtures · "
    "Features 2\N{EN DASH}5 on an offline stack with seeded data · "
    f"{VIEWPORT_WIDTH}px wide, full page · light theme · clock fixed at {FIXED_TIME[:10]}"
)


def escape(value: object) -> str:
    """Escape text for HTML element content and attribute values."""
    return html.escape(str(value), quote=True)


def script_json(value: object) -> str:
    """Serialise JSON that cannot terminate the surrounding ``<script>`` element."""
    text = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    for character, replacement in (
        ("<", "\\u003c"),
        (">", "\\u003e"),
        ("&", "\\u0026"),
        ("\N{LINE SEPARATOR}", "\\u2028"),
        ("\N{PARAGRAPH SEPARATOR}", "\\u2029"),
    ):
        text = text.replace(character, replacement)
    return text


def safe_http_url(value: object) -> str:
    """Return an http(s) URL without credentials, otherwise an empty string."""
    if not isinstance(value, str):
        return ""
    try:
        parts = urlsplit(value)
    except ValueError:
        return ""
    if parts.scheme not in {"http", "https"} or not parts.netloc or "@" in parts.netloc:
        return ""
    return value


def _sha256(text: str) -> str:
    return base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode("ascii")


def _document(*, title: str, body: str, data: object | None, scripts: Sequence[str]) -> str:
    css = (ASSETS / "gallery.css").read_text(encoding="utf-8")
    code = "\n".join((ASSETS / name).read_text(encoding="utf-8") for name in scripts)
    script_source = f"'sha256-{_sha256(code)}'" if code else "'none'"
    policy = (
        "default-src 'none'; img-src 'self' data:; "
        f"style-src 'sha256-{_sha256(css)}'; script-src {script_source}; "
        "base-uri 'none'; form-action 'none'"
    )
    data_block = (
        f'<script id="report-data" type="application/json">{script_json(data)}</script>'
        if data is not None
        else ""
    )
    code_block = f"<script>{code}</script>" if code else ""
    return (
        '<!doctype html><html lang="en-AU"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<meta http-equiv="Content-Security-Policy" content="{escape(policy)}">'
        '<meta name="referrer" content="no-referrer">'
        f'<title>{escape(title)}</title><link rel="icon" href="{escape(FAVICON)}">'
        f"<style>{css}</style></head><body>{body}{data_block}{code_block}</body></html>"
    )


def _template(name: str, **values: str) -> str:
    """Fill a trusted page body; every value is already escaped or built from trusted markup."""
    return Template((ASSETS / name).read_text(encoding="utf-8")).substitute(values)


def _brand(label: str, href: str = "") -> str:
    inner = f"{MARK}<span><strong>PropertyScope NSW</strong><small>{escape(label)}</small></span>"
    return (
        f'<a class="brand" href="{escape(href)}">{inner}</a>'
        if href
        else f'<div class="brand">{inner}</div>'
    )


def _counts(summary: Mapping[str, int]) -> str:
    limitations = summary.get("incomplete", 0) + summary.get("baseUnavailable", 0)
    return (
        '<div class="counts">'
        f'<span class="pill changed">{summary.get("changed", 0)} changed</span>'
        f'<span class="pill subtle">{summary.get("subtle", 0)} subtle</span>'
        f'<span class="pill unchanged">{summary.get("unchanged", 0)} identical</span>'
        f'<span class="pill incomplete">{limitations} limitations</span></div>'
    )


def _sections() -> list[dict[str, str]]:
    return [{"id": section, "label": label} for section, label in SECTIONS]


def render_gallery(
    *,
    title: str,
    rows: Sequence[Mapping[str, Any]],
    summary: Mapping[str, int],
    metadata: Mapping[str, Any],
    image_root: str = "img/",
    history_url: str | None = None,
) -> str:
    """Render one comparison as a standalone interactive page."""
    run_url = safe_http_url(metadata.get("runUrl"))
    base_sha, head_sha = metadata.get("baseSha"), metadata.get("headSha")
    revisions = ""
    if isinstance(base_sha, str) and isinstance(head_sha, str):
        before, after = escape(base_sha[:8]), escape(head_sha[:8])
        revisions = f" · base <code>{before}</code> → head <code>{after}</code>"
    elif isinstance(head_sha, str):
        revisions = f" · head <code>{escape(head_sha[:8])}</code>"
    links = [f'<a href="{escape(history_url)}">Screenshot history</a>'] if history_url else []
    if run_url:
        links.append(f'<a href="{escape(run_url)}">Capture run</a>')
    links.append('<a href="changes.json">changes.json</a>')
    modes = "".join(
        f'<button type="button" data-mode="{mode}" aria-pressed="false">{label}</button>'
        for mode, label in (
            ("side", "Side by side"),
            ("toggle", "Before / after"),
            ("wipe", "Wipe"),
            ("overlay", "Overlay"),
            ("difference", "Difference"),
        )
    )
    body = _template(
        "report.html",
        brand=_brand("Visual review"),
        title=escape(title),
        capture_summary=escape(CAPTURE_SUMMARY),
        revisions=revisions,
        counts=_counts(summary),
        links="".join(links),
        modes=modes,
    )
    data = {
        "schema": 1,
        "title": title,
        "rows": list(rows),
        "sections": _sections(),
        "summary": dict(summary),
        "metadata": {
            "imageRoot": image_root if image_root in ("img/", "../../img/") else "img/",
            "runUrl": run_url,
            "baseSha": base_sha,
            "headSha": head_sha,
        },
    }
    return _document(title=title, body=body, data=data, scripts=("gallery.js",))


def render_history(entries: Sequence[Mapping[str, Any]], *, repo: str | None) -> str:
    """Render the history index for retained runs (already normalised by ``history.entry``)."""
    tabs = "".join(
        f'<button type="button" role="tab" id="tab-{tab}" data-tab="{tab}" '
        f'aria-controls="panel-{tab}" '
        f'aria-selected="false">{label}</button>'
        for tab, label in (
            ("prs", "Pull requests"),
            ("main", "Main"),
            ("timeline", "View timeline"),
        )
    )
    body = _template(
        "history.html",
        brand=_brand("Visual review", "../"),
        capture_summary=escape(CAPTURE_SUMMARY),
        tabs=tabs,
    )
    data = {
        "entries": list(entries),
        "sections": _sections(),
        "repo": repo if isinstance(repo, str) and repo.count("/") == 1 else None,
    }
    return _document(
        title="PropertyScope visual history", body=body, data=data, scripts=("history.js",)
    )


def render_landing(*, repo: str | None) -> str:
    """Render the Pages root: what the site is and where the history lives."""
    source = f"https://github.com/{repo}" if repo and repo.count("/") == 1 else ""
    link = f'<a href="{escape(source)}">{escape(repo)}</a>' if source else "this repository"
    body = _template(
        "landing.html",
        brand=_brand("Visual review"),
        capture_summary=escape(CAPTURE_SUMMARY),
        link=link,
    )
    return _document(title="PropertyScope visual review", body=body, data=None, scripts=())
