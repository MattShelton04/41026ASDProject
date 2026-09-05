from __future__ import annotations

from collections.abc import Iterator
from threading import Event
from typing import Any

import pytest

from propertyscope_data_platform.release_stream import ReleaseRowStream


def page(items: list[dict[str, Any]], *, cursor: str | None = None) -> dict[str, Any]:
    return {
        "release_id": "release",
        "candidate_generation_id": "generation",
        "total": 2,
        "items": items,
        "next_cursor": cursor,
    }


def stream(fetch: Any, heartbeat: Any = lambda *_: None, **kwargs: Any) -> ReleaseRowStream:
    return ReleaseRowStream(
        fetch, heartbeat, release_id="release", generation_id="generation", page_size=2, **kwargs
    )


def test_prefetch_overlaps_consumption_but_never_reads_a_third_page_ahead() -> None:
    second_started = Event()
    calls = []

    def fetch(cursor: str | None) -> dict[str, Any]:
        calls.append(cursor)
        if cursor is None:
            return page([{"id": 1}], cursor="second")
        second_started.set()
        return page([{"id": 2}])

    rows = iter(stream(fetch))
    assert next(rows) == {"id": 1}
    assert second_started.wait(2), "next page must start before current records are consumed"
    assert calls == [None, "second"]
    assert list(rows) == [{"id": 2}]


def test_slow_read_renews_lease_and_cancellation_stops_scheduling() -> None:
    read_started = Event()
    release_read = Event()
    read_finished = Event()
    calls = []

    def fetch(cursor: str | None) -> dict[str, Any]:
        calls.append(cursor)
        read_started.set()
        try:
            assert release_read.wait(2)
            return page([{"id": 1}], cursor="second")
        finally:
            read_finished.set()

    def cancel(processed: int, total: int | None) -> None:
        assert read_started.is_set()
        assert (processed, total) == (0, None)
        raise RuntimeError("operator cancelled")

    try:
        with pytest.raises(RuntimeError, match="operator cancelled"):
            list(stream(fetch, cancel, heartbeat_seconds=0.01))
        assert calls == [None]
    finally:
        release_read.set()
        assert read_finished.wait(2)


def test_fetch_timeout_is_surfaced_instead_of_spinning_on_a_completed_future() -> None:
    def fetch(_: str | None) -> dict[str, Any]:
        raise TimeoutError("upstream timed out")

    with pytest.raises(TimeoutError, match="upstream timed out"):
        list(stream(fetch))


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"release_id": "other"}, "generation changed"),
        ({"candidate_generation_id": None}, "generation changed"),
        ({"total": True}, "candidate total"),
        ({"total": -1}, "candidate total"),
        ({"total": 0}, "page count"),
        ({"items": [None]}, "malformed"),
        ({"items": [{}, {}, {}]}, "malformed"),
        ({"items": [], "next_cursor": "next"}, "cursor"),
        ({"next_cursor": ""}, "cursor"),
        ({"next_cursor": 123}, "cursor"),
    ],
)
def test_invalid_pages_fail_before_prefetch(changes: dict[str, Any], message: str) -> None:
    calls = []

    def fetch(cursor: str | None) -> dict[str, Any]:
        calls.append(cursor)
        return {**page([{"id": 1}], cursor="next"), **changes}

    with pytest.raises(RuntimeError, match=message):
        list(stream(fetch))
    assert calls == [None]


def test_nonadjacent_cursor_cycle_is_rejected() -> None:
    pages: Iterator[dict[str, Any]] = iter(
        {**page([{}], cursor=cursor), "total": 10} for cursor in ("a", "b", "a")
    )
    with pytest.raises(RuntimeError, match="cursor"):
        list(stream(lambda _: next(pages)))


def test_candidate_total_change_and_early_end_are_rejected() -> None:
    for second in ({**page([{}]), "total": 3}, page([])):
        pages = iter([page([{}], cursor="next"), second])
        with pytest.raises(RuntimeError, match=r"total changed|page count"):
            list(stream(lambda _, pages=pages: next(pages)))


def test_column_pages_preserve_values_and_legacy_pages_remain_readable() -> None:
    from propertyscope_data_store.export_pages import columnar_export_page

    items: list[dict[str, Any]] = [
        {"id": 1, "extra": None},
        {"id": 2, "extra": {"months": ["2025-01-01"]}},
    ]
    original = page(items)
    packed = columnar_export_page(original)
    assert "items" not in packed
    assert packed["columns"] == ["id", "extra"]
    assert list(stream(lambda _: packed)) == list(stream(lambda _: original)) == items
    assert list(stream(lambda _: columnar_export_page({**page([]), "total": 0}))) == []


@pytest.mark.parametrize(
    "changes",
    [
        {"layout": "unknown"},
        {"columns": ["id", "id"]},
        {"columns": [None]},
        {"columns": []},
        {"columns": "id"},
        {"rows": [[1, 2]]},
        {"rows": [{"id": 1}]},
        {"rows": [[1], [2], [3]]},
        {"items": []},
    ],
)
def test_malformed_column_pages_are_rejected(changes: dict[str, Any]) -> None:
    packed = {
        **{key: value for key, value in page([]).items() if key != "items"},
        "layout": "propertyscope.export-columns.v1",
        "columns": ["id"],
        "rows": [[1], [2]],
        **changes,
    }
    with pytest.raises(RuntimeError, match=r"layout|malformed"):
        list(stream(lambda _: packed))
