"""Cover the adoption assertions shared by every feature owner."""

import json
import shutil
from pathlib import Path

import pytest

from shared_contracts.grounding import RETRIEVAL_TOOL, grounded_allowlist_variants
from shared_testkit import (
    assert_corpus_manifest,
    assert_grounded_allowlist_accepted,
    assert_grounded_answer,
    load_corpus_manifest,
)

FEATURE = "student-9-example"
CORPUS = "operator-guidance"


def _write_manifest(
    directory: Path, *, documents: list[dict[str, object]] | None = None, **overrides: object
) -> Path:
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "feature_key": FEATURE,
        "corpus_id": CORPUS,
        "documents": documents
        if documents is not None
        else [
            {
                "document_id": "guidance-one",
                "title": "Bounded guidance",
                "source_uri": "https://example.invalid/guidance-one.md",
                "source_date": "2026-09-19",
                "license": "CC0-1.0",
                "evidence_kind": "project_guidance",
                "location": "Operator guidance: guidance-one",
                "path": "documents/guidance-one.md",
            }
        ],
    }
    payload.update(overrides)
    (directory / "documents").mkdir(parents=True, exist_ok=True)
    (directory / "documents" / "guidance-one.md").write_text("Bounded text.", encoding="utf-8")
    manifest = directory / "corpus.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    return manifest


def test_loads_declared_document_paths(tmp_path: Path) -> None:
    request = load_corpus_manifest(_write_manifest(tmp_path))
    assert request.feature_key == FEATURE
    assert request.documents[0].text == "Bounded text."


def test_accepts_the_matching_identity(tmp_path: Path) -> None:
    request = assert_corpus_manifest(
        _write_manifest(tmp_path), feature_key=FEATURE, corpus_id=CORPUS
    )
    assert request.corpus_id == CORPUS


def test_rejects_a_mismatched_identity(tmp_path: Path) -> None:
    manifest = _write_manifest(tmp_path)
    with pytest.raises(AssertionError, match="corpus_id"):
        assert_corpus_manifest(manifest, feature_key=FEATURE, corpus_id="other-guidance")


def test_rejects_a_missing_document_file(tmp_path: Path) -> None:
    manifest = _write_manifest(tmp_path)
    (tmp_path / "documents" / "guidance-one.md").unlink()
    with pytest.raises(AssertionError, match="missing file"):
        load_corpus_manifest(manifest)


def test_rejects_a_document_escaping_its_directory(tmp_path: Path) -> None:
    (tmp_path / "outside.md").write_text("Elsewhere.", encoding="utf-8")
    manifest = _write_manifest(
        tmp_path,
        documents=[
            {
                "document_id": "escapee",
                "title": "Outside",
                "source_uri": "https://example.invalid/outside.md",
                "license": "CC0-1.0",
                "path": "../outside.md",
            }
        ],
    )
    with pytest.raises(AssertionError, match="escapes the manifest directory"):
        load_corpus_manifest(manifest)


def test_grounded_allowlist_variants_are_accepted() -> None:
    base = ("feature.read.v1",)
    assert_grounded_allowlist_accepted(grounded_allowlist_variants(base), base)


def test_allowlist_without_the_grounded_variant_fails() -> None:
    base = ("feature.read.v1",)
    with pytest.raises(AssertionError, match=RETRIEVAL_TOOL):
        assert_grounded_allowlist_accepted((base,), base)


def test_supported_answer_requires_citations() -> None:
    answer = {
        "confidence": "moderate",
        "confidence_reason": "Retrieved guidance supports the summary.",
        "safety_boundary": "Read-only guidance.",
        "findings": [{"text": "Guidance.", "kind": "guidance", "citation_ids": ["c1"]}],
    }
    assert_grounded_answer(answer, expect_citations=True)
    with pytest.raises(AssertionError, match="must not cite sources"):
        assert_grounded_answer(answer, expect_citations=False)


def test_insufficient_answer_must_not_cite() -> None:
    answer = {
        "confidence": "insufficient",
        "confidence_reason": "Project sources do not cover the topic.",
        "safety_boundary": "Read-only guidance.",
        "findings": [],
    }
    assert_grounded_answer(answer, expect_citations=False)
    with pytest.raises(AssertionError, match="must cite retrieved documents"):
        assert_grounded_answer(answer, expect_citations=True)


def test_feature_1_manifest_satisfies_the_shared_assertions() -> None:
    """The reference corpus is the worked example owners copy."""
    root = Path(__file__).resolve().parents[3]
    assert_corpus_manifest(
        root / "student-1/config/rag/corpus.json",
        feature_key="student-1-propertyscope-data-platform",
        corpus_id="operator-guidance",
    )


def test_shipped_corpus_template_passes_the_assertion_it_documents(tmp_path: Path) -> None:
    """The template owners copy must satisfy the check the adoption guide tells them to run."""
    root = Path(__file__).resolve().parents[3]
    source = root / "docs/release-1/templates/rag-corpus"
    target = tmp_path / "rag"
    shutil.copytree(source, target)
    manifest = target / "corpus.json"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            "student-N-REPLACE-WITH-YOUR-FEATURE-KEY", "student-9-example"
        ),
        encoding="utf-8",
    )

    assert_corpus_manifest(manifest, feature_key="student-9-example", corpus_id="operator-guidance")


def test_loader_agrees_with_the_real_ingest_loader(tmp_path: Path) -> None:
    """shared_testkit may not depend on rag-server, so pin the duplicated rules instead."""
    from rag_server.cli import load_manifest

    manifest = _write_manifest(tmp_path)

    assert load_corpus_manifest(manifest) == load_manifest(manifest)


def test_predicate_form_catches_a_list_versus_tuple_comparison() -> None:
    """The most common adoption mistake: comparing the wire list against tuples."""
    base = ("feature.read.v1",)
    approved = grounded_allowlist_variants(base)

    def broken(wire_allowlist: list[str]) -> bool:
        return wire_allowlist in approved  # list is never equal to a tuple

    def correct(wire_allowlist: list[str]) -> bool:
        return tuple(wire_allowlist) in approved

    assert_grounded_allowlist_accepted(correct, base)
    with pytest.raises(AssertionError, match="JSON list"):
        assert_grounded_allowlist_accepted(broken, base)


def test_corpus_check_reports_sections_that_would_be_split(tmp_path: Path) -> None:
    manifest = _write_manifest(tmp_path)
    document = tmp_path / "documents" / "guidance-one.md"
    long_section = "## Long\n\n" + "A claim and its qualification. " * 50
    document.write_text("# Guide\n\nShort intro.\n\n" + long_section, encoding="utf-8")

    with pytest.raises(AssertionError, match="Long"):
        assert_corpus_manifest(manifest, feature_key=FEATURE, corpus_id=CORPUS)

    split = long_section.replace(". A claim", ".\n\n## More\n\nA claim", 20)
    document.write_text("# Guide\n\n" + split, encoding="utf-8")
    assert_corpus_manifest(manifest, feature_key=FEATURE, corpus_id=CORPUS)
