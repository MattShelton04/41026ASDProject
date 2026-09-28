"""Release 1 grounding boundaries for Feature 2.

AI-mode rewrites every run it grounds against a registered corpus: it appends the shared
retrieval tool to ``tool_allowlist``. These tests pin the two places that silently break when
that happens - the ownership comparison this backend uses to read its own runs, and the corpus
manifest the host launcher scopes RAG with.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
from flask.testing import FlaskClient

from propertyscope_market_intelligence.app import create_app as create_backend
from propertyscope_market_intelligence.domain import (
    APPROVED_TOOL_ALLOWLISTS,
    FEATURE_KEY,
    TOOL_ALLOWLIST,
    TOOL_ALLOWLIST_V1,
)
from propertyscope_market_store.app import create_app as create_database
from propertyscope_market_store.configuration import StoreSettings
from shared_testkit import assert_corpus_manifest, assert_grounded_allowlist_accepted

RETRIEVAL_TOOL = "context.retrieve.v1"
CORPUS_ID = "operator-guidance"
RUN_ID = "90000000-0000-4000-8000-000000000001"
CASE_ID = "60000000-0000-4000-8000-000000000001"


class _StoreClient:
    """The real database service, backed by a temporary SQLite file."""

    def __init__(self, tmp_path: Path) -> None:
        self._client = create_database(
            StoreSettings(tmp_path / "local.sqlite3", "local-token")
        ).test_client()

    def ready(self) -> bool:
        return self._client.get("/health/ready").status_code == 200

    def request(
        self, method: str, path: str, *, params: Any = None, json: Any = None
    ) -> httpx.Response:
        response = self._client.open(
            path,
            method=method,
            query_string=params,
            json=json,
            headers={"X-PropertyScope-Internal-Token": "local-token"},
        )
        return httpx.Response(
            response.status_code,
            request=httpx.Request(method, "http://database" + path),
            content=response.data,
            headers={"content-type": response.content_type},
        )


class _Feature1:
    state = "verified"

    def validate_property(self, _property_ref: str) -> str:
        return self.state

    def iter_artifact(self, _path: str) -> Iterator[bytes]:
        yield b""


class GroundedAiMode:
    """AI-mode as it behaves once this feature declares a corpus."""

    def __init__(self, allowlist: list[str]) -> None:
        self._allowlist = allowlist

    def create_run(self, _payload: dict[str, Any]) -> httpx.Response:
        return httpx.Response(202, json={"id": RUN_ID, "status": "queued"})

    def get(self, _path: str, *, params: Any = None) -> httpx.Response:
        del params
        return httpx.Response(
            200,
            json={
                "run": {
                    "id": RUN_ID,
                    "feature_key": FEATURE_KEY,
                    "tool_allowlist": self._allowlist,
                    "status": "succeeded",
                    "final_result": {"summary": "Evidence explained."},
                }
            },
        )

    def cancel(self, _run_id: str) -> httpx.Response:
        return httpx.Response(202, json={"status": "cancelling"})


def _client(tmp_path: Path, allowlist: list[str]) -> FlaskClient:
    return create_backend(
        store=_StoreClient(tmp_path),
        feature1=_Feature1(),
        ai_mode=GroundedAiMode(allowlist),
    ).test_client()


def test_ownership_predicate_accepts_the_grounded_variant() -> None:
    """The shared assertion drives this backend's real comparison, not the constant."""

    def accepts(wire_allowlist: list[str]) -> bool:
        return tuple(wire_allowlist) in APPROVED_TOOL_ALLOWLISTS

    assert_grounded_allowlist_accepted(accepts, TOOL_ALLOWLIST)


def test_grounded_run_stays_readable_through_the_api(tmp_path: Path) -> None:
    """A run carrying the appended retrieval tool must not 404 as someone else's run."""
    client = _client(tmp_path, [*TOOL_ALLOWLIST, RETRIEVAL_TOOL])
    for path in (
        f"/api/market-intelligence/v1/assistant/turns/{RUN_ID}",
        f"/api/market-intelligence/v1/assistant/turns/{RUN_ID}/events",
    ):
        assert client.get(path).status_code == 200, path
    cancelled = client.post(f"/api/market-intelligence/v1/assistant/turns/{RUN_ID}/cancel")
    assert cancelled.status_code == 202


