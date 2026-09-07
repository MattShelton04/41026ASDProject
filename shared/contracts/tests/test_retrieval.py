"""Strict retrieval envelope validation independent of the owning service."""

import pytest
from pydantic import ValidationError

from shared_contracts.retrieval import (
    CorpusDocument,
    CorpusIngestRequest,
    EvidenceCitation,
    RetrievalRequest,
    RetrievalResponse,
)


def document(**changes: object) -> CorpusDocument:
    return CorpusDocument(
        document_id="guide",
        title="Guide",
        source_uri="https://example.org/guide",
        text="Public guidance",
        license="CC0",
    ).evolve(**changes)


@pytest.mark.parametrize(
    "uri",
    [
        "javascript:alert(1)",
        "file:///secret",
        "https://user:pass@example.org",
        "//example.org",
        "https://example.org/\nnext",
        "http://",
        "https://a\\b",
    ],
)
def test_reject_unsafe_source_uris(uri: str) -> None:
    with pytest.raises(ValidationError):
        document(source_uri=uri)


@pytest.mark.parametrize(
    "changes",
    [
        {"text": " "},
        {"title": " "},
        {"license": ""},
        {"access_class": "private"},
        {"status": "withdrawn"},
        {"document_id": "../escape"},
        {"unknown": True},
    ],
)
def test_document_rejects_invalid_metadata(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        document(**changes)


def test_batch_bounds_and_uniqueness() -> None:
    with pytest.raises(ValidationError, match="unique"):
        CorpusIngestRequest(
            feature_key="feature-1", corpus_id="guide", documents=(document(), document())
        )
    with pytest.raises(ValidationError, match="500000"):
        CorpusIngestRequest(
            feature_key="feature-1",
            corpus_id="guide",
            documents=tuple(
                document(document_id=f"doc-{number}", text="x" * 60000) for number in range(9)
            ),
        )
    empty = CorpusIngestRequest(feature_key="feature-1", corpus_id="guide", documents=())
    assert CorpusIngestRequest.model_validate_json(empty.model_dump_json()) == empty


@pytest.mark.parametrize(
    "changes",
    [
        {"query": " "},
        {"top_k": 11},
        {"top_k": 0},
        {"min_score": float("nan")},
        {"max_context_chars": 12001},
        {"schema_version": "2.0"},
        {"owner_id": "private"},
    ],
)
def test_query_bounds(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        RetrievalRequest(feature_key="feature-1", corpus_id="guide", query="guidance").evolve(
            **changes
        )


def test_response_rejects_forged_scope_and_inconsistent_status() -> None:
    citation = EvidenceCitation(
        citation_id="cite-1",
        feature_key="feature-1",
        corpus_id="guide",
        corpus_version="a" * 64,
        document_id="guide",
        chunk_id="chunk-1",
        title="Guide",
        source_uri="https://example.org",
        content_hash="b" * 64,
        location="chars 1-5",
        ingested_at="2026-09-06T00:00:00Z",
        evidence_kind="project_guidance",
        excerpt="Guide",
        score=0.8,
    )
    valid = RetrievalResponse(
        feature_key="feature-1",
        corpus_id="guide",
        corpus_version="a" * 64,
        status="ready",
        citations=(citation,),
    )
    for changes in (
        {"status": "empty"},
        {"citations": ()},
        {"corpus_version": "b" * 64},
        {"feature_key": "feature-2"},
        {"corpus_id": "other"},
        {"citations": (citation, citation)},
        {"corpus_version": None},
    ):
        with pytest.raises(ValidationError):
            valid.evolve(**changes)
    with pytest.raises(ValidationError):
        valid.evolve(status="no_match", citations=(), corpus_version=None)
    with pytest.raises(ValidationError):
        citation.evolve(ingested_at="2026-09-06T00:00:00")
