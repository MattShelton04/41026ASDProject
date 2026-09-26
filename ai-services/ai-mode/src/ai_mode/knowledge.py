"""Read-only corpus inspection for the operations interface.

Operators and feature owners use this to see what each registered corpus contains and to test
how a question ranks against it, using the same relevance limits as grounded runs. Requests go
to the RAG service with AI-mode's own token; the browser never receives that token, and only
corpora registered with AI-mode can be named.
"""

from __future__ import annotations

from collections.abc import Callable
from time import monotonic
from typing import Any

import httpx
from flask import Blueprint, Response, jsonify, request
from pydantic import ValidationError

from ai_mode.http import problem_response as _problem
from shared_contracts.grounding import (
    GROUNDING_MAX_CONTEXT_CHARS,
    GROUNDING_MIN_SCORE,
    GROUNDING_TOP_K,
)
from shared_contracts.retrieval import (
    CorpusContents,
    CorpusVersion,
    RetrievalRequest,
    RetrievalResponse,
)

MAX_CONTENTS_BYTES = 4 * 1024 * 1024
MAX_SEARCH_BYTES = 64_000
MAX_VERSION_BYTES = 10_000
TIMEOUT_SECONDS = 5.0
DIAGNOSTIC_TOP_K = 10


class KnowledgeUnavailableError(RuntimeError):
    """The RAG service did not return a valid bounded response."""


class KnowledgeClient:
    """Bounded, authenticated reads from the RAG service."""

    def __init__(
        self,
        *,
        base_url: str,
        service_token: str,
        client: httpx.Client | None = None,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = service_token
        self.client = client or httpx.Client(follow_redirects=False)
        self._owns_client = client is None
        self._clock = clock

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def version(self, feature: str, corpus: str) -> CorpusVersion | None:
        raw = self._read("GET", f"/api/v1/corpora/{feature}/{corpus}", MAX_VERSION_BYTES)
        return None if raw is None else CorpusVersion.model_validate_json(raw)

    def contents(self, feature: str, corpus: str) -> CorpusContents | None:
        raw = self._read("GET", f"/api/v1/corpora/{feature}/{corpus}/chunks", MAX_CONTENTS_BYTES)
        return None if raw is None else CorpusContents.model_validate_json(raw)

    def retrieve(self, query: RetrievalRequest) -> RetrievalResponse:
        raw = self._read(
            "POST", "/api/v1/retrieve", MAX_SEARCH_BYTES, json=query.model_dump(mode="json")
        )
        if raw is None:
            raise KnowledgeUnavailableError("retrieval returned no result")
        return RetrievalResponse.model_validate_json(raw)

    def _read(self, method: str, path: str, limit: int, **kwargs: Any) -> bytes | None:
        deadline = self._clock() + TIMEOUT_SECONDS
        try:
            with self.client.stream(
                method,
                self.base_url + path,
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=TIMEOUT_SECONDS,
                **kwargs,
            ) as response:
                if response.status_code == 404:
                    return None
                if response.status_code != 200:
                    raise KnowledgeUnavailableError(f"RAG returned HTTP {response.status_code}")
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > limit or self._clock() > deadline:
                        raise KnowledgeUnavailableError("RAG response exceeded its bounds")
                return bytes(raw)
        except httpx.HTTPError as exc:
            raise KnowledgeUnavailableError("RAG service is unreachable") from exc


def grounding_limits() -> dict[str, float | int]:
    return {
        "top_k": GROUNDING_TOP_K,
        "max_context_chars": GROUNDING_MAX_CONTEXT_CHARS,
        "min_score": GROUNDING_MIN_SCORE,
    }


def create_knowledge_blueprint(
    client: KnowledgeClient | None, corpora: tuple[tuple[str, str], ...]
) -> Blueprint:
    """Expose registered corpora; a disabled RAG service reports that state, not an error."""
    blueprint = Blueprint("ai_mode_knowledge", __name__)
    registered = frozenset(corpora)

    @blueprint.get("/api/v1/operations/knowledge")
    def list_corpora() -> tuple[Response, int]:
        knowledge = client
        items: list[dict[str, object]] = []
        for feature, corpus in corpora:
            item: dict[str, object] = {"feature_key": feature, "corpus_id": corpus}
            if knowledge is None:
                item.update(status="disabled", version=None)
            else:
                try:
                    version = knowledge.version(feature, corpus)
                    item.update(
                        status="ready" if version else "empty",
                        version=version.model_dump(mode="json") if version else None,
                    )
                except (KnowledgeUnavailableError, ValidationError):
                    item.update(status="unavailable", version=None)
            items.append(item)
        return jsonify(
            {
                "enabled": knowledge is not None,
                "grounding": grounding_limits(),
                "corpora": items,
            }
        ), 200

    @blueprint.get("/api/v1/operations/knowledge/<feature>/<corpus>/chunks")
    def corpus_chunks(feature: str, corpus: str) -> tuple[Response, int]:
        knowledge = client
        if (feature, corpus) not in registered:
            return _problem(404, "corpus_not_registered", "Corpus is not registered with AI-mode")
        if knowledge is None:
            return _problem(503, "retrieval_disabled", "Document retrieval is disabled")
        try:
            contents = knowledge.contents(feature, corpus)
        except (KnowledgeUnavailableError, ValidationError):
            return _problem(503, "retrieval_unavailable", "Document retrieval is unavailable")
        if contents is None:
            return _problem(404, "corpus_empty", "The registered corpus has not been ingested")
        response = jsonify(contents.model_dump(mode="json"))
        response.headers["Cache-Control"] = "private, no-cache"
        return response, 200

    @blueprint.get("/api/v1/operations/knowledge/<feature>/<corpus>/search")
    def corpus_search(feature: str, corpus: str) -> tuple[Response, int]:
        knowledge = client
        if (feature, corpus) not in registered:
            return _problem(404, "corpus_not_registered", "Corpus is not registered with AI-mode")
        if knowledge is None:
            return _problem(503, "retrieval_disabled", "Document retrieval is disabled")
        text = request.args.get("q", "")
        try:
            grounded = RetrievalRequest(
                feature_key=feature,
                corpus_id=corpus,
                query=text,
                top_k=GROUNDING_TOP_K,
                max_context_chars=GROUNDING_MAX_CONTEXT_CHARS,
                min_score=GROUNDING_MIN_SCORE,
            )
        except ValidationError:
            return _problem(400, "query_invalid", "Enter a question of 1-2000 characters")
        diagnostic = grounded.evolve(top_k=DIAGNOSTIC_TOP_K, max_context_chars=12000, min_score=0)
        try:
            used = knowledge.retrieve(grounded)
            ranked = knowledge.retrieve(diagnostic)
        except (KnowledgeUnavailableError, ValidationError):
            return _problem(503, "retrieval_unavailable", "Document retrieval is unavailable")
        selected = {citation.chunk_id for citation in used.citations}
        return jsonify(
            {
                "query": text,
                "grounding": grounding_limits(),
                "status": used.status,
                "corpus_version": used.corpus_version,
                "detail": used.detail,
                "candidates": [
                    {
                        **citation.model_dump(mode="json"),
                        "used_in_grounding": citation.chunk_id in selected,
                    }
                    for citation in ranked.citations
                ],
            }
        ), 200

    return blueprint
