"""Bounded concurrency-one background execution queue."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from queue import Empty, Full, Queue
from threading import Event, Thread
from time import monotonic
from uuid import UUID

from ai_mode.configuration import (
    DEFAULT_QUEUE_CAPACITY,
    DEFAULT_QUEUE_RECONCILE_INTERVAL_SECONDS,
)
from shared_contracts import AgentRun

LOGGER = logging.getLogger(__name__)


class RunQueueFullError(RuntimeError):
    """The bounded local queue cannot accept more work."""


class SerialRunQueue:
    """Execute persisted runs serially, using durable discovery as the safety net."""

    def __init__(
        self,
        handler: Callable[[UUID], object],
        *,
        discover: Callable[[], Iterable[UUID]] | None = None,
        capacity: int = DEFAULT_QUEUE_CAPACITY,
        reconcile_interval_seconds: float = DEFAULT_QUEUE_RECONCILE_INTERVAL_SECONDS,
    ) -> None:
        if capacity < 1:
            raise ValueError("queue capacity must be positive")
        if reconcile_interval_seconds <= 0:
            raise ValueError("reconcile interval must be positive")
        self._handler = handler
        self._discover = discover
        self._reconcile_interval_seconds = reconcile_interval_seconds
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
                run_id = self._items.get(timeout=self._reconcile_interval_seconds)
            except Empty:
                self._reconcile()
                continue
            try:
                self._handle(run_id)
            finally:
                self._items.task_done()

    def _reconcile(self) -> None:
        if self._discover is None:
            return
        try:
            run_ids = tuple(self._discover())
        except Exception:
            LOGGER.exception(
                "Durable agent run discovery failed",
                extra={
                    "event": "agent.queue.discovery_failed",
                    "outcome": "failure",
                    "error_code": "run_discovery_failed",
                },
            )
            return
        for run_id in run_ids:
            if self._stopping.is_set():
                return
            self._handle(run_id)

    def _handle(self, run_id: UUID) -> None:
        started = monotonic()
        try:
            result = self._handler(run_id)
        except Exception:
            LOGGER.exception(
                "agent run worker failed",
                extra={
                    "event": "agent.run.worker_failed",
                    "run_id": run_id,
                    "outcome": "failure",
                    "duration_ms": max(0, int((monotonic() - started) * 1_000)),
                    "error_code": "run_worker_failed",
                },
            )
            return
        fields: dict[str, object] = {
            "event": "agent.run.blocked",
            "run_id": run_id,
            "outcome": "completed",
            "duration_ms": max(0, int((monotonic() - started) * 1_000)),
        }
        if isinstance(result, AgentRun):
            fields.update(
                {
                    "feature_key": result.feature_key,
                    "run_status": result.status,
                    "outcome": result.status,
                    "iteration_count": result.iteration_count,
                    "tool_call_count": result.tool_call_count,
                    "error_code": result.error.code if result.error is not None else None,
                }
            )
        LOGGER.info("Agent run reached a blocked boundary", extra=fields)
