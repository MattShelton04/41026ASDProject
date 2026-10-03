"""Protect report navigation, reproducibility, drift checks and draft handling."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from pypdf import PdfReader
from reportlab.platypus import Paragraph, Table
from scripts import build_release0_report
from scripts import report_pdf as engine

BASELINE = "7d5350d19023fb1e978e85127a72e3500a1556f3"
SPEC = build_release0_report.SPEC


def _spec_for(tmp_path: Path, pairs: dict[str, str]) -> engine.ReportSpec:
    return replace(SPEC, asset_dir=tmp_path, diagram_dir=tmp_path, diagram_pairs=pairs)


def _write(tmp_path: Path, text: str) -> Path:
    source = tmp_path / "report.md"
    source.write_text(text, encoding="utf-8")
    return source


def test_evidence_links_preserve_pinned_ref_and_section() -> None:
    source = engine.REPORT_DIR / "release-0-technical-report.md"
    url = engine.resolve_link(
        "../architecture/registered-feature-scope.md#document-control", source, BASELINE
    )
    assert url.endswith(
        f"/{BASELINE}/docs/architecture/registered-feature-scope.md#document-control"
    )
    assert (
        engine.resolve_link("https://example.org/evidence#run", source, BASELINE)
        == "https://example.org/evidence#run"
    )


def test_headings_keep_visual_and_bookmark_hierarchy(tmp_path: Path) -> None:
    source = _write(tmp_path, "# Report\n\n## Chapter\n\n### Section\n\n#### Feature\n")
    headings = [
        item
        for item in engine.parse_markdown(source, BASELINE, SPEC)
        if isinstance(item, Paragraph)
    ]
    assert [item.style.name for item in headings] == [
        "ReportTitle",
        "HeadingOne",
        "HeadingTwo",
        "HeadingThree",
    ]
    assert [getattr(item, "_heading_level", None) for item in headings] == [None, 0, 1, 2]


@pytest.mark.parametrize("ordered", [False, True])
@pytest.mark.parametrize("indent", ["  ", ""])
def test_wrapped_list_items_keep_their_text_and_rendered_order(
    tmp_path: Path, ordered: bool, indent: str
) -> None:
    first, second = ("1.", "2.") if ordered else ("-", "-")
    source = _write(
        tmp_path,
        "# Report\n\n## 8 Limitations\n\nBefore the list.\n\n"
        f"{first} First limitation begins\n"
        f"{indent}and continues with [retained evidence](https://example.org/evidence).\n"
        f"{second} Second limitation begins\n"
        f"{indent}and ends here.\n\nAfter the list.\n",
    )
    paragraphs = [
        item.getPlainText()
        for item in engine.parse_markdown(source, BASELINE, SPEC)
        if isinstance(item, Paragraph)
    ]
    assert paragraphs == [
        "Report",
        "8 Limitations",
        "Before the list.",
        f"{first} First limitation begins and continues with retained evidence.",
        f"{second} Second limitation begins and ends here.",
        "After the list.",
    ]
    output = tmp_path / "wrapped-list.pdf"
    engine.build(source, output, BASELINE, SPEC)
    rendered = " ".join(" ".join(page.extract_text().split()) for page in PdfReader(output).pages)
    fragments = (
        "Before the list.",
        "First limitation begins and continues with retained evidence.",
        "Second limitation begins and ends here.",
        "After the list.",
    )
    positions = [rendered.index(fragment) for fragment in fragments]
    assert positions == sorted(positions)


@pytest.mark.parametrize("changed", ["source", "asset"])
def test_rejects_stale_diagram_sources_and_assets(tmp_path: Path, changed: str) -> None:
    source, asset = tmp_path / "diagram.mmd", tmp_path / "diagram.png"
    source.write_text("flowchart TB\n A --> B\n", encoding="utf-8")
    asset.write_bytes(b"original rendered asset")
    manifest = {
        "mermaid_version": engine.MERMAID_VERSION,
        "diagrams": {source.name: engine.diagram_fingerprint(source, asset)},
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    spec = _spec_for(tmp_path, {source.name: asset.name})
    engine.validate_diagrams(spec)
    (source if changed == "source" else asset).write_bytes(b"changed")
    with pytest.raises(ValueError, match="Stale diagram"):
        engine.validate_diagrams(spec)


def test_pdf_has_resolved_contents_figures_and_repeatable_bytes(tmp_path: Path) -> None:
    # Use actual report figures; no Mermaid subprocess or network is needed.
    figure = (SPEC.asset_dir / "feature-2-runtime.png").as_posix()
    source = _write(
        tmp_path,
        "# Report\n\n[[PAGEBREAK]]\n\n[[TOC]]\n\n## Architecture\n\n"
        f"### Feature 2\n\n![Feature 2 architecture]({figure})\n\n"
        "[[PAGEBREAK]]\n\n## Evidence\n\n[Run](https://example.org/run)\n",
    )
    first, second = tmp_path / "first.pdf", tmp_path / "second.pdf"
    engine.build(source, first, BASELINE, SPEC)
    engine.build(source, second, BASELINE, SPEC)
    assert first.read_bytes() == second.read_bytes()
    reader = PdfReader(first)
    assert len(reader.pages) == 4
    assert "Architecture" in reader.pages[1].extract_text()
    assert "Building contents" not in reader.pages[1].extract_text()
    assert reader.pages[2].images
    destinations = [annotation.get_object()["/Dest"] for annotation in reader.pages[1]["/Annots"]]
    assert len(destinations) == 4  # Both chapter titles and page numbers are linked.
    assert destinations[0][0] == reader.pages[2].indirect_reference
    assert destinations[2][0] == reader.pages[3].indirect_reference
    assert reader.get_destination_page_number(reader.outline[0]) == 2


def test_diagram_hash_survives_cross_platform_checkout(tmp_path: Path) -> None:
    source, asset = tmp_path / "diagram.mmd", tmp_path / "diagram.png"
    source.write_bytes(b"flowchart TB\n A --> B\n")
    asset.write_bytes(b"unchanged image")
    expected = engine.diagram_fingerprint(source, asset)
    source.write_bytes(b"flowchart TB\r\n A --> B\r\n")
    assert engine.diagram_fingerprint(source, asset) == expected


def test_diagram_refresh_reuses_verified_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, asset = tmp_path / "diagram.mmd", tmp_path / "diagram.png"
    source.write_text("flowchart TB\n A --> B\n", encoding="utf-8")
    asset.write_bytes(b"rendered diagram")
    manifest = {
        "mermaid_version": engine.MERMAID_VERSION,
        "diagrams": {source.name: engine.diagram_fingerprint(source, asset)},
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    spec = _spec_for(tmp_path, {source.name: asset.name})
    monkeypatch.setattr(engine.shutil, "which", lambda _: "npx")
    calls: list[list[str]] = []

    def render(command: list[str], *, check: bool) -> None:
        assert check
        calls.append(command)
        asset.write_bytes(b"refreshed diagram")

    monkeypatch.setattr(engine.subprocess, "run", render)
    engine.render_diagrams(spec)
    assert calls == []
    source.write_text("flowchart TB\n A --> C\n", encoding="utf-8")
    engine.render_diagrams(spec)
    assert len(calls) == 1
    engine.validate_diagrams(spec)


def test_word_count_covers_the_assessed_body_only(tmp_path: Path) -> None:
    source = _write(
        tmp_path,
        "# Cover title\n\nCover words are not counted.\n\n[[TOC]]\n\n"
        "## 1 Overview\n\nOne two three.\n\n- four five\n\n"
        "| Col | Other |\n|---|---|\n| six | [seven](https://example.org) |\n\n"
        "<!-- Guidance for authors\nspanning lines -->\n"
        "[[TODO: Student 2 | not counted either]]\n\n"
        "![A long caption that is not counted](missing.png)\n\n"
        "```text\ncaptured output is evidence\n```\n\n"
        "## Appendix A Evidence\n\nNever counted.\n",
    )
    words = engine.count_words(source, SPEC)
    # Heading "1 Overview" (2) + prose (3) + list (2) + table header (2) + row (2).
    assert words.sections == (("1 Overview", 11),)
    assert words.total == 11


def test_conservative_count_includes_generated_tables_code_and_appendices(tmp_path: Path) -> None:
    spec = replace(
        SPEC,
        count_appendices_and_code=True,
        directives={
            "RESULTS": lambda _: ["| Check | Result |", "|---|---|", "| retrieval | passed |"]
        },
    )
    source = _write(
        tmp_path,
        "# Cover\n\n## 1 Results\n\n[[RESULTS]]\n\n"
        "```text\nrequest r1 status succeeded\n```\n\n"
        "## Appendix A Contributions\n\nOne two three.\n",
    )
    words = engine.count_words(source, spec)
    assert words.sections == (("1 Results", 10), ("Appendix A Contributions", 6))
    assert words.total == 16
    assert "code and appendices included" in engine.format_status(engine.review(source, spec), spec)


def test_inline_baseline_resolves_in_cover_table(tmp_path: Path) -> None:
    source = _write(tmp_path, "# Report\n\n| Commit reference | `[[BASELINE]]` |\n|---|---|\n")
    story = engine.parse_markdown(source, BASELINE, SPEC)
    table = next(item for item in story if isinstance(item, Table))
    assert table._cellvalues[0][1].getPlainText() == BASELINE


def test_full_text_count_includes_cover_and_image_captions(tmp_path: Path) -> None:
    source = _write(
        tmp_path,
        "# Cover title\n\nTwo words\n\n[[TOC]]\n\n## 1 Scope\n\n"
        "Three body words.\n\n![Figure one cited evidence](answer.png)\n",
    )
    spec = replace(SPEC, count_appendices_and_code=True, count_cover_and_captions=True)
    assert engine.count_words(source, spec).sections == (("Cover", 4), ("1 Scope", 9))
    assert engine.count_words(source, spec).total == 13
    assert "cover and captions included" in engine.format_status(engine.review(source, spec), spec)


def test_draft_renders_todos_and_missing_images_but_final_blocks(tmp_path: Path) -> None:
    source = _write(
        tmp_path,
        "# Report\n\n## 1 Scope\n\n<!-- hidden guidance -->\n"
        "[[TODO: Student 4 | Add the MCP screenshot]]\n\n![Pending capture](shots/f4.png)\n",
    )
    story = engine.parse_markdown(source, BASELINE, SPEC)
    rendered = " ".join(
        cell.getPlainText()
        for item in story
        if isinstance(item, Table)
        for row in item._cellvalues
        for value in row
        for cell in (value if isinstance(value, list) else [value])
        if isinstance(cell, Paragraph)
    )
    assert "TO COMPLETE / STUDENT 4" in rendered
    assert "hidden guidance" not in rendered
    status = engine.review(source, replace(SPEC, word_limit=1))
    assert [todo.owner for todo in status.todos] == ["Student 4"]
    assert status.missing_images == ("shots/f4.png",)
    blockers = status.final_blockers(replace(SPEC, word_limit=1), "main")
    assert len(blockers) == 4  # TODO, image, word limit and unpinned baseline.
    assert "Student 4" in engine.format_status(status, SPEC)


def test_release_directives_expand_before_rendering_and_counting(tmp_path: Path) -> None:
    spec = replace(SPEC, directives={"GREETING": lambda argument: [f"Hello {argument} there."]})
    source = _write(tmp_path, "# Report\n\n## 1 Scope\n\n[[GREETING team]]\n")
    assert engine.count_words(source, spec).total == 5
    paragraphs = [
        item.getPlainText()
        for item in engine.parse_markdown(source, BASELINE, spec)
        if isinstance(item, Paragraph)
    ]
    assert "Hello team there." in paragraphs


def test_code_columns_widen_to_fit_identifiers() -> None:
    rows = [["Tool", "Notes"], ["`platform.capabilities.v1`", "x " * 200]]
    widths = engine._fit_code_columns([60.0, engine.CONTENT_WIDTH - 60.0], rows)
    assert widths[0] > 60.0
    assert abs(sum(widths) - engine.CONTENT_WIDTH) < 0.01
