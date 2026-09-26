"""Owned corpus policy checks, independent of network, models and the RAG runtime."""

from __future__ import annotations

import json
import re
from pathlib import Path

from shared_contracts.retrieval import CorpusIngestRequest
from shared_testkit import assert_corpus_manifest

ROOT = Path(__file__).resolve().parents[2]
CORPUS_ROOT = ROOT / "config/rag"
FEATURE_KEY = "student-1-propertyscope-data-platform"


def _corpus() -> CorpusIngestRequest:
    return assert_corpus_manifest(
        CORPUS_ROOT / "corpus.json", feature_key=FEATURE_KEY, corpus_id="operator-guidance"
    )


def test_corpus_is_authored_guidance_with_traceable_sources() -> None:
    for document in _corpus().documents:
        assert document.evidence_kind == "project_guidance"
        assert document.license.startswith("CC0-1.0")
        assert document.source_date is not None
        # The title a citation shows is the heading a reader sees in the source file.
        assert document.text.startswith(f"# {document.title}\n"), document.document_id


def test_every_document_file_is_listed_in_the_manifest() -> None:
    listed = {document.document_id for document in _corpus().documents}
    on_disk = {path.stem for path in (CORPUS_ROOT / "documents").glob("*.md")}
    assert on_disk == listed


def test_guidance_uses_interface_terms_rather_than_internal_field_names() -> None:
    """Answers quote guidance to users, so snake_case identifiers read as jargon."""
    for document in _corpus().documents:
        prose = re.sub(r"`[^`]*`", "", document.text)
        assert not re.search(r"\b[a-z]+_[a-z_]+\b", prose), document.document_id


def test_evaluation_cases_reference_real_documents_and_cover_negative_categories() -> None:
    cases = json.loads((CORPUS_ROOT / "evaluation-v2.json").read_text(encoding="utf-8"))
    documents = {document.document_id for document in _corpus().documents}
    categories = {case["category"] for case in cases["cases"]}
    assert {"supported", "absent", "injection"} <= categories
    assert len({case["id"] for case in cases["cases"]}) == len(cases["cases"])
    for case in cases["cases"]:
        assert set(case["expected_document_ids"]) <= documents
        assert case["forbidden_claims"] and case["answer_policy"]
        if case["category"] == "supported":
            assert case["expected_document_ids"]
        for fixture in case.get("additional_documents", []):
            assert fixture["evidence_kind"] == "fixture"
            assert fixture["document_id"] not in documents
