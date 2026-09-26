"""Exclusive service-owned SQLite index with transactional complete-batch activation."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import unicodedata
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rag_server.embeddings import Embedder, EmbeddingUnavailableError, normalized_vector
from rag_server.ranking import MAX_CHUNKS_PER_DOCUMENT, bm25_scores, fused_order
from shared_contracts.retrieval import (
    CorpusContents,
    CorpusDocument,
    CorpusIngestRequest,
    CorpusVersion,
    EvidenceCitation,
    RetrievalRequest,
    RetrievalResponse,
)

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 120
MIN_SECTION_CHUNK = 400
STRATEGY = "unicode-nfc-markdown-sections-char1200-overlap120-titled-v2"
HEADING = re.compile(r"^#{1,6}[ \t]+(.+?)[ \t#]*$", re.MULTILINE)


def normalize(text: str) -> str:
    return unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n")).strip()


@dataclass(frozen=True)
class Chunk:
    """An exact excerpt of normalized text plus the context used only for its vector."""

    chunk_id: str
    excerpt: str
    location: str
    section: str
    embedding_text: str


def _sections(text: str) -> list[tuple[int, int, str]]:
    """Tile the text into (start, end, heading) spans that each begin at a Markdown heading."""
    headings = [(match.start(), match.group(1).strip()) for match in HEADING.finditer(text)]
    if not headings or headings[0][0] != 0:
        headings.insert(0, (0, ""))
    bounds = [start for start, _ in headings[1:]] + [len(text)]
    return [(start, end, heading) for (start, heading), end in zip(headings, bounds, strict=True)]


def _windows(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Split one oversized section, preferring paragraph breaks, with bounded overlap."""
    spans: list[tuple[int, int]] = []
    while end - start > CHUNK_SIZE:
        limit = start + CHUNK_SIZE
        cut = text.rfind("\n\n", start + CHUNK_SIZE // 2, limit)
        cut = cut if cut > start else limit
        spans.append((start, cut))
        start = max(cut - CHUNK_OVERLAP, start + 1) if cut == limit else cut
    spans.append((start, end))
    return spans


def chunk_document(document: CorpusDocument) -> list[Chunk]:
    """Chunk by Markdown section so a heading stays with the text it introduces.

    Small adjacent sections are packed together up to ``MIN_SECTION_CHUNK`` characters;
    a section longer than ``CHUNK_SIZE`` is windowed at paragraph breaks where possible.
    Excerpts remain exact normalized substrings with one-based positions. The document
    title and section heading are prepended to the embedded text only, which lets short
    sections match questions phrased in terms of the document's subject.
    """
    text = normalize(document.text)
    packed: list[tuple[int, int, str]] = []
    for start, end, heading in _sections(text):
        if packed and packed[-1][1] - packed[-1][0] < MIN_SECTION_CHUNK:
            previous_start, _, previous_heading = packed[-1]
            if end - previous_start <= CHUNK_SIZE:
                packed[-1] = (previous_start, end, previous_heading or heading)
                continue
        packed.append((start, end, heading))
    chunks: list[Chunk] = []
    for section_start, section_end, heading in packed:
        for start, end in _windows(text, section_start, section_end):
            raw = text[start:end]
            excerpt = raw.strip()
            if not excerpt:
                continue
            start += len(raw) - len(raw.lstrip())
            section = heading if heading and heading != document.title else ""
            parts = [document.location] if document.location else []
            if section:
                parts.append(f"section {section[:80]}")
            parts.append(f"chars {start + 1}-{start + len(excerpt)}")
            context = f"{document.title} - {section}" if section else document.title
            chunks.append(
                Chunk(
                    chunk_id=hashlib.sha256(f"{document.document_id}:{start}".encode()).hexdigest(),
                    excerpt=excerpt,
                    location="; ".join(parts),
                    section=section,
                    embedding_text=f"{context}\n\n{excerpt}",
                )
            )
    return chunks


def _position(location: str) -> int:
    match = re.search(r"chars (\d+)-\d+$", location)
    return int(match.group(1)) if match else 0


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

    def contents(self, feature: str, corpus: str) -> CorpusContents | None:
        """List the active version's chunks in document and position order."""
        self.check_scope(feature, corpus)
        with self._lock:
            current = self.current(feature, corpus)
            if current is None:
                return None
            rows = self._db.execute(
                "SELECT citation FROM chunks WHERE feature=? AND corpus=? AND version=?",
                (feature, corpus, current.corpus_version),
            ).fetchall()
        chunks = [EvidenceCitation.model_validate_json(row[0]) for row in rows]
        chunks.sort(key=lambda chunk: (chunk.document_id, _position(chunk.location)))
        return CorpusContents(version=current, chunks=tuple(chunks))

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
            retained = self._db.execute(
                "SELECT metadata FROM versions WHERE feature=? AND corpus=? AND version=?",
                (request.feature_key, request.corpus_id, version),
            ).fetchone()
            if retained is not None:
                metadata = CorpusVersion.model_validate_json(retained[0])
                with self._db:
                    self._db.execute(
                        "INSERT INTO active VALUES(?,?,?) ON CONFLICT(feature,corpus) "
                        "DO UPDATE SET version=excluded.version",
                        (request.feature_key, request.corpus_id, version),
                    )
                return metadata
            chunks = [
                (document, chunk) for document in documents for chunk in chunk_document(document)
            ]
            if len(chunks) > 1000:
                raise ValueError("corpus exceeds 1000 chunks")
            vectors: list[list[float]] = []
            for start in range(0, len(chunks), 16):
                batch = chunks[start : start + 16]
                result = self.embedder.embed([chunk.embedding_text for _, chunk in batch])
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
            for (document, chunk), vector in zip(chunks, vectors, strict=True):
                citation = EvidenceCitation(
                    citation_id="cite-"
                    + hashlib.sha256(f"{version}:{chunk.chunk_id}".encode()).hexdigest(),
                    feature_key=request.feature_key,
                    corpus_id=request.corpus_id,
                    corpus_version=version,
                    document_id=document.document_id,
                    chunk_id=chunk.chunk_id,
                    title=document.title,
                    source_uri=document.source_uri,
                    content_hash=hashlib.sha256(chunk.excerpt.encode()).hexdigest(),
                    location=chunk.location,
                    ingested_at=metadata.ingested_at,
                    source_date=document.source_date,
                    evidence_kind=document.evidence_kind,
                    excerpt=chunk.excerpt,
                    score=0,
                )
                rows.append(
                    (
                        request.feature_key,
                        request.corpus_id,
                        version,
                        chunk.chunk_id,
                        citation.model_dump_json(),
                        json.dumps(vector),
                    )
                )
            with self._db:
                # New content is committed atomically; retained versions are reused above.
                self._db.execute(
                    "DELETE FROM active WHERE feature=? AND corpus=?",
                    (request.feature_key, request.corpus_id),
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
            candidates: list[EvidenceCitation] = []
            for row in sorted(rows, key=lambda row: str(row[0])):
                citation = EvidenceCitation.model_validate_json(row[0])
                if request.document_ids and citation.document_id not in request.document_ids:
                    continue
                vector = normalized_vector(json.loads(row[1]), self.embedder.dimensions)
                score = max(-1.0, min(1.0, sum(a * b for a, b in zip(query, vector, strict=True))))
                candidates.append(citation.evolve(score=score))
            keyword = bm25_scores(
                request.query,
                [f"{item.title} {item.location} {item.excerpt}" for item in candidates],
            )
            ranked = [
                candidates[index]
                for index in fused_order([item.score for item in candidates], keyword)
                if candidates[index].score >= request.min_score
            ]
            selected: list[EvidenceCitation] = []
            per_document: Counter[str] = Counter()
            remaining = request.max_context_chars
            for citation in ranked:
                if len(citation.excerpt) > remaining:
                    continue  # Never truncate an excerpt while retaining its full-content hash.
                if per_document[citation.document_id] >= MAX_CHUNKS_PER_DOCUMENT:
                    continue  # Leave room for other documents that address the question.
                selected.append(citation)
                per_document[citation.document_id] += 1
                remaining -= len(citation.excerpt)
                if len(selected) >= request.top_k:
                    break
            return RetrievalResponse(
                **base,
                status="ready" if selected else "no_match",
                citations=tuple(selected),
                detail="Similarity measures retrieval relevance, not factual confidence",
            )
