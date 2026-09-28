"""The sticky pull request comment that summarises one published comparison.

Everything interpolated from captures is escaped, image URLs come only from content-addressed
names, and the body is bounded well under GitHub's 65,536 character limit.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from scripts.visual.policy import IMAGE_NAME, SECTIONS, VIEWPORT_WIDTH, section_label

MARKER = "<!-- propertyscope-visual-report -->"
MAX_BODY = 60_000
_SPECIAL = frozenset("&<>\"'\\`*_[]()|#!~")
EXPANDED = 3
LISTED = 40


def _text(value: object) -> str:
    """Escape for both Markdown and inline HTML."""
    return "".join(
        f"&#{ord(character)};"
        if character in _SPECIAL
        else " "
        if character in "\r\n"
        else character
        for character in str(value)
    )


def _image(root: str, name: object) -> str | None:
    return f"{root}img/{name}" if isinstance(name, str) and IMAGE_NAME.fullmatch(name) else None


def _percent(row: Mapping[str, Any]) -> str:
    analysis = (row.get("analyses") or {}).get("0") or {}
    changed, percent = analysis.get("changed"), analysis.get("percent")
    if not isinstance(changed, int):
        return ""
    return (
        f"{changed:,} px ({percent:.3f}%)"
        if isinstance(percent, (int, float))
        else f"{changed:,} px"
    )


def _height(row: Mapping[str, Any]) -> str:
    before, after = row.get("baseHeight"), row.get("headHeight")
    if isinstance(before, int) and isinstance(after, int) and before != after:
        return f" · page height {before:,} → {after:,} px"
    return ""


def _section_table(rows: Sequence[Mapping[str, Any]]) -> str:
    lines = ["| Area | Changed | Subtle | Unchanged | Limited |", "|---|---:|---:|---:|---:|"]
    for section_id, label in SECTIONS:
        inside = [row for row in rows if row["section"] == section_id]
        if not inside:
            continue
        count = {
            status: sum(row["change"] == status for row in inside)
            for status in ("changed", "subtle", "unchanged")
        }
        limited = sum(row["change"] in ("incomplete", "base unavailable") for row in inside)
        lines.append(
            f"| {_text(label)} | {count['changed'] or '·'} | {count['subtle'] or '·'} | "
            f"{count['unchanged'] or '·'} | {limited or '·'} |"
        )
    return "\n".join(lines)


def _expanded(row: Mapping[str, Any], site: str, gallery: str) -> str:
    review = row.get("review") or {}
    link = f"{gallery}#section={row['section']}&view={row['id']}&mode=difference"
    parts = [
        f"#### [{_text(row['id'])}]({link})",
        f"{_text(row.get('state', ''))} · <code>{_text(row.get('path', ''))}</code> · "
        f"{_percent(row)}{_height(row)} · {int(review.get('areaCount') or 0)} changed area(s)",
    ]
    if shared := review.get("sharedWith"):
        parts.append(f"Same changed areas in: {', '.join(_text(item) for item in shared[:8])}")
    if preview := _image(site, review.get("preview")):
        parts.append(
            f'<img src="{preview}" width="{VIEWPORT_WIDTH // 2}" alt="Changed areas highlighted">'
        )
    focus = review.get("focus") or []
    if focus:
        cells = []
        for item in focus[:2]:
            before, after = _image(site, item.get("base")), _image(site, item.get("head"))
            if before and after:
                cells.append(
                    f'<tr><td><img src="{before}" alt="Before, actual size"></td>'
                    f'<td><img src="{after}" alt="After, actual size"></td></tr>'
                )
        if cells:
            table = "<table><tr><th>Before</th><th>After</th></tr>" + "".join(cells) + "</table>"
            parts.append(_details("Actual-size close-ups", table))
    return "\n\n".join(parts)


def _details(summary: str, body: str) -> str:
    return f"<details><summary>{summary}</summary>\n\n{body}\n\n</details>"


def _listing(rows: Sequence[Mapping[str, Any]], gallery: str) -> str:
    items = [
        f"- [{_text(row['id'])}]({gallery}#section={row['section']}&view={row['id']}) · "
        f"{_text(section_label(row['section']))} · {_percent(row)}{_height(row)}"
        for row in rows[:LISTED]
    ]
    if len(rows) > LISTED:
        items.append(f"- … and {len(rows) - LISTED} more in the gallery")
    return "\n".join(items)


def render(
    rows: Sequence[Mapping[str, Any]],
    summary: Mapping[str, int],
    *,
    site: str,
    run_id: int,
    head_sha: str,
    base_sha: str | None,
    attempt: int,
    run_url: str,
) -> str:
    """Render the comment body; ``site`` is the Pages URL of the ``visual/`` directory."""
    gallery = f"{site}runs/{run_id}/"
    changed = [
        row
        for row in rows
        if row["change"] == "changed" and not (row.get("review") or {}).get("sameAs")
    ]
    folded = [
        row
        for row in rows
        if row["change"] == "changed" and (row.get("review") or {}).get("sameAs")
    ]
    subtle = [row for row in rows if row["change"] == "subtle"]
    limited = [row for row in rows if row["change"] in ("incomplete", "base unavailable")]
    if summary.get("changed"):
        verdict = f"**{summary['changed']} view(s) changed** — please review them before merging."
    elif summary.get("incomplete"):
        verdict = "**Some views could not be captured**, so this comparison is incomplete."
    elif summary.get("subtle"):
        verdict = "Only subtle rendering differences — probably anti-aliasing, but worth a glance."
    else:
        verdict = "No visual changes."
    base = f"`{base_sha[:7]}`" if base_sha else "no baseline"
    parts = [
        MARKER,
        "## Visual review",
        f"{verdict} [Open the gallery]({gallery}) · [History]({site})",
        f"Compared {base} → `{head_sha[:7]}` · {summary.get('total', 0)} views · "
        f"attempt {attempt} · [workflow run]({run_url})",
        _section_table(rows),
    ]
    for row in changed[:EXPANDED]:
        parts.append(_expanded(row, site, gallery))
    rest = changed[EXPANDED:] + folded
    if rest:
        parts.append(_details(f"{len(rest)} more changed view(s)", _listing(rest, gallery)))
    if subtle:
        parts.append(_details(f"{len(subtle)} subtle view(s)", _listing(subtle, gallery)))
    if limited:
        lines = []
        for row in limited[:LISTED]:
            reason = (
                "no baseline screenshot" if row["change"] == "base unavailable" else "not captured"
            )
            errors = [
                *((row.get("head") or {}).get("errors") or []),
                *((row.get("base") or {}).get("errors") or []),
            ]
            detail = f": {_text(errors[0][:200])}" if errors else ""
            lines.append(f"- {_text(row['id'])} · {reason}{detail}")
        parts.append(_details(f"{len(limited)} view(s) with limitations", "\n".join(lines)))
    parts.append(
        "<sub>Screenshots use deterministic fixtures and an offline stack at 1440 px wide. "
        "This comment is updated in place on each push.</sub>"
    )
    body = "\n\n".join(parts)
    if len(body) > MAX_BODY:
        body = "\n\n".join(
            [
                *parts[:5],
                f"The full report is too large for a comment. [Open the gallery]({gallery}).",
            ]
        )
    return body


def is_newer(existing: str, run_id: int, attempt: int) -> bool:
    """True when a posted comment already describes a later run than this one."""
    marker = _metadata(existing)
    if marker is None:
        return False
    posted_run, posted_attempt = marker
    return (posted_run, posted_attempt) > (run_id, attempt)


def stamp(body: str, run_id: int, attempt: int) -> str:
    """Record which run a comment describes, so older reruns never overwrite newer results."""
    return body.replace(MARKER, f"{MARKER}\n<!-- run:{run_id}:{attempt} -->", 1)


def _metadata(body: str) -> tuple[int, int] | None:
    start = body.find("<!-- run:")
    if start < 0:
        return None
    fields = body[start + 9 : body.find(" -->", start)].split(":")
    try:
        return int(fields[0]), int(fields[1])
    except (IndexError, ValueError):
        return None
