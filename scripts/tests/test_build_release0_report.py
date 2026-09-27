"""Protect the Release 0 report configuration and its frozen Canvas submission."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from scripts import build_release0_report as report
from scripts import report_pdf

SUBMITTED_SHA256 = "ab18217737aefbbe43f0645aa32da122647500025ef8e55d347aaad7c9dd85b3"


def test_submitted_pdf_is_frozen() -> None:
    digest = hashlib.sha256(report.SUBMITTED_PDF.read_bytes()).hexdigest()
    assert digest == SUBMITTED_SHA256


def test_default_output_never_overwrites_the_submission(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(report_pdf, "build", lambda *args: calls.append(args))

    assert report.main([]) == 0
    assert calls == [(report.SOURCE, report.DEFAULT_OUTPUT, report.BASELINE, report.SPEC)]
    assert report_pdf.ROOT / "tmp" in report.DEFAULT_OUTPUT.parents
    with pytest.raises(SystemExit):
        report.main(["--output", str(report.SUBMITTED_PDF)])
    assert len(calls) == 1


def test_migration_directory_links_to_pinned_github_tree() -> None:
    migration_path = "student-1/database/src/propertyscope_data_store/sql"
    url = report_pdf.resolve_link(f"../../{migration_path}", report.SOURCE, report.BASELINE)
    assert url == (
        f"https://github.com/MattShelton04/41026ASDProject/tree/{report.BASELINE}/{migration_path}"
    )


def test_report_includes_all_five_architectures_and_erds() -> None:
    source = report.SOURCE.read_text(encoding="utf-8")
    pairs = report.SPEC.diagram_pairs
    for student in range(1, 6):
        for kind in ("runtime", "erd"):
            asset = pairs[f"feature-{student}-{kind}.mmd"]
            assert f"assets/release-0/{asset}" in source


def test_committed_figures_match_their_mermaid_sources() -> None:
    report_pdf.validate_diagrams(report.SPEC)


def test_release_0_sizing_keeps_its_compact_figures(tmp_path: Path) -> None:
    assert report.SPEC.image_max_height(tmp_path / "compose-topology.png") < (
        report.SPEC.image_max_height(tmp_path / "integrated-architecture.png")
    )
