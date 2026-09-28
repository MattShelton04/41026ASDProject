"""Bounded history entries for the Pages index, and which runs the site keeps."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any

from scripts.visual.policy import CASE_ID, IMAGE_NAME, MAX_VIEWS, SHA

RETAINED_PER_KIND = 30
CHANGE_STATUSES = ("changed", "subtle", "incomplete", "base unavailable")
SUMMARY_KEYS = ("changed", "subtle", "unchanged", "incomplete", "baseUnavailable", "total")


def _positive(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _view_map(value: object, accept: Callable[[object], bool]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    kept: dict[str, Any] = {}
    for key, item in value.items():
        if len(kept) >= MAX_VIEWS:
            break
        if isinstance(key, str) and CASE_ID.fullmatch(key) and accept(item):
            kept[key] = item
    return kept


def entry(value: object) -> dict[str, Any] | None:
    """Normalise one ``entry.json`` read back from the Pages branch, or reject it."""
    if not isinstance(value, Mapping):
        return None
    run_id, pr = _positive(value.get("id")), value.get("pr")
    sha = value.get("sha")
    if run_id is None or not isinstance(sha, str) or not SHA.fullmatch(sha):
        return None
    if pr is not None and _positive(pr) is None:
        return None
    created = value.get("created")
    try:
        created_text = datetime.fromisoformat(str(created).replace("Z", "+00:00")).isoformat()
    except ValueError:
        created_text = ""
    raw_summary = value.get("summary")
    if not isinstance(raw_summary, Mapping):
        raw_summary = {}
    summary = {
        key: min(MAX_VIEWS, max(0, count)) if isinstance(count := raw_summary.get(key), int) else 0
        for key in SUMMARY_KEYS
    }
    base = value.get("base")
    views = value.get("views")
    if not isinstance(views, list):
        views = []

    def image(item: object) -> bool:
        return isinstance(item, str) and bool(IMAGE_NAME.fullmatch(item))

    return {
        "id": run_id,
        "sha": sha,
        "base": base if isinstance(base, str) and SHA.fullmatch(base) else None,
        "pr": pr,
        "prTitle": str(value.get("prTitle") or "")[:200],
        "attempt": _positive(value.get("attempt")) or 1,
        "title": str(value.get("title") or "Visual comparison")[:300],
        "created": created_text,
        "summary": summary,
        "views": list(
            dict.fromkeys(v for v in views if isinstance(v, str) and CASE_ID.fullmatch(v))
        )[:MAX_VIEWS],
        "images": _view_map(value.get("images"), image),
        "changes": _view_map(value.get("changes"), lambda item: item in CHANGE_STATUSES),
        "previews": _view_map(value.get("previews"), image),
    }


def retained(entries: Sequence[Mapping[str, Any]], current_id: int) -> list[dict[str, Any]]:
    """Keep the newest runs of each kind, always including the run being published.

    A rerun of an older capture keeps its slot, so this publication never prunes the gallery its
    own comment is about to link.
    """
    ordered = sorted((dict(item) for item in entries), key=lambda item: -int(item["id"]))
    current = next((item for item in ordered if item["id"] == current_id), None)
    kept = [current] if current else []
    counts = {"pr": 0, "main": 0}
    if current:
        counts["pr" if current["pr"] else "main"] += 1
    for item in ordered:
        if item is current:
            continue
        kind = "pr" if item["pr"] else "main"
        if counts[kind] >= RETAINED_PER_KIND:
            continue
        counts[kind] += 1
        kept.append(item)
    return sorted(kept, key=lambda item: -int(item["id"]))
