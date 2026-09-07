"""Real SQLite and deterministic injected embeddings; no service or network is required."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from rag_server.embeddings import FixtureEmbedder, UnavailableEmbedder, normalized_vector
from rag_server.index import CorpusIndex, CorpusScopeDeniedError, chunk_document, normalize

from shared_contracts.retrieval import CorpusDocument, CorpusIngestRequest, RetrievalRequest

FEATURE = "student-1-propertyscope-data-platform"
SCOPE = frozenset({(FEATURE, "operator-guidance")})


def document(document_id: str = "publication", **changes: object) -> CorpusDocument:
    return CorpusDocument(
        document_id=document_id,
        title="Publication guidance",
        source_uri="https://example.org/guidance",
        text="Publication requires explicit review approval.",
        license="CC0-1.0",
    ).evolve(**changes)


def batch(*documents: CorpusDocument) -> CorpusIngestRequest:
    return CorpusIngestRequest(
        feature_key=FEATURE, corpus_id="operator-guidance", documents=documents
    )


def query(**changes: object) -> RetrievalRequest:
    return RetrievalRequest(
        feature_key=FEATURE,
        corpus_id="operator-guidance",
        query="publication review approval",
    ).evolve(**changes)


@pytest.fixture
def index() -> Iterator[CorpusIndex]:
    service = CorpusIndex(":memory:", FixtureEmbedder(), SCOPE)
    yield service
    service.close()


def test_retrieval_is_pinned_and_idempotent(index: CorpusIndex) -> None:
    first = index.ingest(batch(document()))
    assert index.ingest(batch(document())) == first
    result = index.retrieve(query())
    assert result.status == "ready"
    assert result.corpus_version == first.corpus_version
    citation = result.citations[0]
    assert citation.content_hash == hashlib.sha256(citation.excerpt.encode()).hexdigest()
    assert citation.ingested_at == first.ingested_at
    assert citation.source_date is None
    assert citation.location == "chars 1-46"
    assert citation.evidence_kind == "project_guidance"


@pytest.mark.parametrize(
    "changes",
    [
        {"title": "Corrected title"},
        {"source_uri": "https://example.org/revised"},
        {"license": "CC-BY-4.0"},
        {"source_date": "2026-09-01"},
        {"location": "Section 1"},
        {"text": "Publication requires careful human approval."},
        {"evidence_kind": "fixture"},
    ],
)
def test_metadata_and_content_changes_create_version(
    index: CorpusIndex, changes: dict[str, object]
) -> None:
    first = index.ingest(batch(document()))
    second = index.ingest(batch(document(**changes)))
    assert first.corpus_version != second.corpus_version
    assert index.current(FEATURE, "operator-guidance") == second


def test_normalization_and_order_are_idempotent(index: CorpusIndex) -> None:
    first = index.ingest(batch(document("a", text="  Cafe\u0301\r\nreview  "), document("b")))
    second = index.ingest(batch(document("b"), document("a", text="Café\nreview")))
    assert first == second
    assert normalize("\rText\r\n") == "Text"


def test_replace_withdraw_and_reactivate(index: CorpusIndex) -> None:
    initial = index.ingest(batch(document("a"), document("b")))
    initial_citations = index.retrieve(query()).citations
    replaced = index.ingest(batch(document("b")))
    assert replaced.document_count == 1
    assert index.retrieve(query(document_ids=("a",))).status == "no_match"
    withdrawn = index.ingest(batch())
    assert withdrawn.chunk_count == 0
    assert index.retrieve(query()).status == "empty"
    original_embedder = index.embedder
    # Retained reactivation is a pointer update, even if fresh embedding is broken.
    index.embedder = InvalidEmbedder([])
    restored = index.ingest(batch(document("a"), document("b")))
    assert restored == initial
    index.embedder = original_embedder
    assert index.retrieve(query()).citations == initial_citations


class InvalidEmbedder(FixtureEmbedder):
    def __init__(self, vectors: list[list[float]]) -> None:
        self.vectors = vectors

    def embed(self, texts: Sequence[str], *, query: bool = False) -> list[list[float]]:
        return self.vectors


@pytest.mark.parametrize(
    "vectors", [[], [[1.0]], [[0.0] * 384], [[float("nan")] * 384], [[float("inf")] * 384]]
)
def test_failed_refresh_retains_active(index: CorpusIndex, vectors: list[list[float]]) -> None:
    first = index.ingest(batch(document()))
    index.embedder = InvalidEmbedder(vectors)
    with pytest.raises(ValueError):
        index.ingest(batch(document(title="Changed")))
    assert index.current(FEATURE, "operator-guidance") == first
    assert index.retrieve(query()).status == "unavailable"


def test_transaction_failure_rolls_back_activation(index: CorpusIndex) -> None:
    first = index.ingest(batch(document()))
    index._db.execute(
        "CREATE TRIGGER fail_insert BEFORE INSERT ON chunks "
        "BEGIN SELECT RAISE(ABORT, 'test failure'); END"
    )
    with pytest.raises(sqlite3.IntegrityError):
        index.ingest(batch(document(title="Changed")))
    assert index.current(FEATURE, "operator-guidance") == first


def test_scope_and_initial_evidence_class(index: CorpusIndex) -> None:
    with pytest.raises(CorpusScopeDeniedError):
        index.ingest(batch(document()).evolve(feature_key="other-feature"))
    with pytest.raises(CorpusScopeDeniedError):
        index.retrieve(query(corpus_id="private"))
    with pytest.raises(CorpusScopeDeniedError):
        index.ingest(batch(document(evidence_kind="official")))


def test_empty_no_match_top_k_and_context_budget(index: CorpusIndex) -> None:
    assert index.retrieve(query()).status == "empty"
    index.ingest(batch(*(document(f"doc-{number}") for number in range(10))))
    assert len(index.retrieve(query(top_k=2)).citations) == 2
    result = index.retrieve(query(max_context_chars=100, top_k=10))
    assert sum(len(citation.excerpt) for citation in result.citations) <= 100
    assert index.retrieve(query(query="zygomatic quasars", min_score=0.9)).status == "no_match"
    index.ingest(batch(document(text="publication " * 150)))
    assert index.retrieve(query(max_context_chars=100)).status == "no_match"


def test_model_identity_change_requires_ingestion(index: CorpusIndex) -> None:
    first = index.ingest(batch(document()))
    index.embedder = UnavailableEmbedder()
    assert index.retrieve(query()).status == "unavailable"
    changed = FixtureEmbedder()
    changed.identity = "fixture-v2"
    index.embedder = changed
    second = index.ingest(batch(document()))
    assert first.corpus_version != second.corpus_version


def test_restart_persistence_retention_and_exclusive_owner(tmp_path: Path) -> None:
    path = tmp_path / "index.sqlite3"
    index = CorpusIndex(path, FixtureEmbedder(), SCOPE, retained_versions=2)
    for number in range(5):
        last = index.ingest(batch(document(title=f"Version {number}")))
    assert index._db.execute("SELECT count(*) FROM versions").fetchone()[0] == 2
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        CorpusIndex(path, FixtureEmbedder(), SCOPE)
    index.close()
    restarted = CorpusIndex(path, FixtureEmbedder(), SCOPE)
    assert restarted.current(FEATURE, "operator-guidance") == last
    assert restarted.retrieve(query()).status == "ready"
    restarted.close()


def test_concurrent_ingest_and_search_are_complete(index: CorpusIndex) -> None:
    def exercise(number: int) -> None:
        index.ingest(batch(document(title=f"Version {number}")))
        result = index.retrieve(query())
        assert all(
            citation.corpus_version == result.corpus_version for citation in result.citations
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(exercise, range(12)))


def test_chunks_overlap_without_losing_tail() -> None:
    text = "x" * 2500
    chunks = chunk_document(document(text=text, location="Section A"))
    assert len(chunks) == 3
    assert chunks[-1][1] == text[2160:]
    assert chunks[-1][2] == "Section A; chars 2161-2500"
    assert len({chunk[0] for chunk in chunks}) == 3
    assert normalized_vector([3, 4], 2) == [0.6, 0.8]


@pytest.mark.parametrize("retained,scopes", [(0, SCOPE), (6, SCOPE), (3, frozenset())])
def test_invalid_index_bounds(retained: int, scopes: frozenset[tuple[str, str]]) -> None:
    with pytest.raises(ValueError):
        CorpusIndex(":memory:", FixtureEmbedder(), scopes, retained_versions=retained)
