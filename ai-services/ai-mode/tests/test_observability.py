"""Tests for bounded structured operational logging."""

from __future__ import annotations

import json
import logging

from ai_mode.observability import JsonLogFormatter, configure_structured_logging


def test_json_formatter_emits_stable_context_without_arbitrary_extras() -> None:
    formatter = JsonLogFormatter(service="ai-mode", environment="test")
    record = logging.LogRecord(
        name="ai_mode.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Request completed",
        args=(),
        exc_info=None,
    )
    record.event = "http.request.completed"
    record.request_id = "request-123"
    record.duration_ms = 7
    record.secret_payload = "must-not-be-logged"

    payload = json.loads(formatter.format(record))

    assert payload["service"] == "ai-mode"
    assert payload["environment"] == "test"
    assert payload["event"] == "http.request.completed"
    assert payload["request_id"] == "request-123"
    assert payload["duration_ms"] == 7
    assert payload["run_id"] is None
    assert "secret_payload" not in payload


def test_logging_configuration_is_scoped_to_ai_mode() -> None:
    logger = logging.getLogger("ai_mode")
    previous = (logger.handlers[:], logger.level, logger.propagate)
    try:
        configure_structured_logging(service="ai-mode", environment="test", level="WARNING")

        assert logger.level == logging.WARNING
        assert logger.propagate is False
        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0].formatter, JsonLogFormatter)
    finally:
        for handler in logger.handlers:
            handler.close()
        logger.handlers = previous[0]
        logger.setLevel(previous[1])
        logger.propagate = previous[2]
