"""Corpus inspection routes against a mocked RAG transport; no service is started."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import httpx
import pytest
from flask import Flask

from ai_mode.knowledge import KnowledgeClient, create_knowledge_blueprint
from shared_contracts.grounding import GROUNDING_MIN_SCORE, GROUNDING_TOP_K
from shared_testkit import assert_problem_detail

FEATURE = "student-9-example"
CORPUS = "guidance"
VERSION = "a" * 64
INGESTED = datetime(2026, 9, 26, tzinfo=UTC).isoformat()


def citation(chunk: str, score: float) -> dict[str, object]:
    excerpt = f"Excerpt for {chunk}."
    return {
        "citation_id": f"cite-{chunk}",
        "feature_key": FEATURE,
        "corpus_id": CORPUS,
        "corpus_version": VERSION,
        "document_id": chunk,
        "chunk_id": chunk,
        "title": chunk.title(),
        "source_uri": "https://example.org/guide",
        "content_hash": hashlib.sha256(excerpt.encode()).hexdigest(),
        "location": "chars 1-20",
        "ingested_at": INGESTED,
        "evidence_kind": "project_guidance",
        "excerpt": excerpt,
        "score": score,
    }


VERSION_BODY = {
    "feature_key": FEATURE,
    "corpus_id": CORPUS,
    "corpus_version": VERSION,
    "document_count": 2,
    "chunk_count": 2,
    "embedding_model": "fixture",
    "embedding_dimensions": 384,
    "ingested_at": INGESTED,
}


def rag(request: httpx.Request) -> httpx.Response:
    assert request.headers["Authorization"] == "Bearer rag-token"
    path = request.url.path
    if path == f"/api/v1/corpora/{FEATURE}/{CORPUS}":
        return httpx.Response(200, json=VERSION_BODY)
    if path == f"/api/v1/corpora/{FEATURE}/{CORPUS}/chunks":
        chunks = [citation("alpha", 0), citation("beta", 0)]
        return httpx.Response(200, json={"version": VERSION_BODY, "chunks": chunks})
    if path == "/api/v1/retrieve":
        body = json.loads(request.content)
        ranked = [citation("alpha", 0.71), citation("beta", 0.48)]
        kept = [item for item in ranked if float(str(item["score"])) >= body["min_score"]]
        return httpx.Response(
            200,
            json={
                "feature_key": FEATURE,
                "corpus_id": CORPUS,
                "corpus_version": VERSION,
                "status": "ready" if kept else "no_match",
                "citations": kept[: body["top_k"]],
            },
        )
    return httpx.Response(404, json={})


def make_app(handler: object = rag, *, enabled: bool = True) -> Flask:
    client = (
        KnowledgeClient(
            base_url="http://rag.test",
            service_token="rag-token",
            client=httpx.Client(transport=httpx.MockTransport(handler)),  # type: ignore[arg-type]
        )
        if enabled
        else None
    )
    app = Flask(__name__)
    app.register_blueprint(create_knowledge_blueprint(client, ((FEATURE, CORPUS),)))
    return app


def test_lists_registered_corpora_with_active_versions_and_grounding_limits() -> None:
    body = make_app().test_client().get("/api/v1/operations/knowledge").json

    assert body["enabled"] is True
    assert body["grounding"]["min_score"] == GROUNDING_MIN_SCORE
    assert body["grounding"]["top_k"] == GROUNDING_TOP_K
    [corpus] = body["corpora"]
    assert (corpus["feature_key"], corpus["corpus_id"], corpus["status"]) == (
        FEATURE,
        CORPUS,
        "ready",
    )
    assert corpus["version"]["corpus_version"] == VERSION
    assert corpus["version"]["chunk_count"] == 2


def test_disabled_retrieval_is_reported_as_a_state_not_an_error() -> None:
    client = make_app(enabled=False).test_client()

    listing = client.get("/api/v1/operations/knowledge").json
    assert listing["enabled"] is False
    assert listing["corpora"][0]["status"] == "disabled"
    response = client.get(f"/api/v1/operations/knowledge/{FEATURE}/{CORPUS}/chunks")
    assert_problem_detail(response.json, status=503, code="retrieval_disabled")


def test_unreachable_rag_marks_corpus_unavailable() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = make_app(down).test_client()
    assert client.get("/api/v1/operations/knowledge").json["corpora"][0]["status"] == "unavailable"
    response = client.get(f"/api/v1/operations/knowledge/{FEATURE}/{CORPUS}/search?q=x")
    assert_problem_detail(response.json, status=503, code="retrieval_unavailable")


def test_chunks_are_listed_only_for_registered_corpora() -> None:
    client = make_app().test_client()

    listed = client.get(f"/api/v1/operations/knowledge/{FEATURE}/{CORPUS}/chunks")
    assert listed.status_code == 200
    assert [chunk["chunk_id"] for chunk in listed.json["chunks"]] == ["alpha", "beta"]
    other = client.get("/api/v1/operations/knowledge/student-2-other/private/chunks")
    assert_problem_detail(other.json, status=404, code="corpus_not_registered")


def test_search_marks_which_ranked_passages_a_grounded_run_would_receive() -> None:
    client = make_app().test_client()

    body = client.get(f"/api/v1/operations/knowledge/{FEATURE}/{CORPUS}/search?q=publish").json

    assert body["status"] == "ready"
    assert [(item["chunk_id"], item["used_in_grounding"]) for item in body["candidates"]] == [
        ("alpha", True),
        ("beta", False),
    ]


@pytest.mark.parametrize("query", ["", "   ", "x" * 2001])
def test_search_rejects_blank_or_oversized_queries(query: str) -> None:
    response = (
        make_app()
        .test_client()
        .get(f"/api/v1/operations/knowledge/{FEATURE}/{CORPUS}/search", query_string={"q": query})
    )
    assert_problem_detail(response.json, status=400, code="query_invalid")


def test_oversized_rag_response_is_rejected() -> None:
    def huge(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 20_000)

    client = make_app(huge).test_client()
    assert client.get("/api/v1/operations/knowledge").json["corpora"][0]["status"] == "unavailable"
