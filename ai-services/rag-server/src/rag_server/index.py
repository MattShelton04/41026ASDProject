"""Exclusive service-owned SQLite index with transactional complete-batch activation."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import unicodedata
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rag_server.embeddings import Embedder, EmbeddingUnavailableError, normalized_vector
from shared_contracts.retrieval import (
    CorpusDocument,
    CorpusIngestRequest,
    CorpusVersion,
    EvidenceCitation,
    RetrievalRequest,
    RetrievalResponse,
)

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 120
STRATEGY = "unicode-nfc-newline-trim-char1200-overlap120-v1"


def normalize(text: str) -> str:
    return unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n")).strip()


def chunk_document(document: CorpusDocument) -> list[tuple[str, str, str]]:
    """Stable IDs, exact excerpts and one-based normalized character positions."""
    text = normalize(document.text)
    chunks = []
    for start in range(0, len(text), CHUNK_SIZE - CHUNK_OVERLAP):
        excerpt = text[start : start + CHUNK_SIZE]
        chunk_id = hashlib.sha256(f"{document.document_id}:{start}".encode()).hexdigest()
        prefix = document.location + "; " if document.location else ""
        location = f"{prefix}chars {start + 1}-{start + len(excerpt)}"
        chunks.append((chunk_id, excerpt, location))
        if start + CHUNK_SIZE >= len(text):
            break
    return chunks


class CorpusScopeDeniedError(ValueError):
    """Only explicitly registered public feature corpora can enter this service."""


class CorpusIndex:
    """One bounded database, owned only by this service instance.

    The connection's exclusive locking mode and immediate transaction serialize writers.
    The process lock also protects retrieval against half-replaced in-process snapshots.
    """

    def __init__(
        self,
        path: str | Path,
        embedder: Embedder,
        allowed_corpora: frozenset[tuple[str, str]],
        *,
        retained_versions: int = 3,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not 1 <= retained_versions <= 5 or not 1 <= len(allowed_corpora) <= 20:
            raise ValueError("index requires 1-20 corpora and 1-5 retained versions")
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.embedder = embedder
        self.allowed_corpora = allowed_corpora
        self.retained_versions = retained_versions
        self.clock = clock
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(path), check_same_thread=False, timeout=2)
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.execute("PRAGMA locking_mode=EXCLUSIVE")
        self._db.execute("PRAGMA max_page_count=131072")  # 512 MiB at SQLite's 4096-byte page size.
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS versions (
                feature TEXT NOT NULL, corpus TEXT NOT NULL, version TEXT NOT NULL,
                metadata TEXT NOT NULL, sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                UNIQUE(feature, corpus, version)
            );
            CREATE TABLE IF NOT EXISTS chunks (
                feature TEXT NOT NULL, corpus TEXT NOT NULL, version TEXT NOT NULL,
                chunk_id TEXT NOT NULL, citation TEXT NOT NULL, vector TEXT NOT NULL,
                PRIMARY KEY(feature, corpus, version, chunk_id),
                FOREIGN KEY(feature, corpus, version)
                    REFERENCES versions(feature, corpus, version) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS active (
                feature TEXT NOT NULL, corpus TEXT NOT NULL, version TEXT NOT NULL,
                PRIMARY KEY(feature, corpus),
                FOREIGN KEY(feature, corpus, version)
                    REFERENCES versions(feature, corpus, version)
            );
        """)
        self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def check_scope(self, feature: str, corpus: str) -> None:
        if (feature, corpus) not in self.allowed_corpora:
            raise CorpusScopeDeniedError("Feature/corpus is not registered for public guidance")

    def current(self, feature: str, corpus: str) -> CorpusVersion | None:
        self.check_scope(feature, corpus)
        with self._lock:
            row = self._db.execute(
                "SELECT v.metadata FROM versions v JOIN active a "
                "ON v.feature=a.feature AND v.corpus=a.corpus AND v.version=a.version "
                "WHERE a.feature=? AND a.corpus=?",
                (feature, corpus),
            ).fetchone()
            return CorpusVersion.model_validate_json(row[0]) if row else None

    def ingest(self, request: CorpusIngestRequest) -> CorpusVersion:
        self.check_scope(request.feature_key, request.corpus_id)
        # R1 admits authored public guidance and clearly labelled fixtures only.
        if any(document.evidence_kind == "official" for document in request.documents):
            raise CorpusScopeDeniedError(
                "Official evidence requires a separately approved source adapter"
            )
        documents = sorted(
            (document.evolve(text=normalize(document.text)) for document in request.documents),
            key=lambda document: document.document_id,
        )
        fingerprint = {
            "request": request.evolve(documents=tuple(documents)).model_dump(mode="json"),
            "embedding_model": self.embedder.identity,
            "dimensions": self.embedder.dimensions,
            "strategy": STRATEGY,
        }
        version = hashlib.sha256(
            json.dumps(
                fingerprint, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode()
        ).hexdigest()
        with self._lock:
            current = self.current(request.feature_key, request.corpus_id)
            if current is not None and current.corpus_version == version:
                return current
            chunks = [
                (document, *chunk) for document in documents for chunk in chunk_document(document)
            ]
            if len(chunks) > 1000:
                raise ValueError("corpus exceeds 1000 chunks")
            vectors: list[list[float]] = []
            for start in range(0, len(chunks), 16):
                batch = chunks[start : start + 16]
                result = self.embedder.embed([chunk[2] for chunk in batch])
                if len(result) != len(batch):
                    raise ValueError("embedding batch returned an incorrect vector count")
                vectors.extend(
                    normalized_vector(vector, self.embedder.dimensions) for vector in result
                )
            metadata = CorpusVersion(
                feature_key=request.feature_key,
                corpus_id=request.corpus_id,
                corpus_version=version,
                document_count=len(documents),
                chunk_count=len(chunks),
                embedding_model=self.embedder.identity,
                embedding_dimensions=self.embedder.dimensions,
                ingested_at=self.clock(),
            )
            rows: list[tuple[Any, ...]] = []
            for (document, chunk_id, excerpt, location), vector in zip(
                chunks, vectors, strict=True
            ):
                citation = EvidenceCitation(
                    citation_id="cite-"
                    + hashlib.sha256(f"{version}:{chunk_id}".encode()).hexdigest(),
                    feature_key=request.feature_key,
                    corpus_id=request.corpus_id,
                    corpus_version=version,
                    document_id=document.document_id,
                    chunk_id=chunk_id,
                    title=document.title,
                    source_uri=document.source_uri,
                    content_hash=hashlib.sha256(excerpt.encode()).hexdigest(),
                    location=location,
                    ingested_at=metadata.ingested_at,
                    source_date=document.source_date,
                    evidence_kind=document.evidence_kind,
                    excerpt=excerpt,
                    score=0,
                )
                rows.append(
                    (
                        request.feature_key,
                        request.corpus_id,
                        version,
                        chunk_id,
                        citation.model_dump_json(),
                        json.dumps(vector),
                    )
                )
            with self._db:
                # Existing historical content can be reactivated without duplicate records.
                self._db.execute(
                    "DELETE FROM active WHERE feature=? AND corpus=?",
                    (request.feature_key, request.corpus_id),
                )
                self._db.execute(
                    "DELETE FROM versions WHERE feature=? AND corpus=? AND version=?",
                    (request.feature_key, request.corpus_id, version),
                )
                self._db.execute(
                    "INSERT INTO versions(feature,corpus,version,metadata) VALUES(?,?,?,?)",
                    (request.feature_key, request.corpus_id, version, metadata.model_dump_json()),
                )
                self._db.executemany("INSERT INTO chunks VALUES(?,?,?,?,?,?)", rows)
                self._db.execute(
                    "INSERT INTO active VALUES(?,?,?)",
                    (request.feature_key, request.corpus_id, version),
                )
                self._db.execute(
                    "DELETE FROM versions WHERE feature=? AND corpus=? AND sequence NOT IN "
                    "(SELECT sequence FROM versions WHERE feature=? AND corpus=? "
                    "ORDER BY sequence DESC LIMIT ?)",
                    (
                        request.feature_key,
                        request.corpus_id,
                        request.feature_key,
                        request.corpus_id,
                        self.retained_versions,
                    ),
                )
            return metadata

    def retrieve(self, request: RetrievalRequest) -> RetrievalResponse:
        self.check_scope(request.feature_key, request.corpus_id)
        with self._lock:
            current = self.current(request.feature_key, request.corpus_id)
            base: dict[str, Any] = {
                "feature_key": request.feature_key,
                "corpus_id": request.corpus_id,
                "corpus_version": current.corpus_version if current else None,
            }
            if current is None or current.chunk_count == 0:
                return RetrievalResponse(**base, status="empty", detail="No active source context")
            if current.embedding_model != self.embedder.identity:
                return RetrievalResponse(
                    **base,
                    status="unavailable",
                    detail="Reingest using the prepared embedding model",
                )
            try:
                vectors = self.embedder.embed([request.query], query=True)
                if len(vectors) != 1:
                    raise ValueError("query requires exactly one vector")
                query = normalized_vector(vectors[0], self.embedder.dimensions)
            except (EmbeddingUnavailableError, ValueError):
                return RetrievalResponse(
                    **base, status="unavailable", detail="Local embedding dependency unavailable"
                )
            rows = self._db.execute(
                "SELECT citation,vector FROM chunks WHERE feature=? AND corpus=? AND version=?",
                (request.feature_key, request.corpus_id, current.corpus_version),
            ).fetchall()
            ranked: list[EvidenceCitation] = []
            for row in rows:
                citation = EvidenceCitation.model_validate_json(row[0])
                if request.document_ids and citation.document_id not in request.document_ids:
                    continue
                vector = normalized_vector(json.loads(row[1]), self.embedder.dimensions)
                score = max(-1.0, min(1.0, sum(a * b for a, b in zip(query, vector, strict=True))))
                if score >= request.min_score:
                    ranked.append(citation.evolve(score=score))
            ranked.sort(key=lambda citation: (-citation.score, citation.chunk_id))
            selected: list[EvidenceCitation] = []
            remaining = request.max_context_chars
            for citation in ranked:
                if len(citation.excerpt) > remaining:
                    continue  # Never truncate an excerpt while retaining its full-content hash.
                selected.append(citation)
                remaining -= len(citation.excerpt)
                if len(selected) >= request.top_k:
                    break
            return RetrievalResponse(
                **base,
                status="ready" if selected else "no_match",
                citations=tuple(selected),
                detail="Similarity measures retrieval relevance, not factual confidence",
            )
