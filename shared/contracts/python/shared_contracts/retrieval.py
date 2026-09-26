"""Versioned, bounded public-context ingestion and retrieval wire contracts."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import AwareDatetime, Field, field_validator, model_validator

from shared_contracts.base import ContractModel

RetrievalIdentifier = Annotated[
    str, Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9_.-]*$")
]
ContentHash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
EvidenceKind = Literal["project_guidance", "fixture", "official"]


def validate_source_uri(value: str) -> str:
    """Allow display-only HTTP(S) references, never credentials or executable schemes."""
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or any(ord(character) < 33 for character in value)
        or "\\" in value
    ):
        raise ValueError("source_uri must be an HTTP(S) URL without credentials or whitespace")
    return value


class CorpusDocument(ContractModel):
    """A normalized document supplied by its owning feature; URLs are never fetched."""

    document_id: RetrievalIdentifier
    title: str = Field(min_length=1, max_length=240)
    source_uri: str = Field(min_length=1, max_length=2048)
    text: str = Field(min_length=1, max_length=60000)
    source_date: date | None = None
    license: str = Field(min_length=1, max_length=200)
    status: Literal["active"] = "active"
    access_class: Literal["public_project_guidance"] = "public_project_guidance"
    evidence_kind: EvidenceKind = "project_guidance"
    location: str = Field(default="", max_length=200)

    _source_uri = field_validator("source_uri")(validate_source_uri)

    @field_validator("text", "title", "license")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("document text and metadata must not be blank")
        return value


class CorpusIngestRequest(ContractModel):
    """Complete replacement; an empty document batch explicitly withdraws a corpus."""

    schema_version: Literal["1.0"] = "1.0"
    feature_key: RetrievalIdentifier
    corpus_id: RetrievalIdentifier
    documents: tuple[CorpusDocument, ...] = Field(max_length=200)

    @model_validator(mode="after")
    def bounded_unique_batch(self) -> Self:
        identifiers = [document.document_id for document in self.documents]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("document IDs must be unique within a complete batch")
        if sum(len(document.text) for document in self.documents) > 500000:
            raise ValueError("complete document batch exceeds 500000 characters")
        return self


class CorpusVersion(ContractModel):
    """Immutable activated corpus identity, including embedding/preprocessing identity."""

    schema_version: Literal["1.0"] = "1.0"
    feature_key: RetrievalIdentifier
    corpus_id: RetrievalIdentifier
    corpus_version: ContentHash
    document_count: int = Field(ge=0, le=200)
    chunk_count: int = Field(ge=0, le=1000)
    embedding_model: str = Field(min_length=1, max_length=300)
    embedding_dimensions: int = Field(ge=1, le=4096)
    ingested_at: AwareDatetime


class EvidenceCitation(ContractModel):
    """Self-contained untrusted source excerpt pinned to one complete corpus version."""

    citation_id: RetrievalIdentifier
    feature_key: RetrievalIdentifier
    corpus_id: RetrievalIdentifier
    corpus_version: ContentHash
    document_id: RetrievalIdentifier
    chunk_id: RetrievalIdentifier
    title: str = Field(min_length=1, max_length=240)
    source_uri: str = Field(min_length=1, max_length=2048)
    content_hash: ContentHash
    location: str = Field(min_length=1, max_length=300)
    ingested_at: AwareDatetime
    source_date: date | None = None
    evidence_kind: EvidenceKind
    excerpt: str = Field(min_length=1, max_length=1600)
    score: float = Field(ge=-1, le=1, allow_inf_nan=False)

    _source_uri = field_validator("source_uri")(validate_source_uri)


class CorpusContents(ContractModel):
    """Every chunk of the active corpus version, for operator inspection and debugging.

    Chunks carry ``score=0``: no query was ranked. Ordering is by document ID, then
    position, so the listing is stable for a given version.
    """

    schema_version: Literal["1.0"] = "1.0"
    version: CorpusVersion
    chunks: tuple[EvidenceCitation, ...] = Field(default=(), max_length=1000)

    @model_validator(mode="after")
    def chunks_match_version(self) -> Self:
        if len(self.chunks) != self.version.chunk_count:
            raise ValueError("contents must list every chunk of the active version")
        for chunk in self.chunks:
            if (chunk.feature_key, chunk.corpus_id, chunk.corpus_version) != (
                self.version.feature_key,
                self.version.corpus_id,
                self.version.corpus_version,
            ):
                raise ValueError("chunk scope/version must match the listed version")
        return self


class RetrievalRequest(ContractModel):
    """A bounded query for one registered corpus; filters cannot widen feature scope."""

    schema_version: Literal["1.0"] = "1.0"
    feature_key: RetrievalIdentifier
    corpus_id: RetrievalIdentifier
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=10)
    max_context_chars: int = Field(default=5000, ge=100, le=12000)
    min_score: float = Field(default=0.35, ge=0, le=1, allow_inf_nan=False)
    document_ids: tuple[RetrievalIdentifier, ...] = Field(default=(), max_length=200)

    @field_validator("query")
    @classmethod
    def nonblank_query(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be blank")
        return value


class RetrievalResponse(ContractModel):
    """Explicit outcomes distinguish absent context from a failed retrieval dependency."""

    schema_version: Literal["1.0"] = "1.0"
    feature_key: RetrievalIdentifier
    corpus_id: RetrievalIdentifier
    status: Literal["ready", "no_match", "empty", "unavailable"]
    corpus_version: ContentHash | None = None
    citations: tuple[EvidenceCitation, ...] = Field(default=(), max_length=10)
    detail: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def consistent_evidence(self) -> Self:
        if (self.status == "ready") != bool(self.citations):
            raise ValueError("only ready retrieval may contain citations and it requires evidence")
        if self.status in {"ready", "no_match"} and self.corpus_version is None:
            raise ValueError("retrieval must pin the searched corpus version")
        ids = [citation.citation_id for citation in self.citations]
        if len(ids) != len(set(ids)):
            raise ValueError("citation IDs must be unique")
        for citation in self.citations:
            if (citation.feature_key, citation.corpus_id, citation.corpus_version) != (
                self.feature_key,
                self.corpus_id,
                self.corpus_version,
            ):
                raise ValueError("citation scope/version must match retrieval scope/version")
        return self
