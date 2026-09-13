"""Request-local deadlines for interactive reads, independent of loader work."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from time import monotonic
from typing import Any

from psycopg import Connection, errors
from psycopg_pool import PoolTimeout

from propertyscope_data_store.errors import ReadBudgetExceededError

_deadline: ContextVar[float | None] = ContextVar("propertyscope_read_deadline", default=None)
INTERACTIVE_READ_SECONDS = 3.5


@contextmanager
def interactive_read() -> Iterator[None]:
    """Bound the entire read, including pool waits and all its SQL statements."""
    token = _deadline.set(monotonic() + INTERACTIVE_READ_SECONDS)
    try:
        yield
    except (errors.QueryCanceled, errors.LockNotAvailable, PoolTimeout) as exc:
        raise ReadBudgetExceededError(
            "The read exceeded its time budget. Narrow the search or retry the page."
        ) from exc
    finally:
        _deadline.reset(token)


def remaining_read_seconds() -> float | None:
    deadline = _deadline.get()
    if deadline is None:
        return None
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise ReadBudgetExceededError(
            "The read exceeded its time budget. Narrow the search or retry the page."
        )
    return remaining


def apply_read_budget(connection: Connection[Any]) -> None:
    remaining = remaining_read_seconds()
    if remaining is None:
        return
    milliseconds = max(1, int(remaining * 1000))
    connection.execute(f"SET LOCAL statement_timeout='{milliseconds}ms'")
    connection.execute("SET LOCAL lock_timeout='500ms'")
    # Compilation of complex plans costs more than executing these bounded pages.
    connection.execute("SET LOCAL jit=off")
