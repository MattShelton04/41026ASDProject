"""Authenticated bounded Flask adapter; neither URLs nor feature databases are opened."""

from __future__ import annotations

import hmac
import logging
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from uuid import UUID, uuid4

from flask import Flask, Response, g, jsonify, request
from pydantic import ValidationError
from werkzeug.exceptions import (
    BadRequest,
    HTTPException,
    RequestEntityTooLarge,
    UnsupportedMediaType,
)

from rag_server.embeddings import (
    Embedder,
    EmbeddingUnavailableError,
    FixtureEmbedder,
    LocalEmbedder,
    UnavailableEmbedder,
)
from rag_server.index import CorpusIndex, CorpusScopeDeniedError
from rag_server.observability import SUPPORTED_LOG_LEVELS, configure_structured_logging
from shared_contracts import AGENT_RUN_ID_HEADER, REQUEST_ID_HEADER, is_valid_request_id
from shared_contracts.retrieval import CorpusIngestRequest, RetrievalRequest

DEFAULT_SCOPE = "student-1-propertyscope-data-platform:operator-guidance"
LOGGER = logging.getLogger(__name__)
MAX_LOGGED_PATH_CHARS = 200


@dataclass(frozen=True)
class RagSettings:
    token: str
    database_path: str = ".propertyscope-runtime/host/rag/index.sqlite3"
    model_cache_path: Path = Path(".propertyscope-runtime/host/rag/models")
    embedding_mode: str = "semantic"
    allowed_corpora: frozenset[tuple[str, str]] = frozenset(
        {("student-1-propertyscope-data-platform", "operator-guidance")}
    )
    official_evidence_corpora: frozenset[tuple[str, str]] = frozenset()
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        if len(self.token) < 16:
            raise ValueError("RAG_SERVICE_TOKEN must contain at least 16 characters")
        if self.embedding_mode not in {"semantic", "fixture"}:
            raise ValueError("RAG_EMBEDDING_MODE must be semantic or fixture")
        if not 1 <= len(self.allowed_corpora) <= 20:
            raise ValueError("RAG_ALLOWED_CORPORA must register 1-20 bounded corpora")
        for feature, corpus in self.allowed_corpora:
            RetrievalRequest(feature_key=feature, corpus_id=corpus, query="configuration")
        if not self.official_evidence_corpora.issubset(self.allowed_corpora):
            raise ValueError(
                "RAG_OFFICIAL_EVIDENCE_CORPORA must be registered in RAG_ALLOWED_CORPORA"
            )
        if self.log_level not in SUPPORTED_LOG_LEVELS:
            raise ValueError("RAG_LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL")

    @classmethod
    def from_environment(cls) -> RagSettings:
        pairs = os.getenv("RAG_ALLOWED_CORPORA", DEFAULT_SCOPE).split(",")
        allowed: set[tuple[str, str]] = set()
        for pair in pairs:
            parts = pair.strip().split(":")
            if len(parts) != 2:
                raise ValueError("RAG_ALLOWED_CORPORA requires feature:corpus pairs")
            allowed.add((parts[0], parts[1]))
        official: set[tuple[str, str]] = set()
        for pair in filter(None, os.getenv("RAG_OFFICIAL_EVIDENCE_CORPORA", "").split(",")):
            parts = pair.strip().split(":")
            if len(parts) != 2:
                raise ValueError("RAG_OFFICIAL_EVIDENCE_CORPORA requires feature:corpus pairs")
            official.add((parts[0], parts[1]))
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
            official_evidence_corpora=frozenset(official),
            log_level=os.getenv("RAG_LOG_LEVEL", "INFO").strip().upper(),
        )


