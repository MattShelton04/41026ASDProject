"""Protect report publication, navigation and reproducibility without external tools."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pypdf import PdfReader
from reportlab.platypus import Paragraph
from scripts import build_release0_report as report

BASELINE = "7d5350d19023fb1e978e85127a72e3500a1556f3"


def test_default_output_uses_submission_filename(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[Path, Path, str]] = []
    monkeypatch.setattr(report, "build", lambda *args: calls.append(args))

    assert report.main([]) == 0
    assert calls == [
        (
            report.REPORT_DIR / "release-0-technical-report.md",
            report.REPORT_DIR / "41026Group20Release0Report.pdf",
            BASELINE,
        )
    ]


def test_evidence_links_preserve_pinned_ref_and_section() -> None:
    source = report.REPORT_DIR / "release-0-technical-report.md"
    url = report._resolve_link(
        "../architecture/registered-feature-scope.md#document-control", source, BASELINE
    )
    assert url.endswith(
        f"/{BASELINE}/docs/architecture/registered-feature-scope.md#document-control"
    )
    assert (
        report._resolve_link("https://example.org/evidence#run", source, BASELINE)
        == "https://example.org/evidence#run"
    )


def test_headings_keep_visual_and_bookmark_hierarchy(tmp_path: Path) -> None:
    source = tmp_path / "headings.md"
    source.write_text("# Report\n\n## Chapter\n\n### Section\n\n#### Feature\n", encoding="utf-8")
    headings = [
        item for item in report.parse_markdown(source, BASELINE) if isinstance(item, Paragraph)
    ]
    assert [item.style.name for item in headings] == [
        "ReportTitle",
        "HeadingOne",
        "HeadingTwo",
        "HeadingThree",
    ]
    assert [getattr(item, "_heading_level", None) for item in headings] == [None, 0, 1, 2]


def test_migration_directory_links_to_pinned_github_tree() -> None:
    source = report.REPORT_DIR / "release-0-technical-report.md"
    migration_path = "student-1/database/src/propertyscope_data_store/sql"
    url = report._resolve_link(f"../../{migration_path}", source, BASELINE)
    assert (
        url == f"https://github.com/MattShelton04/41026ASDProject/tree/{BASELINE}/{migration_path}"
    )


@pytest.mark.parametrize("changed", ["source", "asset"])
def test_rejects_stale_diagram_sources_and_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed: str
) -> None:
    source, asset = tmp_path / "diagram.mmd", tmp_path / "diagram.png"
    source.write_text("flowchart TB\n A --> B\n", encoding="utf-8")
    asset.write_bytes(b"original rendered asset")
    manifest = {
        "mermaid_version": report.MERMAID_VERSION,
        "diagrams": {source.name: report._diagram_fingerprint(source, asset)},
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(report, "ASSET_DIR", tmp_path)
    monkeypatch.setattr(report, "DIAGRAM_DIR", tmp_path)
    monkeypatch.setattr(report, "_diagram_pairs", lambda: {source.name: asset.name})
    report._validate_mermaid_diagrams()
    (source if changed == "source" else asset).write_bytes(b"changed")
    with pytest.raises(ValueError, match="Stale diagram"):
        report._validate_mermaid_diagrams()


def test_pdf_has_resolved_contents_figures_and_repeatable_bytes(tmp_path: Path) -> None:
    source = tmp_path / "report.md"
    # Use actual report figures; no Mermaid subprocess or network is needed.
    figure = (report.ASSET_DIR / "feature-2-runtime.png").as_posix()
    source.write_text(
        "# Report\n\n[[PAGEBREAK]]\n\n[[TOC]]\n\n## Architecture\n\n"
        f"### Feature 2\n\n![Feature 2 architecture]({figure})\n\n"
        "[[PAGEBREAK]]\n\n## Evidence\n\n[Run](https://example.org/run)\n",
        encoding="utf-8",
    )
    first, second = tmp_path / "first.pdf", tmp_path / "second.pdf"
    report.build(source, first, BASELINE)
    report.build(source, second, BASELINE)
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


def test_report_includes_all_five_architectures_and_erds() -> None:
    source = (report.REPORT_DIR / "release-0-technical-report.md").read_text(encoding="utf-8")
    pairs = report._diagram_pairs()
    for student in range(1, 6):
        for kind in ("runtime", "erd"):
            asset = pairs[f"feature-{student}-{kind}.mmd"]
            assert f"assets/release-0/{asset}" in source


def test_diagram_hash_survives_cross_platform_checkout(tmp_path: Path) -> None:
    source, asset = tmp_path / "diagram.mmd", tmp_path / "diagram.png"
    source.write_bytes(b"flowchart TB\n A --> B\n")
    asset.write_bytes(b"unchanged image")
    expected = report._diagram_fingerprint(source, asset)
    source.write_bytes(b"flowchart TB\r\n A --> B\r\n")
    assert report._diagram_fingerprint(source, asset) == expected


def test_diagram_refresh_reuses_verified_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, asset = tmp_path / "diagram.mmd", tmp_path / "diagram.png"
    source.write_text("flowchart TB\n A --> B\n", encoding="utf-8")
    asset.write_bytes(b"rendered diagram")
    manifest = {
        "mermaid_version": report.MERMAID_VERSION,
        "diagrams": {source.name: report._diagram_fingerprint(source, asset)},
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(report, "ASSET_DIR", tmp_path)
    monkeypatch.setattr(report, "DIAGRAM_DIR", tmp_path)
    monkeypatch.setattr(report, "_diagram_pairs", lambda: {source.name: asset.name})
    monkeypatch.setattr(report.shutil, "which", lambda _: "npx")
    calls: list[list[str]] = []

    def render(command: list[str], *, check: bool) -> None:
        assert check
        calls.append(command)
        asset.write_bytes(b"refreshed diagram")

    monkeypatch.setattr(report.subprocess, "run", render)
    report.render_diagrams()
    assert calls == []
    source.write_text("flowchart TB\n A --> C\n", encoding="utf-8")
    report.render_diagrams()
    assert len(calls) == 1
    report._validate_mermaid_diagrams()
