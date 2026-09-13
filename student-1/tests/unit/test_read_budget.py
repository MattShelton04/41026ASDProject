from __future__ import annotations

from typing import Any, cast

import pytest
from psycopg import Connection, errors
from psycopg_pool import PoolTimeout

from propertyscope_data_store import read_budget
from propertyscope_data_store.errors import ReadBudgetExceededError


class RecordingConnection:
    def __init__(self) -> None:
        self.commands: list[str] = []

    def execute(self, command: str) -> None:
        self.commands.append(command)


def test_read_budget_covers_all_statements_and_resets_after_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [10.0]
    monkeypatch.setattr(read_budget, "monotonic", lambda: now[0])
    connection = RecordingConnection()
    with pytest.raises(ReadBudgetExceededError), read_budget.interactive_read():
        read_budget.apply_read_budget(cast(Connection[Any], connection))
        now[0] += 2
        assert read_budget.remaining_read_seconds() == 1.5
        read_budget.apply_read_budget(cast(Connection[Any], connection))
        now[0] += 2
        read_budget.remaining_read_seconds()
    assert connection.commands[0] == "SET LOCAL statement_timeout='3500ms'"
    assert connection.commands[3] == "SET LOCAL statement_timeout='1500ms'"
    assert read_budget.remaining_read_seconds() is None
    # Loader/export calls outside an interactive request keep their own limits.
    read_budget.apply_read_budget(cast(Connection[Any], connection))
    assert len(connection.commands) == 6


@pytest.mark.parametrize("failure", [errors.QueryCanceled, errors.LockNotAvailable, PoolTimeout])
def test_read_cancellation_and_pool_waits_have_one_safe_boundary(failure: type[Exception]) -> None:
    with (
        pytest.raises(ReadBudgetExceededError, match="time budget") as captured,
        read_budget.interactive_read(),
    ):
        raise failure("private SQL and connection information")
    assert "private" not in str(captured.value)
    assert read_budget.remaining_read_seconds() is None