def test_ungrounded_run_stays_readable(tmp_path: Path) -> None:
    """Registering a corpus must not break runs recorded before it existed."""
    client = _client(tmp_path, list(TOOL_ALLOWLIST))
    detail = client.get(f"/api/market-intelligence/v1/assistant/turns/{RUN_ID}")
    assert detail.status_code == 200


def test_foreign_allowlist_is_still_rejected(tmp_path: Path) -> None:
    """Widening by one known tool must not relax ownership to an unrestricted read."""
    client = _client(tmp_path, ["market.cases.inspect.v1", "platform.capabilities.v1"])
    detail = client.get(f"/api/market-intelligence/v1/assistant/turns/{RUN_ID}")
    assert detail.status_code == 404


def test_corpus_manifest_is_ingestible() -> None:
    """The identity the host launcher scopes RAG with must match what this feature declares."""
    assert_corpus_manifest(
        Path("student-2/config/rag/corpus.json"),
        feature_key=FEATURE_KEY,
        corpus_id=CORPUS_ID,
    )


def test_shared_chat_payload_is_accepted(tmp_path: Path) -> None:
    """The shared assistant posts {message, scope, context, history}, not {case_id, message}."""
    client = _client(tmp_path, [*TOOL_ALLOWLIST, RETRIEVAL_TOOL])
    created = client.post(
        "/api/market-intelligence/v1/assistant/turns",
        json={
            "message": "Explain the exclusions in this case.",
            "scope": "feature",
            "context": {"market_case_id": CASE_ID, "display_label": "Sydney 2025 snapshot"},
            "history": [
                {"role": "user", "content": "What does this case cover?"},
                {"role": "assistant", "content": "Ten eligible sales in 2025."},
            ],
        },
    )
    assert created.status_code == 202, created.get_json()


def test_history_must_be_complete_alternating_exchanges(tmp_path: Path) -> None:
    """A dangling user message would let replayed text pose as a completed exchange."""
    client = _client(tmp_path, list(TOOL_ALLOWLIST))
    rejected = client.post(
        "/api/market-intelligence/v1/assistant/turns",
        json={
            "message": "Explain the exclusions in this case.",
            "context": {"market_case_id": CASE_ID},
            "history": [{"role": "user", "content": "Dangling question"}],
        },
    )
    assert rejected.status_code == 422


def test_turn_without_a_case_is_rejected(tmp_path: Path) -> None:
    """The feature answers one saved case; a turn with no case must not reach AI-mode."""
    client = _client(tmp_path, list(TOOL_ALLOWLIST))
    rejected = client.post(
        "/api/market-intelligence/v1/assistant/turns",
        json={"message": "Explain the exclusions.", "scope": "feature", "context": {}},
    )
    assert rejected.status_code == 422


def test_capability_tool_is_argument_free_and_record_free(tmp_path: Path) -> None:
    """The MCP loop needs a read-only tool it can call with no arguments."""
    client = _client(tmp_path, list(TOOL_ALLOWLIST))
    result = client.post("/api/market-intelligence/v1/tools/market.capabilities.v1", json={})
    assert result.status_code == 200
    guide = result.get_json()
    assert guide["feature"]["feature_key"] == FEATURE_KEY
    assert {tool["name"] for tool in guide["tools"]} == set(TOOL_ALLOWLIST)
    assert guide["limitations"], "the guide must state what the feature refuses to do"
    # It describes the feature; it must never leak a case, property or sale record.
    assert "market_case" not in json.dumps(guide)


def test_runs_recorded_before_the_capability_tool_stay_readable(tmp_path: Path) -> None:
    """Adding a tool must not orphan runs recorded under the previous allowlist."""
    for allowlist in (
        list(TOOL_ALLOWLIST_V1),
        [*TOOL_ALLOWLIST_V1, RETRIEVAL_TOOL],
        list(TOOL_ALLOWLIST),
        [*TOOL_ALLOWLIST, RETRIEVAL_TOOL],
    ):
        client = _client(tmp_path, allowlist)
        detail = client.get(f"/api/market-intelligence/v1/assistant/turns/{RUN_ID}")
        assert detail.status_code == 200, allowlist
