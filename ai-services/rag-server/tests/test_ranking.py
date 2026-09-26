"""Pure ranking behaviour; no index, model or network."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from rag_server.embeddings import FixtureEmbedder
from rag_server.index import CorpusIndex
from rag_server.ranking import bm25_scores, fused_order, tokens

from shared_contracts.retrieval import CorpusDocument, CorpusIngestRequest, RetrievalRequest

FEATURE = "student-9-example"
SCOPE = frozenset({(FEATURE, "guidance")})


def test_tokens_drop_stopwords_and_simple_plurals() -> None:
    assert tokens("What are the Sections of a property page?") == ["section", "property", "page"]
    assert tokens("address") == ["address"]


def test_bm25_prefers_the_passage_naming_the_rare_term() -> None:
    passages = [
        "Research areas receive published data over HTTP.",
        "Research available lists linked datasets on a property page.",
        "Other research areas import data into their own databases.",
    ]
    scores = bm25_scores("research available section", passages)
    assert max(range(3), key=scores.__getitem__) == 1
    assert bm25_scores("", passages) == [0.0, 0.0, 0.0]


def test_fusion_lifts_a_keyword_match_that_dense_similarity_ranks_second() -> None:
    dense = [0.74, 0.73, 0.60]
    keyword = [0.0, 3.0, 0.4]
    assert fused_order(dense, keyword)[0] == 1
    # Swapped ranks tie under reciprocal rank fusion; dense similarity breaks the tie.
    assert fused_order(dense, [0.4, 3.0, 0.0])[0] == 0
    # Without keyword evidence the dense order is kept.
    assert fused_order(dense, [0.0, 0.0, 0.0]) == [0, 1, 2]


@pytest.fixture
def index() -> Iterator[CorpusIndex]:
    service = CorpusIndex(":memory:", FixtureEmbedder(), SCOPE)
    yield service
    service.close()


def test_retrieval_caps_passages_per_document(index: CorpusIndex) -> None:
    sections = "\n\n".join(f"## Part {n}\n\n" + "publication review rules " * 20 for n in range(4))
    index.ingest(
        CorpusIngestRequest(
            feature_key=FEATURE,
            corpus_id="guidance",
            documents=(
                CorpusDocument(
                    document_id="long",
                    title="Publication",
                    source_uri="https://example.org/long",
                    text=sections,
                    license="CC0-1.0",
                ),
                CorpusDocument(
                    document_id="other",
                    title="Review",
                    source_uri="https://example.org/other",
                    text="Publication review is recorded.",
                    license="CC0-1.0",
                ),
            ),
        )
    )
    result = index.retrieve(
        RetrievalRequest(
            feature_key=FEATURE, corpus_id="guidance", query="publication review", min_score=0
        )
    )
    documents = [citation.document_id for citation in result.citations]
    assert documents.count("long") == 2
    assert "other" in documents
