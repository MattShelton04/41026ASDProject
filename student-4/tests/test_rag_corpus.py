"""Validate the due-diligence RAG guidance corpus before it is ingested."""

from __future__ import annotations

from pathlib import Path

from propertyscope_due_diligence.api import FEATURE_KEY
from shared_testkit import assert_corpus_manifest

CORPUS_ID = "operator-guidance"


def test_corpus_manifest_is_ingestible() -> None:
    """The identity the host launcher scopes RAG with must match what this feature declares."""
    assert_corpus_manifest(
        Path("student-4/config/rag/corpus.json"),
        feature_key=FEATURE_KEY,
        corpus_id=CORPUS_ID,
    )
