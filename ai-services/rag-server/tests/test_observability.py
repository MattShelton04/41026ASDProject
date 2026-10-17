"""One allowlisted, correlated JSON log line per RAG request, including failures."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from enum import Enum
from uuid import UUID

import pytest
from flask import Flask, Response
from rag_server import RagSettings, create_app
from rag_server.observability import JsonLogFormatter, configure_structured_logging

FEATURE = "student-1-propertyscope-data-platform"
TOKEN = "test-token-for-rag-service"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
RUN_ID = "4b7d1f0e-8a3c-4c1e-9f55-2f6c1b0d9a11"
QUERY = "publication review for the confidential 12 Example Street buyer"
DOCUMENT_TEXT = "Publication requires explicit review approval."


@pytest.fixture
def app() -> Iterator[Flask]:
    application = create_app(
        RagSettings(token=TOKEN, database_path=":memory:", embedding_mode="fixture")
    )
    yield application
    application.extensions["rag_index"].close()


def records(
    caplog: pytest.LogCaptureFixture, event: str | None = "http.request.completed"
) -> list[dict[str, object]]:
    """Render captured records through the production formatter, as the host log sees them."""
    formatter = JsonLogFormatter()
    return [
        json.loads(formatter.format(record))
        for record in caplog.records
        if record.name.startswith("rag_server")
        and (event is None or getattr(record, "event", None) == event)
    ]


def ingest(client: object) -> None:
    body = {
        "feature_key": FEATURE,
        "corpus_id": "operator-guidance",
        "documents": [
            {
                "document_id": "guide",
                "title": "Publication review",
                "source_uri": "https://example.org",
                "text": DOCUMENT_TEXT,
                "license": "CC0",
            }
        ],
    }
    assert client.post("/api/v1/corpora/ingest", json=body, headers=HEADERS).status_code == 200  # type: ignore[attr-defined]


def test_retrieval_logs_correlated_scope_counts_without_query_or_content(
    app: Flask, caplog: pytest.LogCaptureFixture
) -> None:
    client = app.test_client()
    ingest(client)
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="rag_server"):
        response = client.post(
            "/api/v1/retrieve",
            headers={
                **HEADERS,
                "X-Request-ID": "local-deploy-0123456789abcdef",
                "X-Agent-Run-ID": RUN_ID,
            },
            json={"feature_key": FEATURE, "corpus_id": "operator-guidance", "query": QUERY},
        )
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "local-deploy-0123456789abcdef"
    [line] = records(caplog)
    assert line["event"] == "http.request.completed"
    assert line["service"] == "rag-server"
    assert line["level"] == "info"
    assert line["request_id"] == "local-deploy-0123456789abcdef"
    assert line["run_id"] == RUN_ID
    assert (line["feature_key"], line["corpus_id"]) == (FEATURE, "operator-guidance")
    assert (line["method"], line["path"], line["status_code"]) == ("POST", "/api/v1/retrieve", 200)
    assert (line["outcome"], line["error_code"]) == ("success", None)
    assert line["retrieval_status"] == "ready"
    assert line["result_count"] == 1
    assert isinstance(line["duration_ms"], int) and line["duration_ms"] >= 0
    rendered = json.dumps(line)
    for secret in (QUERY, "12 Example Street", DOCUMENT_TEXT, TOKEN, "Bearer"):
        assert secret not in rendered


def test_ingestion_and_corpus_routes_log_counts_and_route_templates(
    app: Flask, caplog: pytest.LogCaptureFixture
) -> None:
    client = app.test_client()
    route = f"/api/v1/corpora/{FEATURE}/operator-guidance"
    with caplog.at_level(logging.INFO, logger="rag_server"):
        assert client.get(route, headers=HEADERS).status_code == 404
        ingest(client)
        assert client.get(route, headers=HEADERS).status_code == 200
        assert client.get(route + "/chunks", headers=HEADERS).status_code == 200
    empty, ingested, current, chunks = records(caplog)
    assert (empty["status_code"], empty["error_code"], empty["outcome"]) == (
        404,
        "corpus_empty",
        "failure",
    )
    assert empty["path"] == "/api/v1/corpora/<feature>/<corpus>"
    assert (ingested["document_count"], ingested["chunk_count"]) == (1, 1)
    assert (current["document_count"], current["chunk_count"]) == (1, 1)
    assert chunks["path"] == "/api/v1/corpora/<feature>/<corpus>/chunks"
    assert chunks["result_count"] == 1
    assert all(line["feature_key"] == FEATURE for line in (empty, ingested, current, chunks))
    assert DOCUMENT_TEXT not in json.dumps([empty, ingested, current, chunks])


def test_rejections_log_reason_without_unregistered_scope_or_credentials(
    app: Flask, caplog: pytest.LogCaptureFixture
) -> None:
    client = app.test_client()
    with caplog.at_level(logging.INFO, logger="rag_server"):
        unauthorized = client.post(
            "/api/v1/retrieve",
            headers={"Authorization": "Bearer guessed-token-value", "X-Request-ID": "bad id!"},
            json={"feature_key": FEATURE, "corpus_id": "operator-guidance", "query": QUERY},
        )
        denied = client.get("/api/v1/corpora/other/private-notes", headers=HEADERS)
        invalid = client.post("/api/v1/retrieve", headers=HEADERS, json={"query": QUERY})
        missing = client.get("/not-a-route", headers=HEADERS)
    first, second, third, fourth = records(caplog)
    assert unauthorized.status_code == 401
    assert (first["error_code"], first["outcome"]) == ("unauthorized", "failure")
    # An unsafe incoming ID is replaced, and the generated ID is echoed consistently.
    assert first["request_id"] == unauthorized.headers["X-Request-ID"]
    assert str(UUID(str(first["request_id"]))) == first["request_id"]
    assert first["feature_key"] is None and "corpus_id" not in first
    assert (denied.status_code, second["error_code"]) == (403, "scope_denied")
    assert second["feature_key"] is None and "corpus_id" not in second
    assert (invalid.status_code, third["error_code"]) == (400, "invalid_request")
    assert (missing.status_code, fourth["error_code"]) == (404, "not_found")
    assert fourth["path"] == "/not-a-route"
    rendered = json.dumps([first, second, third, fourth])
    for secret in (QUERY, "guessed-token-value", TOKEN, "private-notes"):
        assert secret not in rendered


def test_unexpected_failure_returns_problem_and_logs_error_without_message(
    app: Flask, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(payload: object) -> None:
        raise RuntimeError(f"index failure while answering {QUERY}")

    monkeypatch.setattr(app.extensions["rag_index"], "retrieve", explode)
    client = app.test_client()
    with caplog.at_level(logging.INFO, logger="rag_server"):
        response = client.post(
            "/api/v1/retrieve",
            headers={**HEADERS, "X-Request-ID": "local-deploy-failure"},
            json={"feature_key": FEATURE, "corpus_id": "operator-guidance", "query": QUERY},
        )
    assert response.status_code == 500
    assert response.json["title"] == "internal_error"
    assert response.headers["X-Request-ID"] == "local-deploy-failure"
    [line] = records(caplog)
    assert line["level"] == "error"
    assert (line["status_code"], line["outcome"], line["error_code"]) == (
        500,
        "failure",
        "internal_error",
    )
    assert line["request_id"] == "local-deploy-failure"
    assert line["feature_key"] == FEATURE
    assert "result_count" not in line
    assert QUERY not in json.dumps(line) and "index failure" not in json.dumps(line)


def test_teardown_logs_a_request_that_failed_while_finalizing(
    app: Flask, caplog: pytest.LogCaptureFixture
) -> None:
    @app.after_request
    def broken(response: Response) -> Response:
        raise RuntimeError(f"finalizer failure mentioning {QUERY}")

    client = app.test_client()
    with caplog.at_level(logging.INFO, logger="rag_server"):
        response = client.get("/health/live", headers={"X-Request-ID": "local-deploy-teardown"})
    assert response.status_code == 500
    [line] = records(caplog)
    assert (line["level"], line["status_code"], line["outcome"]) == ("error", 500, "failure")
    assert line["request_id"] == "local-deploy-teardown"
    assert line["exception_type"] == "RuntimeError"
    assert line["error_code"] == "internal_server_error"
    # Flask's own finalizer report shares the service logger and is rendered just as safely.
    assert QUERY not in json.dumps(records(caplog, event=None))


def test_environment_factory_writes_json_lines_to_stdout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("RAG_SERVICE_TOKEN", TOKEN)
    monkeypatch.setenv("RAG_DATABASE_PATH", ":memory:")
    monkeypatch.setenv("RAG_EMBEDDING_MODE", "fixture")
    monkeypatch.setenv("RAG_LOG_LEVEL", "info")
    app = create_app()
    response = app.test_client().get(
        "/health/ready", headers={**HEADERS, "X-Request-ID": "local-deploy-stdout"}
    )
    app.extensions["rag_index"].close()
    assert response.status_code == 200
    [line] = [json.loads(text) for text in capsys.readouterr().out.splitlines()]
    assert line["request_id"] == "local-deploy-stdout"
    assert line["path"] == "/health/ready"
    assert logging.getLogger("rag_server").propagate is False


def test_log_level_is_validated_and_quiet_levels_suppress_request_lines(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(ValueError, match="RAG_LOG_LEVEL"):
        RagSettings(token=TOKEN, log_level="LOUD")
    configure_structured_logging("WARNING")
    logging.getLogger("rag_server.app").info("suppressed", extra={"request_id": "local-deploy-x"})
    assert capsys.readouterr().out == ""


def test_formatter_serializes_only_allowlisted_fields() -> None:
    class Status(Enum):
        READY = "ready"

    record = logging.LogRecord("rag_server.app", logging.INFO, __file__, 1, "done", None, None)
    record.request_id = UUID(RUN_ID)
    record.retrieval_status = Status.READY
    record.result_count = 2
    record.path = ("tuple", "value")
    record.query = QUERY
    record.text = DOCUMENT_TEXT
    line = json.loads(JsonLogFormatter(environment="test").format(record))
    assert line["request_id"] == RUN_ID
    assert line["retrieval_status"] == "ready"
    assert line["result_count"] == 2
    assert line["path"] == "('tuple', 'value')"
    assert line["environment"] == "test"
    assert line["event"] == "rag_server.app"
    assert "query" not in line and "text" not in line
