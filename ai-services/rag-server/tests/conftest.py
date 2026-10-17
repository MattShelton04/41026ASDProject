"""Keep environment-driven app factories from leaking logger configuration between tests."""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest
from rag_server.observability import LOGGER_NAME


@pytest.fixture(autouse=True)
def restore_service_logger() -> Iterator[None]:
    logger = logging.getLogger(LOGGER_NAME)
    handlers, level, propagate = list(logger.handlers), logger.level, logger.propagate
    yield
    logger.handlers[:] = handlers
    logger.setLevel(level)
    logger.propagate = propagate
