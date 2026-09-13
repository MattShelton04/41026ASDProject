from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, cast

import pytest
from flask import Flask

from propertyscope_data_store._release_records import _ReleaseRecords
from propertyscope_data_store.api import create_blueprint, register_error_handlers
from propertyscope_data_store.errors import ReadBudgetExceededError


class PreviewOwner:
    def __init__(self, rows: int) -> None:
        self.rows = rows
        self.queries: list[str] = []
        self.context_reads = 0

    def _required(self, query: str, params: Sequence[Any]) -> dict[str, Any]:
        self.context_reads += 1
        assert "count(*)" not in query
        return {
            "id": str(params[0]),
            "dataset_id": "nsw-government-schools",
            "release_version": "test",
            "status": "accepted",
            "record_count": 99999,
            "import_profile_key": "schools-master",
        }

    def _fetch_all(self, query: str, params: Sequence[Any]) -> list[dict[str, Any]]:
        self.queries.append(query)
        return [{"school_code": str(index)} for index in range(self.rows)]


@pytest.mark.parametrize(
    ("rows", "offset", "total", "lower_bound", "next_offset"),
    [
        (26, 0, 26, True, 25),
        (25, 0, 25, False, None),
        (1, 25, 26, False, None),
        (0, 0, 0, False, None),
        (0, 9999, 0, True, None),
    ],
)
def test_preview_continuation_is_proven_by_a_sentinel_not_a_full_count(
    rows: int,
    offset: int,
    total: int,
    lower_bound: bool,
    next_offset: int | None,
) -> None:
    owner = PreviewOwner(rows)
    page = _ReleaseRecords(cast(Any, owner)).preview_release_records(
        uuid.uuid4(), limit=25, offset=offset
    )
    assert page["total"] == total
    assert page["total_is_lower_bound"] is lower_bound
    assert page["next_offset"] == next_offset
    assert page["count"] == len(page["items"]) == min(rows, 25)
    assert owner.context_reads == 1 and len(owner.queries) == 1


def test_summary_projection_does_not_fetch_large_manifests_and_full_remains_default() -> None:
    owner = PreviewOwner(0)
    releases = _ReleaseRecords(cast(Any, owner))
    releases.list_releases(status="accepted", summary=True, limit=25, offset=0)
    assert "release.*" not in owner.queries[-1]
    assert "manifest_json" not in owner.queries[-1]
    assert "release.status=%s" in owner.queries[-1]
    releases.list_releases(status="accepted", limit=25, offset=0)
    assert "release.*" in owner.queries[-1]


def test_cancelled_interactive_sql_returns_a_correlated_problem() -> None:
    class SlowStore:
        def search_properties(self, *_: Any, **__: Any) -> None:
            raise ReadBudgetExceededError("Narrow the search or retry the page.")

    app = Flask(__name__)
    app.register_blueprint(create_blueprint(cast(Any, SlowStore()), internal_token="test"))
    register_error_handlers(app)
    response = app.test_client().get(
        "/internal/data-platform/v1/properties/search?q=Glebe",
        headers={"X-PropertyScope-Internal-Token": "test", "X-Request-ID": "read-budget-test"},
    )
    assert response.status_code == 503
    body = response.get_json()
    assert body is not None
    assert body["code"] == "read_budget_exceeded"
    assert body["request_id"] == "read-budget-test"
