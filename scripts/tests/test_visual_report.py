"""Comparison reports, galleries, Pages layout and pull request comments for visual regression."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from scripts.visual import comment, history, pages
from scripts.visual import report as visual_report
from scripts.visual.gallery import render_gallery, render_history, script_json
from scripts.visual.pngsafe import encode_png
from scripts.visual.policy import VIEWPORT_WIDTH
from scripts.visual.report import build_report

BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40


def _png(height: int = 400, mark: bool = False) -> bytes:
    image = np.zeros((height, VIEWPORT_WIDTH, 4), dtype=np.uint8)
    image[..., :3] = (245, 244, 238)
    image[..., 3] = 255
    if mark:
        image[50:90, 100:300, :3] = (230, 111, 81)
    return encode_png(image)


def _side(
    directory: Path, revision: str, sha: str, cases: dict[str, bytes | None], **extra: Any
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    records = []
    for case_id, data in cases.items():
        records.append(
            {
                "id": case_id,
                "status": "captured" if data else "failed",
                "path": "/features/data-platform/#overview",
                "state": "data overview",
                "errors": [] if data else ["timed out"],
                **extra,
            }
        )
        if data:
            (directory / f"{case_id}.png").write_bytes(data)
    manifest = {
        "schema": 1,
        "revision": revision,
        "provider": "fixture",
        "revisionSha": sha,
        "cases": records,
    }
    (directory / "capture-fixture.json").write_text(json.dumps(manifest))
    return directory


@pytest.fixture
def built(tmp_path: Path) -> tuple[Path, Any]:
    base = _side(
        tmp_path / "base",
        "base",
        BASE_SHA,
        {"shared-home": _png(), "f1-overview": _png(), "f1-runs": _png()},
    )
    head = _side(
        tmp_path / "head",
        "head",
        HEAD_SHA,
        {
            "shared-home": _png(),
            "f1-overview": _png(mark=True),
            "f1-runs": _png(mark=True),
            "f1-new-view": _png(),
            "f1-sources": None,
        },
    )
    output = tmp_path / "report"
    report = build_report(
        base_dir=base,
        head_dir=head,
        output=output,
        title="PR #7: <b>Title</b>",
        metadata={"expectedHeadSha": HEAD_SHA, "runUrl": "https://github.com/o/r/actions/runs/1"},
    )
    return output, report


def test_report_classifies_each_view_and_groups_identical_changes(built: tuple[Path, Any]) -> None:
    output, report = built
    changes = {row["id"]: row["change"] for row in report.rows}
    assert changes == {
        "shared-home": "unchanged",
        "f1-overview": "changed",
        "f1-runs": "changed",
        "f1-sources": "incomplete",
        "f1-new-view": "base unavailable",
    }
    assert report.summary == {
        "changed": 2,
        "subtle": 0,
        "unchanged": 1,
        "incomplete": 1,
        "baseUnavailable": 1,
        "total": 5,
    }
    overview = next(row for row in report.rows if row["id"] == "f1-overview")
    runs = next(row for row in report.rows if row["id"] == "f1-runs")
    assert overview["review"]["sharedWith"] == ["f1-runs"]
    assert runs["review"]["sameAs"] == "f1-overview"
    assert overview["section"] == "feature-1"
    for name in report.files:
        assert (output / "img" / name).is_file()
    machine = json.loads((output / "changes.json").read_text())
    assert machine["headSha"] == HEAD_SHA
    assert machine["views"][1]["areas"]


def test_report_rejects_mismatched_or_self_comparisons(tmp_path: Path) -> None:
    base = _side(tmp_path / "base", "base", BASE_SHA, {"shared-home": _png()})
    head = _side(tmp_path / "head", "head", BASE_SHA, {"shared-home": _png()})
    with pytest.raises(ValueError, match="against itself"):
        build_report(base_dir=base, head_dir=head, output=tmp_path / "out")
    other = _side(tmp_path / "other", "head", HEAD_SHA, {"shared-home": _png()})
    with pytest.raises(ValueError, match="does not match"):
        build_report(
            base_dir=base,
            head_dir=other,
            output=tmp_path / "out",
            metadata={"expectedHeadSha": "c" * 40},
        )
    with pytest.raises(ValueError, match="different revision"):
        build_report(base_dir=other, head_dir=other, output=tmp_path / "out")


def test_report_marks_rejected_screenshots_incomplete(tmp_path: Path) -> None:
    base = _side(tmp_path / "base", "base", BASE_SHA, {"shared-home": _png()})
    head = _side(tmp_path / "head", "head", HEAD_SHA, {"shared-home": _png()})
    (head / "shared-home.png").write_bytes(b"\x89PNG\r\n\x1a\nnot really")
    report = build_report(base_dir=base, head_dir=head, output=tmp_path / "out")
    row = report.rows[0]
    assert row["change"] == "incomplete"
    assert any("rejected" in error for error in row["head"]["errors"])


def test_gallery_escapes_artifact_text_and_pins_scripts_by_hash(built: tuple[Path, Any]) -> None:
    output, _ = built
    page = (output / "index.html").read_text(encoding="utf-8")
    assert "<b>Title</b>" not in page
    assert "PR #7: &lt;b&gt;Title&lt;/b&gt;" in page
    policy = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', page)
    assert policy is not None
    assert "default-src &#x27;none&#x27;" in policy.group(1)
    assert "script-src &#x27;sha256-" in policy.group(1)
    assert "unsafe-inline" not in page
    assert page.count("<script") == 2


def test_script_json_cannot_close_its_element() -> None:
    text = script_json({"title": "</script><script>alert(1)</script>\N{LINE SEPARATOR}"})
    assert "</" not in text
    assert "\N{LINE SEPARATOR}" not in text
    assert json.loads(text)["title"].startswith("</script>")


def test_gallery_drops_unsafe_run_links() -> None:
    page = render_gallery(
        title="t",
        rows=[],
        summary={},
        metadata={"runUrl": "javascript:alert(1)"},
    )
    assert "javascript:" not in page


def _entry(run_id: int, pr: int | None) -> dict[str, Any]:
    return {
        "id": run_id,
        "sha": HEAD_SHA,
        "pr": pr,
        "created": "2026-09-01T00:00:00+00:00",
        "summary": {"changed": 1},
        "views": ["shared-home", "../escape"],
        "images": {"shared-home": "f" * 64 + ".png", "bad id": "x.png"},
        "changes": {"shared-home": "changed", "f1-runs": "exploded"},
    }


def test_history_entries_are_normalised_and_bounded() -> None:
    normalised = history.entry(_entry(12, 3))
    assert normalised is not None
    assert normalised["views"] == ["shared-home"]
    assert normalised["images"] == {"shared-home": "f" * 64 + ".png"}
    assert normalised["changes"] == {"shared-home": "changed"}
    assert history.entry({**_entry(12, 3), "sha": "nope"}) is None
    assert history.entry({**_entry(12, 3), "pr": -1}) is None


def test_retention_keeps_newest_of_each_kind_and_the_current_run() -> None:
    entries = [history.entry(_entry(run, 1 if run % 2 else None)) for run in range(1, 101)]
    kept = history.retained([item for item in entries if item], current_id=1)
    ids = [item["id"] for item in kept]
    assert 1 in ids
    assert sum(1 for item in kept if item["pr"]) == history.RETAINED_PER_KIND
    assert sum(1 for item in kept if not item["pr"]) == history.RETAINED_PER_KIND
    assert ids == sorted(ids, reverse=True)


def test_history_page_embeds_entries_as_inert_data() -> None:
    normalised = history.entry({**_entry(5, 2), "prTitle": "</script><img src=x onerror=alert(1)>"})
    assert normalised is not None
    page = render_history([normalised], repo="owner/repo")
    assert "<img src=x" not in page


def test_pages_layout_prunes_runs_and_unreferenced_images(
    tmp_path: Path, built: tuple[Path, Any]
) -> None:
    output, report = built
    site = tmp_path / "site"
    stale = site / "visual" / "img" / ("0" * 64 + ".png")
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"old")
    junk = site / "visual" / "runs" / "not-a-run"
    junk.mkdir(parents=True)
    entry = pages.run_entry(report, run_id=42, attempt=1, title="t", pr=7, pr_title="PR")
    kept = pages.publish_run(
        site, report=report, report_dir=output, entry=entry, title="t", repo="owner/repo"
    )
    assert [item["id"] for item in kept] == [42]
    assert not stale.exists()
    assert not junk.exists()
    run = site / "visual" / "runs" / "42"
    gallery = (run / "index.html").read_text(encoding="utf-8")
    assert "../../img/" in gallery
    for name in report.files:
        assert (site / "visual" / "img" / name).is_file()
    assert (site / "visual" / "index.html").is_file()
    assert (site / "index.html").is_file()
    assert (site / ".nojekyll").is_file()
    assert entry["previews"]["f1-overview"] in report.files


def test_comment_summarises_sections_and_escapes_text(built: tuple[Path, Any]) -> None:
    _, report = built
    rows = [dict(row) for row in report.rows]
    rows[0] = {**rows[0], "state": "<img src=x onerror=alert(1)> [link](javascript:x)"}
    body = comment.render(
        rows,
        report.summary,
        site="https://owner.github.io/repo/visual/",
        run_id=42,
        head_sha=HEAD_SHA,
        base_sha=BASE_SHA,
        attempt=1,
        run_url="https://github.com/owner/repo/actions/runs/42",
    )
    assert body.startswith(comment.MARKER)
    assert "2 view(s) changed" in body
    assert "| Feature 1 · Property data | 2 |" in body
    assert "https://owner.github.io/repo/visual/runs/42/#section=feature-1&view=f1-overview" in body
    assert "<img src=x" not in body
    assert "](javascript:" not in body
    assert "1 view(s) with limitations" not in body
    assert "2 view(s) with limitations" in body
    assert len(body) < comment.MAX_BODY


def test_comment_run_stamps_prevent_older_reruns_overwriting() -> None:
    stamped = comment.stamp(f"{comment.MARKER}\nbody", run_id=10, attempt=2)
    assert comment.is_newer(stamped, run_id=10, attempt=1)
    assert comment.is_newer(stamped, run_id=9, attempt=5)
    assert not comment.is_newer(stamped, run_id=10, attempt=3)
    assert not comment.is_newer(stamped, run_id=11, attempt=1)
    assert not comment.is_newer("no stamp", run_id=1, attempt=1)


def test_ci_report_exposes_missing_provider_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts.visual.cases import VisualCase

    monkeypatch.setattr(
        visual_report,
        "CASES",
        (
            VisualCase("shared-home", "fixture", "/", "home"),
            VisualCase("f2-cases", "stack", "/features/market/", "cases"),
        ),
    )
    base = _side(tmp_path / "base", "base", BASE_SHA, {"shared-home": _png()})
    head = _side(tmp_path / "head", "head", HEAD_SHA, {"shared-home": _png()})
    report = build_report(
        base_dir=base,
        head_dir=head,
        output=tmp_path / "out",
        expected_providers=("fixture", "stack"),
    )
    assert report.summary["total"] == 2
    assert report.summary["incomplete"] == 1
    stack = report.rows[1]
    assert stack["change"] == "incomplete"
    assert "stack capture artifact missing" in stack["head"]["errors"][0]
    assert "stack capture artifact missing" in stack["base"]["errors"][0]
    changes = json.loads((tmp_path / "out" / "changes.json").read_text())
    assert changes["views"][1]["limitations"][1].startswith("head: stack capture artifact missing")


def test_ci_report_exposes_views_omitted_from_head_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts.visual.cases import VisualCase

    monkeypatch.setattr(
        visual_report, "CASES", (VisualCase("shared-home", "fixture", "/", "home"),)
    )
    base = _side(tmp_path / "base", "base", BASE_SHA, {"shared-home": _png()})
    head = _side(tmp_path / "head", "head", HEAD_SHA, {})
    report = build_report(
        base_dir=base,
        head_dir=head,
        output=tmp_path / "out",
        expected_providers=("fixture",),
    )
    assert report.rows[0]["change"] == "incomplete"
    assert report.rows[0]["head"]["errors"] == ["view missing from the capture manifest"]


def test_local_report_retains_its_selected_case_scope(tmp_path: Path) -> None:
    base = _side(tmp_path / "base", "base", BASE_SHA, {"shared-home": _png()})
    head = _side(tmp_path / "head", "head", HEAD_SHA, {"shared-home": _png()})
    report = build_report(base_dir=base, head_dir=head, output=tmp_path / "out")
    assert report.summary["total"] == 1
    assert report.summary["incomplete"] == 0
