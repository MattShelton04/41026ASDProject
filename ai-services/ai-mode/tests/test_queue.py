"""Tests for the bounded concurrency-one background queue."""

from threading import Event
from uuid import uuid4

import pytest

from ai_mode.queue import RunQueueFullError, SerialRunQueue


def test_queue_executes_work_and_stops_cleanly() -> None:
    handled = Event()
    run_id = uuid4()
    queue = SerialRunQueue(lambda received: handled.set())

    queue.enqueue(run_id)

    assert handled.wait(timeout=2)
    queue.close()
    with pytest.raises(RunQueueFullError, match="stopping"):
        queue.enqueue(run_id)


def test_queue_rejects_invalid_capacity_and_full_buffer() -> None:
    with pytest.raises(ValueError, match="capacity must be positive"):
        SerialRunQueue(lambda run_id: None, capacity=0)
    with pytest.raises(ValueError, match="reconcile interval must be finite and positive"):
        SerialRunQueue(lambda run_id: None, reconcile_interval_seconds=0)
    for invalid in (float("nan"), float("inf")):
        with pytest.raises(ValueError, match="reconcile interval must be finite and positive"):
            SerialRunQueue(lambda run_id: None, reconcile_interval_seconds=invalid)

    entered = Event()
    release = Event()

    def block(run_id):  # type: ignore[no-untyped-def]
        entered.set()
        release.wait(timeout=2)

    queue = SerialRunQueue(block, capacity=1)
    queue.enqueue(uuid4())
    assert entered.wait(timeout=2)
    queue.enqueue(uuid4())
    with pytest.raises(RunQueueFullError, match="capacity reached"):
        queue.enqueue(uuid4())
    release.set()
    queue.close()


def test_worker_discovers_persisted_work_without_an_in_memory_signal() -> None:
    handled = Event()
    run_id = uuid4()

    def discover():  # type: ignore[no-untyped-def]
        return () if handled.is_set() else (run_id,)

    queue = SerialRunQueue(
        lambda received: handled.set() if received == run_id else None,
        discover=discover,
        reconcile_interval_seconds=0.01,
    )

    assert handled.wait(timeout=2)
    queue.close()


def test_durable_discovery_retries_after_a_transient_handler_failure() -> None:
    recovered = Event()
    run_id = uuid4()
    attempts = 0

    def handle(received):  # type: ignore[no-untyped-def]
        nonlocal attempts
        assert received == run_id
        attempts += 1
        if attempts == 1:
            raise RuntimeError("transient")
        recovered.set()

    queue = SerialRunQueue(
        handle,
        discover=lambda: () if recovered.is_set() else (run_id,),
        reconcile_interval_seconds=0.01,
    )
    queue.enqueue(run_id)

    assert recovered.wait(timeout=2)
    queue.close()
    assert attempts == 2


def test_worker_contains_handler_failures(caplog: pytest.LogCaptureFixture) -> None:
    attempted = Event()

    def fail(run_id):  # type: ignore[no-untyped-def]
        attempted.set()
        raise RuntimeError("boom")

    queue = SerialRunQueue(fail)
    queue.enqueue(uuid4())

    assert attempted.wait(timeout=2)
    queue.close()
    assert "agent run worker failed" in caplog.text
