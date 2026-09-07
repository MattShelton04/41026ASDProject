"""Cumulative streaming and remaining-run budgets at the grounding verification boundary."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from scripts import release1_validation as validation

from agent_core import StructuredModelRequest, StructuredModelResult
from ai_mode.adapters.retrieval import RetrievalToolExecutor, retrieval_definition
from ai_mode.persistence import SQLiteRunStore
from ai_mode.services import UnconfiguredToolExecutor
from shared_contracts.retrieval import CorpusVersion, EvidenceCitation, RetrievalResponse

NOW = datetime(2026, 9, 7, tzinfo=UTC)


def version() -> CorpusVersion:
    return CorpusVersion(
        feature_key=validation.FEATURE,
        corpus_id=validation.CORPUS,
        corpus_version="a" * 64,
        document_count=1,
        chunk_count=1,
        embedding_model="fixture",
        embedding_dimensions=1,
        ingested_at=NOW,
    )


def evidence() -> RetrievalResponse:
    metadata = version()
    citation = EvidenceCitation(
        citation_id="source-1",
        feature_key=metadata.feature_key,
        corpus_id=metadata.corpus_id,
        corpus_version=metadata.corpus_version,
        document_id="guide",
        chunk_id="chunk-1",
        title="Guide",
        source_uri="https://example.org/guide",
        content_hash="b" * 64,
        location="section 1",
        ingested_at=NOW,
        evidence_kind="fixture",
        excerpt="Review before publication.",
        score=0.9,
    )
    return RetrievalResponse(
        feature_key=metadata.feature_key,
        corpus_id=metadata.corpus_id,
        corpus_version=metadata.corpus_version,
        status="ready",
        citations=(citation,),
    )


def test_metadata_slow_stream_cannot_reset_cumulative_timeout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    elapsed = [0.0]
    yielded = [0]

    class SlowStream(httpx.SyncByteStream):
        def __iter__(self) -> Iterator[bytes]:
            for value in version().model_dump_json().encode():
                elapsed[0] += 0.4
                yielded[0] += 1
                yield bytes([value])

    monkeypatch.setattr("ai_mode.adapters.retrieval.monotonic", lambda: elapsed[0])
    store = SQLiteRunStore(tmp_path / "state.sqlite3")
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=SlowStream()))
    ) as client:
        executor = RetrievalToolExecutor(
            UnconfiguredToolExecutor(),
            store,
            base_url="http://127.0.0.1:5012",
            service_token="x" * 32,
            client=client,
        )
        assert executor.current_version(validation.FEATURE, validation.CORPUS) is None
    assert yielded[0] == 5


def test_exhausted_metadata_budget_never_dispatches(tmp_path: Path) -> None:
    def forbidden(request: httpx.Request) -> httpx.Response:
        pytest.fail("An exhausted verification must not contact RAG")

    with httpx.Client(transport=httpx.MockTransport(forbidden)) as client:
        executor = RetrievalToolExecutor(
            UnconfiguredToolExecutor(),
            SQLiteRunStore(tmp_path / "state.sqlite3"),
            base_url="http://127.0.0.1:5012",
            service_token="x" * 32,
            client=client,
        )
        assert executor.current_version(validation.FEATURE, validation.CORPUS, timeout_ms=0) is None


@pytest.mark.parametrize("remaining_ms", [0, 100])
def test_runner_cannot_succeed_after_grounding_verification_exhausts_budget(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    remaining_ms: int,
) -> None:
    class Clock:
        current = NOW

        def now(self) -> datetime:
            return self.current

    clock = Clock()
    monkeypatch.setattr(validation, "SystemClock", lambda: clock)

    class ExpensiveProvider(validation.ValidationProvider):
        def generate_structured(self, request: StructuredModelRequest) -> StructuredModelResult:
            result = super().generate_structured(request)
            if request.role.value == "adapter":
                detail = self.store.get(request.run_id)
                assert detail is not None
                clock.current = NOW + timedelta(
                    milliseconds=detail.run.limits.time_budget_ms - remaining_ms
                )
            return result

    monkeypatch.setattr(validation, "ValidationProvider", ExpensiveProvider)
    reads: list[float] = []

    def response(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json=evidence().model_dump(mode="json"))
        reads.append(request.extensions["timeout"]["read"])
        clock.current += timedelta(milliseconds=200)
        return httpx.Response(200, json=version().model_dump(mode="json"))

    store = SQLiteRunStore(tmp_path / "validation.sqlite3")
    store.initialize()
    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        executor = RetrievalToolExecutor(
            UnconfiguredToolExecutor(),
            store,
            base_url="http://127.0.0.1:5012",
            service_token="x" * 32,
            client=client,
        )
        result = validation.execute_validation("rag", store, retrieval_definition(), executor)
    assert result["status"] == "failed"
    assert result["error"] == {"code": "run_limit_reached", "message": "time limit reached"}
    assert reads == ([0.1] if remaining_ms else [])
