"""Bounded background execution for workflow stages."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol

from multi_agent_server.errors import CapacityExceededError

LOGGER = logging.getLogger(__name__)


class StageExecutor(Protocol):
    """Runs agent stages; implementations decide where and when."""

    def has_capacity(self) -> bool:
        """Whether another task would be accepted now."""
        ...

    def submit(self, task: Callable[[], None]) -> None:
        """Accept a task or raise ``CapacityExceededError``."""
        ...

    def shutdown(self) -> None:
        """Stop accepting work."""
        ...


class InlineExecutor:
    """Runs each task synchronously (CLI in-process mode and deterministic tests)."""

    def has_capacity(self) -> bool:
        return True

    def submit(self, task: Callable[[], None]) -> None:
        task()

    def shutdown(self) -> None:
        """Nothing to stop."""


class BoundedExecutor:
    """A fixed thread pool with a hard cap on queued plus running tasks."""

    def __init__(self, *, workers: int, capacity: int) -> None:
        if not 1 <= workers <= 16 or not workers <= capacity <= 1_000:
            raise ValueError("workers must be 1-16 and capacity between workers and 1000")
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="multi-agent")
        self._capacity = capacity
        self._pending = 0
        self._lock = threading.Lock()

    def has_capacity(self) -> bool:
        with self._lock:
            return self._pending < self._capacity

    def submit(self, task: Callable[[], None]) -> None:
        with self._lock:
            if self._pending >= self._capacity:
                raise CapacityExceededError("The workflow queue is full; try again shortly")
            self._pending += 1

        def run() -> None:
            try:
                task()
            except Exception:
                LOGGER.exception("Workflow stage task failed outside its own error handling")
            finally:
                with self._lock:
                    self._pending -= 1

        self._pool.submit(run)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
