"""Validate Feature 3's reviewed RAG guidance before local ingestion."""

from pathlib import Path

from propertyscope_suburb_analytics.app import FEATURE_KEY
from shared_testkit import assert_corpus_manifest


def test_corpus_manifest_is_ingestible() -> None:
    assert_corpus_manifest(
        Path("student-3/config/rag/corpus.json"),
        feature_key=FEATURE_KEY,
        corpus_id="suburb-analytics-guidance",
    )
