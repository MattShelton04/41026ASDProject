"""Keep the entrypoint's logger configuration from leaking between tests."""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest
from mcp_server.observability import LOGGER_NAMES


@pytest.fixture(autouse=True)
def restore_service_loggers() -> Iterator[None]:
    loggers = [logging.getLogger(name) for name in LOGGER_NAMES]
    saved = [(list(logger.handlers), logger.level, logger.propagate) for logger in loggers]
    yield
    for logger, (handlers, level, propagate) in zip(loggers, saved, strict=True):
        logger.handlers[:] = handlers
        logger.setLevel(level)
        logger.propagate = propagate
