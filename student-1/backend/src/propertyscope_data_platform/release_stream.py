"""Bounded, cancellable read-ahead for immutable candidate export pages."""

from __future__ import annotations

import time
from collections.abc import Callable, Generator
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any


class ReleaseRowStream:
    """Overlap one HTTP page read with projection/compression of the current page.

    Only the calling thread updates progress or yields records. An abandoned fetch is
    read-only and cannot schedule another request; its transport timeout bounds cleanup.
    """

    def __init__(
        self,
        fetch: Callable[[str | None], dict[str, Any]],
        heartbeat: Callable[[int, int | None], None],
        *,
        release_id: str,
        generation_id: str,
        page_size: int,
        heartbeat_seconds: float = 5,
    ) -> None:
        if page_size < 1 or heartbeat_seconds <= 0:
            raise ValueError("page and heartbeat bounds must be positive")
        self.fetch = fetch
        self.heartbeat = heartbeat
        self.release_id = release_id
        self.generation_id = generation_id
        self.page_size = page_size
        self.heartbeat_seconds = heartbeat_seconds
        self.total: int | None = None
        self.processed = 0
        self._started = False

    def __iter__(self) -> Generator[dict[str, Any], None, None]:
        if self._started:
            raise RuntimeError("release row stream is single-use")
        self._started = True
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="release-page")
        last_heartbeat = time.monotonic()
        pending: Future[dict[str, Any]] | None = None
        seen: set[str] = set()

        def check_active(*, force: bool = False) -> None:
            nonlocal last_heartbeat
            if force or time.monotonic() - last_heartbeat >= self.heartbeat_seconds:
                self.heartbeat(self.processed, self.total)
                last_heartbeat = time.monotonic()

        try:
            pending = executor.submit(self.fetch, None)
            while pending is not None:
                while True:
                    try:
                        page = pending.result(timeout=self.heartbeat_seconds)
                        break
                    except TimeoutError:
                        # A fetch may itself raise TimeoutError. Do not mistake a
                        # completed failure for a still-running future and loop forever.
                        if pending.done():
                            raise
                        check_active()
                items, cursor = self._validate(page, seen)
                check_active(force=cursor is not None)
                pending = executor.submit(self.fetch, cursor) if cursor is not None else None
                for item in items:
                    check_active()
                    yield item
                    self.processed += 1
            if self.processed != self.total:
                raise RuntimeError("Release product page count is inconsistent")
        finally:
            if pending is not None:
                pending.cancel()
            executor.shutdown(wait=False, cancel_futures=True)

    def _validate(
        self, page: dict[str, Any], seen: set[str]
    ) -> tuple[list[dict[str, Any]], str | None]:
        if not isinstance(page, dict):
            raise RuntimeError("Release product page is malformed")
        if "layout" in page:
            if page["layout"] != "propertyscope.export-columns.v1":
                raise RuntimeError("Release product page layout is not supported")
            columns, rows = page.get("columns"), page.get("rows")
            if (
                not isinstance(columns, list)
                or len(columns) > 128
                or any(not isinstance(column, str) or not column for column in columns)
                or len(set(columns)) != len(columns)
                or not isinstance(rows, list)
                or len(rows) > self.page_size
                or any(not isinstance(row, list) or len(row) != len(columns) for row in rows)
                or (rows and not columns)
                or "items" in page
            ):
                raise RuntimeError("Release product column page is malformed")
            page = {**page, "items": [dict(zip(columns, row, strict=True)) for row in rows]}
        if (
            str(page.get("release_id")) != self.release_id
            or str(page.get("candidate_generation_id")) != self.generation_id
        ):
            raise RuntimeError("Candidate generation changed during release construction")
        if self.total is None:
            total = page.get("total")
            if not isinstance(total, int) or isinstance(total, bool) or total < 0:
                raise RuntimeError("Release product first page has no candidate total")
            self.total = total
        elif page.get("total") is not None and page["total"] != self.total:
            raise RuntimeError("Release product candidate total changed")
        items = page.get("items")
        if (
            not isinstance(items, list)
            or len(items) > self.page_size
            or any(not isinstance(item, dict) for item in items)
        ):
            raise RuntimeError("Release product page is malformed")
        if self.processed + len(items) > self.total:
            raise RuntimeError("Release product page count is inconsistent")
        cursor = page.get("next_cursor")
        if cursor is not None:
            if not isinstance(cursor, str) or not cursor or cursor in seen or not items:
                raise RuntimeError("Release product pagination cursor is invalid")
            seen.add(cursor)
        return items, cursor
