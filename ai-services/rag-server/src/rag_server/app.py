"""Authenticated bounded Flask adapter; neither URLs nor feature databases are opened."""

from __future__ import annotations

import hmac
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from flask import Flask, Response, jsonify, request
from pydantic import ValidationError
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge, UnsupportedMediaType

from rag_server.embeddings import (
    Embedder,
    EmbeddingUnavailableError,
    FixtureEmbedder,
    LocalEmbedder,
    UnavailableEmbedder,
)
from rag_server.index import CorpusIndex, CorpusScopeDeniedError
from shared_contracts.retrieval import CorpusIngestRequest, RetrievalRequest

DEFAULT_SCOPE = "student-1-propertyscope-data-platform:operator-guidance"


@dataclass(frozen=True)
class RagSettings:
    token: str
    database_path: str = ".propertyscope-runtime/host/rag/index.sqlite3"
    model_cache_path: Path = Path(".propertyscope-runtime/host/rag/models")
    embedding_mode: str = "semantic"
    allowed_corpora: frozenset[tuple[str, str]] = frozenset(
        {("student-1-propertyscope-data-platform", "operator-guidance")}
    )

    def __post_init__(self) -> None:
        if len(self.token) < 16:
            raise ValueError("RAG_SERVICE_TOKEN must contain at least 16 characters")
        if self.embedding_mode not in {"semantic", "fixture"}:
            raise ValueError("RAG_EMBEDDING_MODE must be semantic or fixture")
        if not 1 <= len(self.allowed_corpora) <= 20:
            raise ValueError("RAG_ALLOWED_CORPORA must register 1-20 bounded corpora")
        for feature, corpus in self.allowed_corpora:
            RetrievalRequest(feature_key=feature, corpus_id=corpus, query="configuration")

    @classmethod
    def from_environment(cls) -> RagSettings:
        pairs = os.getenv("RAG_ALLOWED_CORPORA", DEFAULT_SCOPE).split(",")
        allowed: set[tuple[str, str]] = set()
        for pair in pairs:
            parts = pair.strip().split(":")
            if len(parts) != 2:
                raise ValueError("RAG_ALLOWED_CORPORA requires feature:corpus pairs")
            allowed.add((parts[0], parts[1]))
        return cls(
            token=os.getenv("RAG_SERVICE_TOKEN", ""),
            database_path=os.getenv(
                "RAG_DATABASE_PATH", ".propertyscope-runtime/host/rag/index.sqlite3"
            ),
            model_cache_path=Path(
                os.getenv("RAG_MODEL_CACHE_PATH", ".propertyscope-runtime/host/rag/models")
            ),
            embedding_mode=os.getenv("RAG_EMBEDDING_MODE", "semantic"),
            allowed_corpora=frozenset(allowed),
        )


def create_app(
    settings: RagSettings | None = None,
    *,
    embedder: Embedder | None = None,
    index: CorpusIndex | None = None,
) -> Flask:
    settings = settings or RagSettings.from_environment()
    if embedder is None:
        if settings.embedding_mode == "fixture":
            embedder = FixtureEmbedder()
        else:
            try:
                embedder = LocalEmbedder(settings.model_cache_path)
            except EmbeddingUnavailableError:
                embedder = UnavailableEmbedder()
    index = index or CorpusIndex(settings.database_path, embedder, settings.allowed_corpora)
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
    app.extensions["rag_index"] = index
    app.extensions["rag_settings"] = settings

    def problem(status: int, code: str, detail: str) -> tuple[Response, int]:
        response = jsonify(
            {
                "type": f"urn:propertyscope:rag:{code}",
                "title": code,
                "status": status,
                "detail": detail,
            }
        )
        response.content_type = "application/problem+json"
        return response, status

    @app.before_request
    def authorize() -> tuple[Response, int] | None:
        if request.path == "/health/live":
            return None
        authorization = request.headers.get("Authorization", "")
        if not hmac.compare_digest(authorization.encode(), f"Bearer {settings.token}".encode()):
            return problem(401, "unauthorized", "Valid service authentication is required")
        return None

    @app.get("/health/live")
    def live() -> Response:
        return jsonify({"status": "ok", "service": "rag-server"})

    @app.get("/health/ready")
    def ready() -> tuple[Response, int]:
        available = not isinstance(index.embedder, UnavailableEmbedder)
        return jsonify(
            {
                "status": "ok" if available else "unavailable",
                "service": "rag-server",
                "embedding_mode": settings.embedding_mode,
                "embedding_model": index.embedder.identity,
            }
        ), 200 if available else 503

    @app.post("/api/v1/corpora/ingest")
    def ingest() -> Response:
        payload = CorpusIngestRequest.model_validate(request.get_json())
        return jsonify(index.ingest(payload).model_dump(mode="json"))

    @app.post("/api/v1/retrieve")
    def retrieve() -> Response:
        payload = RetrievalRequest.model_validate(request.get_json())
        return jsonify(index.retrieve(payload).model_dump(mode="json"))

    @app.get("/api/v1/corpora/<feature>/<corpus>")
    def current(feature: str, corpus: str) -> Response | tuple[Response, int]:
        version = index.current(feature, corpus)
        if version is None:
            return problem(404, "corpus_empty", "The registered corpus has not been ingested")
        return jsonify(version.model_dump(mode="json"))

    @app.errorhandler(CorpusScopeDeniedError)
    def denied(error: CorpusScopeDeniedError) -> tuple[Response, int]:
        return problem(403, "scope_denied", str(error))

    @app.errorhandler(ValidationError)
    @app.errorhandler(ValueError)
    @app.errorhandler(BadRequest)
    @app.errorhandler(UnsupportedMediaType)
    def invalid(error: Exception) -> tuple[Response, int]:
        return problem(400, "invalid_request", "Request violates the bounded retrieval contract")

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(error: Exception) -> tuple[Response, int]:
        return problem(413, "request_too_large", "Request body exceeds 2 MiB")

    @app.errorhandler(EmbeddingUnavailableError)
    @app.errorhandler(sqlite3.Error)
    def unavailable(error: Exception) -> tuple[Response, int]:
        return problem(503, "retrieval_unavailable", "Local retrieval dependency unavailable")

    return app
