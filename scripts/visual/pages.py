"""Lay out a published comparison inside a checked-out ``gh-pages`` tree.

    <site>/index.html                    landing page
    <site>/visual/index.html             history of retained runs
    <site>/visual/runs/<run id>/         one gallery, its entry.json and images.json
    <site>/visual/img/<sha256>.png       content-addressed images shared by every run

Only retained runs' images survive, so the branch stays bounded however many runs are published.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.visual import history
from scripts.visual.gallery import render_history, render_landing
from scripts.visual.policy import IMAGE_NAME, MAX_JSON_BYTES
from scripts.visual.report import Report, write_report_pages

ROOT = "visual"


def run_entry(
    report: Report,
    *,
    run_id: int,
    attempt: int,
    title: str,
    pr: int | None,
    pr_title: str,
    created: datetime | None = None,
) -> dict[str, Any]:
    """The history record for one published run."""
    rows = report.rows
    return {
        "id": run_id,
        "sha": report.metadata.get("headSha"),
        "base": report.metadata.get("baseSha"),
        "pr": pr,
        "prTitle": pr_title,
        "attempt": attempt,
        "title": title,
        "created": (created or datetime.now(UTC)).isoformat(timespec="seconds"),
        "summary": report.summary,
        "views": [row["id"] for row in rows],
        "images": {row["id"]: row["headImage"] for row in rows if row.get("headImage")},
        "changes": {row["id"]: row["change"] for row in rows if row["change"] != "unchanged"},
        "previews": {
            row["id"]: row["review"]["preview"]
            for row in rows
            if (row.get("review") or {}).get("preview")
        },
    }


def _read_json(path: Path) -> object:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if len(raw) > MAX_JSON_BYTES:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def publish_run(
    site: Path,
    *,
    report: Report,
    report_dir: Path,
    entry: Mapping[str, Any],
    title: str,
    repo: str | None,
) -> list[dict[str, Any]]:
    """Add one run to the site, prune old runs and unreferenced images, and rebuild the indexes.

    Returns the retained history entries, newest first.
    """
    visual = site / ROOT
    images, runs = visual / "img", visual / "runs"
    images.mkdir(parents=True, exist_ok=True)
    runs.mkdir(parents=True, exist_ok=True)
    for name in report.files:
        if IMAGE_NAME.fullmatch(name) and not (images / name).exists():
            shutil.copyfile(report_dir / "img" / name, images / name)

    run_id = int(entry["id"])
    target = runs / str(run_id)
    if target.exists():
        shutil.rmtree(target)
    write_report_pages(
        output=target,
        title=title,
        rows=report.rows,
        summary=report.summary,
        metadata=report.metadata,
        image_root="../../img/",
        history_url="../../",
    )
    (target / "entry.json").write_text(json.dumps(dict(entry), indent=2) + "\n", encoding="utf-8")
    (target / "images.json").write_text(json.dumps(report.files) + "\n", encoding="utf-8")

    entries = []
    for directory in runs.iterdir():
        normalised = (
            history.entry(_read_json(directory / "entry.json")) if directory.is_dir() else None
        )
        if normalised is None or str(normalised["id"]) != directory.name:
            _remove(directory)
            continue
        entries.append(normalised)
    kept = history.retained(entries, run_id)
    kept_ids = {str(item["id"]) for item in kept}
    for directory in runs.iterdir():
        if directory.name not in kept_ids:
            _remove(directory)

    referenced: set[str] = set()
    for item in kept:
        names = _read_json(runs / str(item["id"]) / "images.json")
        if isinstance(names, list):
            referenced.update(
                name for name in names if isinstance(name, str) and IMAGE_NAME.fullmatch(name)
            )
        referenced.update(item["images"].values())
        referenced.update(item["previews"].values())
    for image in images.iterdir():
        if image.name not in referenced:
            _remove(image)

    (visual / "index.html").write_text(render_history(kept, repo=repo), encoding="utf-8")
    (site / "index.html").write_text(render_landing(repo=repo), encoding="utf-8")
    (site / ".nojekyll").write_text("", encoding="utf-8")
    return kept


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)
