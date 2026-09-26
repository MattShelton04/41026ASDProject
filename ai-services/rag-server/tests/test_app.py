"""In-process HTTP boundary tests with deliberate offline embeddings."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from rag_server import RagSettings, create_app
from rag_server.cli import load_manifest
from rag_server.embeddings import EmbeddingUnavailableError, UnavailableEmbedder

FEATURE = "student-1-propertyscope-data-platform"
HEADERS = {"Authorization": "Bearer test-token-for-rag-service"}


def payload() -> dict[str, object]:
    return {
        "feature_key": FEATURE,
        "corpus_id": "operator-guidance",
        "documents": [
            {
                "document_id": "guide",
                "title": "Publication review",
                "source_uri": "https://example.org",
                "text": "Publication requires explicit review approval.",
                "license": "CC0",
            }
        ],
    }


def test_authenticated_ingestion_search_status_and_bounds() -> None:
    app = create_app(
        RagSettings(
            token="test-token-for-rag-service", database_path=":memory:", embedding_mode="fixture"
        )
    )
    client = app.test_client()
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 401
    assert client.get("/health/ready", headers=HEADERS).json["embedding_mode"] == "fixture"
    route = f"/api/v1/corpora/{FEATURE}/operator-guidance"
    assert client.get(route, headers=HEADERS).status_code == 404
    assert client.get(route + "/chunks", headers=HEADERS).status_code == 404
    assert client.post("/api/v1/corpora/ingest", json=payload()).status_code == 401
    response = client.post("/api/v1/corpora/ingest", json=payload(), headers=HEADERS)
    assert response.status_code == 200
    assert client.get(route, headers=HEADERS).json == response.json
    assert client.get(route + "/chunks").status_code == 401
    contents = client.get(route + "/chunks", headers=HEADERS).json
    assert contents["version"] == response.json
    assert [chunk["document_id"] for chunk in contents["chunks"]] == ["guide"]
    assert client.get("/api/v1/corpora/other/private/chunks", headers=HEADERS).status_code == 403
    result = client.post(
        "/api/v1/retrieve",
        headers=HEADERS,
        json={
            "feature_key": FEATURE,
            "corpus_id": "operator-guidance",
            "query": "publication review",
        },
    )
    assert result.json["status"] == "ready"
    assert result.json["citations"][0]["title"] == "Publication review"
    assert client.get("/api/v1/corpora/other/private", headers=HEADERS).status_code == 403
    for body in ({"url": "file:///secret"}, {"schema_version": "unexpected"}):
        assert client.post("/api/v1/retrieve", json=body, headers=HEADERS).status_code == 400
    assert (
        client.post(
            "/api/v1/retrieve", data="{", headers=HEADERS, content_type="application/json"
        ).status_code
        == 400
    )
    assert client.post("/api/v1/retrieve", data="plain", headers=HEADERS).status_code == 400
    assert (
        client.post(
            "/api/v1/retrieve",
            data="x" * (2 * 1024 * 1024 + 1),
            content_type="application/json",
            headers=HEADERS,
        ).status_code
        == 413
    )
    app.extensions["rag_index"].close()


def test_unprepared_model_is_visible_and_ingestion_fails_safely(tmp_path: Path) -> None:
    app = create_app(
        RagSettings(
            token="test-token-for-rag-service", database_path=":memory:", model_cache_path=tmp_path
        )
    )
    client = app.test_client()
    assert client.get("/health/ready", headers=HEADERS).status_code == 503
    result = client.post("/api/v1/corpora/ingest", json=payload(), headers=HEADERS)
    assert result.status_code == 503
    assert result.json["title"] == "retrieval_unavailable"
    assert app.extensions["rag_index"].current(FEATURE, "operator-guidance") is None
    app.extensions["rag_index"].close()
    with pytest.raises(EmbeddingUnavailableError):
        UnavailableEmbedder().embed(["query"])


def test_environment_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_SERVICE_TOKEN", "test-token-for-rag-service")
    monkeypatch.setenv("RAG_DATABASE_PATH", ":memory:")
    monkeypatch.setenv("RAG_EMBEDDING_MODE", "fixture")
    app = create_app()
    assert app.test_client().get("/health/ready", headers=HEADERS).status_code == 200
    app.extensions["rag_index"].close()
    monkeypatch.setenv("RAG_ALLOWED_CORPORA", "bad-format")
    with pytest.raises(ValueError, match="pairs"):
        RagSettings.from_environment()


@pytest.mark.parametrize(
    "changes",
    [{"token": "short"}, {"embedding_mode": "automatic"}, {"allowed_corpora": frozenset()}],
)
def test_settings_fail_closed(changes: dict[str, object]) -> None:
    values = {"token": "test-token-for-rag-service", **changes}
    with pytest.raises(ValueError):
        RagSettings(**values)  # type: ignore[arg-type]


def test_local_manifest_reads_only_owned_text(tmp_path: Path) -> None:
    document = tmp_path / "guide.md"
    document.write_text("Public review guidance", encoding="utf-8")
    manifest = tmp_path / "corpus.json"
    body = payload()
    docs = body["documents"]
    assert isinstance(docs, list)
    docs[0].pop("text")
    docs[0]["path"] = "guide.md"
    manifest.write_text(json.dumps(body), encoding="utf-8")
    assert load_manifest(manifest).documents[0].text == "Public review guidance"
    for invalid in ("../outside.md", "https://example.org/file.md", "unsafe.py"):
        docs[0]["path"] = invalid
        manifest.write_text(json.dumps(body), encoding="utf-8")
        with pytest.raises((ValueError, OSError)):
            load_manifest(manifest)
    docs[0]["path"] = "guide.md"
    docs[0]["text"] = "ambiguous"
    manifest.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(ValueError, match="either"):
        load_manifest(manifest)
    docs[0].pop("text")
    document.write_text("x" * 240001, encoding="utf-8")
    manifest.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(ValueError, match="too large"):
        load_manifest(manifest)