def create_app(
    settings: RagSettings | None = None,
    *,
    embedder: Embedder | None = None,
    index: CorpusIndex | None = None,
) -> Flask:
    if settings is None:
        settings = RagSettings.from_environment()
        configure_structured_logging(settings.log_level)
    if embedder is None:
        if settings.embedding_mode == "fixture":
            embedder = FixtureEmbedder()
        else:
            try:
                embedder = LocalEmbedder(settings.model_cache_path)
            except EmbeddingUnavailableError:
                embedder = UnavailableEmbedder()
    index = index or CorpusIndex(
        settings.database_path,
        embedder,
        settings.allowed_corpora,
        official_evidence_corpora=settings.official_evidence_corpora,
    )
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
    app.extensions["rag_index"] = index
    app.extensions["rag_settings"] = settings

    def problem(status: int, code: str, detail: str) -> tuple[Response, int]:
        g.error_code = code
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

    def scope(feature: str, corpus: str) -> None:
        """Record a corpus scope for the request log, only once it is a registered pair."""
        if (feature, corpus) in settings.allowed_corpora:
            g.feature_key, g.corpus_id = feature, corpus

    @app.before_request
    def correlate() -> None:
        g.request_started = monotonic()
        supplied = request.headers.get(REQUEST_ID_HEADER, "").strip()
        g.request_id = supplied if is_valid_request_id(supplied) else str(uuid4())
        try:
            g.run_id = str(UUID(request.headers.get(AGENT_RUN_ID_HEADER, "")))
        except ValueError:
            g.run_id = None

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
        g.feature_key, g.corpus_id = payload.feature_key, payload.corpus_id
        g.document_count = len(payload.documents)
        version = index.ingest(payload)
        g.chunk_count = version.chunk_count
        return jsonify(version.model_dump(mode="json"))

    @app.post("/api/v1/retrieve")
    def retrieve() -> Response:
        payload = RetrievalRequest.model_validate(request.get_json())
        g.feature_key, g.corpus_id = payload.feature_key, payload.corpus_id
        result = index.retrieve(payload)
        g.retrieval_status, g.result_count = result.status, len(result.citations)
        return jsonify(result.model_dump(mode="json"))

    @app.get("/api/v1/corpora/<feature>/<corpus>")
    def current(feature: str, corpus: str) -> Response | tuple[Response, int]:
        scope(feature, corpus)
        version = index.current(feature, corpus)
        if version is None:
            return problem(404, "corpus_empty", "The registered corpus has not been ingested")
        g.document_count, g.chunk_count = version.document_count, version.chunk_count
        return jsonify(version.model_dump(mode="json"))

    @app.get("/api/v1/corpora/<feature>/<corpus>/chunks")
    def chunks(feature: str, corpus: str) -> Response | tuple[Response, int]:
        scope(feature, corpus)
        contents = index.contents(feature, corpus)
        if contents is None:
            return problem(404, "corpus_empty", "The registered corpus has not been ingested")
        g.result_count = len(contents.chunks)
        return jsonify(contents.model_dump(mode="json"))

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

    @app.errorhandler(Exception)
    def unexpected(error: Exception) -> HTTPException | tuple[Response, int]:
        if isinstance(error, HTTPException):
            g.error_code = (error.name or "http_error").lower().replace(" ", "_")
            return error
        return problem(500, "internal_error", "The request could not be completed")

    @app.after_request
    def include_request_id(response: Response) -> Response:
        response.headers[REQUEST_ID_HEADER] = g.request_id
        g.response_status = response.status_code
        return response

    @app.teardown_request
    def log_request(error: BaseException | None) -> None:
        """Write exactly one line per request, including requests that raised past Flask."""
        status_code = 500 if error is not None else g.get("response_status", 500)
        path = request.url_rule.rule if request.url_rule is not None else request.path
        started: float = g.get("request_started", monotonic())
        LOGGER.log(
            logging.ERROR if status_code >= 500 else logging.INFO,
            "HTTP request completed",
            exc_info=error,
            extra={
                "event": "http.request.completed",
                "request_id": g.get("request_id"),
                "run_id": g.get("run_id"),
                "feature_key": g.get("feature_key"),
                "outcome": "failure" if status_code >= 400 else "success",
                "duration_ms": max(0, int((monotonic() - started) * 1_000)),
                "error_code": g.get("error_code", "internal_error" if error else None),
                "status_code": status_code,
                "method": request.method,
                "path": path[:MAX_LOGGED_PATH_CHARS],
                "corpus_id": g.get("corpus_id"),
                "retrieval_status": g.get("retrieval_status"),
                "result_count": g.get("result_count"),
                "document_count": g.get("document_count"),
                "chunk_count": g.get("chunk_count"),
            },
        )

    return app
