"""Bounded concurrency-one background execution queue."""

from __future__ import annotations

import logging
from collections.abc import Callable
from queue import Empty, Full, Queue
from threading import Event, Thread
from uuid import UUID

LOGGER = logging.getLogger(__name__)


class RunQueueFullError(RuntimeError):
    """The bounded local queue cannot accept more work."""


class SerialRunQueue:
    """Execute persisted runs serially in one controlled daemon worker."""

    def __init__(self, handler: Callable[[UUID], object], *, capacity: int = 100) -> None:
        if capacity < 1:
            raise ValueError("queue capacity must be positive")
        self._handler = handler
        self._items: Queue[UUID] = Queue(maxsize=capacity)
        self._stopping = Event()
        self._thread = Thread(target=self._work, name="ai-mode-runner", daemon=True)
        self._thread.start()

    def enqueue(self, run_id: UUID) -> None:
        """Schedule work without blocking an HTTP request thread."""
        if self._stopping.is_set():
            raise RunQueueFullError("run queue is stopping")
        try:
            self._items.put_nowait(run_id)
        except Full as exc:
            raise RunQueueFullError("run queue capacity reached") from exc

    def close(self) -> None:
        """Stop accepting work; the daemon exits after its current handler."""
        self._stopping.set()
        self._thread.join(timeout=2)

    def _work(self) -> None:
        while not self._stopping.is_set():
            try:
                run_id = self._items.get(timeout=0.1)
            except Empty:
                continue
            try:
                self._handler(run_id)
            except Exception:
                LOGGER.exception("agent run worker failed", extra={"run_id": str(run_id)})
            finally:
                self._items.task_done()
