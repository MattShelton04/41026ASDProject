"""Owned corpus policy checks, independent of network, models and the RAG runtime."""

from __future__ import annotations

import json
from pathlib import Path

from shared_contracts.retrieval import CorpusIngestRequest

ROOT = Path(__file__).resolve().parents[2]
CORPUS_ROOT = ROOT / "config/rag"


def _load_corpus() -> CorpusIngestRequest:
    payload = json.loads((CORPUS_ROOT / "corpus.json").read_text(encoding="utf-8"))
    for document in payload["documents"]:
        path = (CORPUS_ROOT / document.pop("path")).resolve()
        assert path.is_relative_to(CORPUS_ROOT.resolve())
        document["text"] = path.read_text(encoding="utf-8")
    return CorpusIngestRequest.model_validate(payload)


def test_corpus_contains_only_bounded_authored_guidance_with_traceable_sources() -> None:
    corpus = _load_corpus()
    assert corpus.feature_key == "student-1-propertyscope-data-platform"
    assert corpus.corpus_id == "operator-guidance"
    assert len(corpus.documents) == 10
    for document in corpus.documents:
        assert document.evidence_kind == "project_guidance"
        assert document.license.startswith("CC0-1.0")
        assert document.source_date is not None
        assert len(document.text) <= 1200  # Each small authored topic fits one exact excerpt.
        assert "Basis:" in document.text
        assert document.source_uri.startswith("https://github.com/MattShelton04/")


def test_guidance_preserves_current_publication_partial_scope_and_unknown_evidence() -> None:
    documents = {document.document_id: document.text for document in _load_corpus().documents}
    assert "independently of downstream imports" in documents["publication"]
    assert "cannot roll back producer publication" in documents["publication"]
    assert "cannot replace the accepted complete" in documents["partial-psi"]
    assert "not exact contract-date intervals" in documents["partial-psi"]
    assert "unavailable, not zero" in documents["crime-coverage"]
    assert "not proof" in documents["missing-evidence"]
    assert "read-only assistant explanations do not authorize publication" in documents["recovery"]


def test_frozen_cases_include_negative_claims_and_real_expected_documents() -> None:
    cases = json.loads((CORPUS_ROOT / "evaluation-v1.json").read_text(encoding="utf-8"))
    documents = {document.document_id for document in _load_corpus().documents}
    assert {case["category"] for case in cases["cases"]} == {
        "supported",
        "absent",
        "ambiguous",
        "stale_conflict",
        "injection",
    }
    assert len({case["id"] for case in cases["cases"]}) == len(cases["cases"])
    for case in cases["cases"]:
        assert set(case["expected_document_ids"]) <= documents
        assert case["forbidden_claims"] and case["answer_policy"]
        if case["category"] == "supported":
            assert case["expected_document_ids"]
        for fixture in case.get("additional_documents", []):
            assert fixture["evidence_kind"] == "fixture"
            assert fixture["document_id"] not in documents
