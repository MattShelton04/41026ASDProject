"""Allowlisted one-line JSON tool-call logs on stdout, matching AI-mode's log schema.

Only identifiers, outcomes, reason categories and timing are serialized. Tool arguments,
structured results, signed invocation metadata, tokens and exception messages never reach a
log line, whatever a caller passes.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime
from enum import Enum
from typing import Final
from uuid import UUID

SERVICE_NAME: Final = "mcp-server"
# The shared runtime's feature-call records are surfaced in the same format.
LOGGER_NAMES: Final = ("mcp_server", "shared_tool_runtime")
SUPPORTED_LOG_LEVELS: Final = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})

_CORE_CONTEXT_FIELDS: Final[tuple[str, ...]] = (
    "request_id",
    "run_id",
    "step_id",
    "tool_call_id",
    "feature_key",
    "outcome",
    "duration_ms",
    "error_code",
)
_OPTIONAL_FIELDS: Final[tuple[str, ...]] = (
    "tool_name",
    "tool_version",
    "tool_outcome",
    "retryable",
)


class JsonLogFormatter(logging.Formatter):
    """Render an allowlisted, one-line event without serializing arbitrary extras."""

    def __init__(self, *, service: str = SERVICE_NAME, environment: str = "local") -> None:
        super().__init__()
        self._service = service
        self._environment = environment

    def format(self, record: logging.LogRecord) -> str:
        """Return one deterministic-schema JSON object suitable for the host log file."""
        payload: dict[str, object | None] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname.lower(),
            "service": self._service,
            "environment": self._environment,
            "event": getattr(record, "event", record.name),
            "message": record.getMessage(),
        }
        for field in _CORE_CONTEXT_FIELDS:
            payload[field] = _json_value(getattr(record, field, None))
        for field in _OPTIONAL_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = _json_value(value)
        if record.exc_info is not None and record.exc_info[0] is not None:
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def log_level_from_environment() -> str:
    """Read ``MCP_LOG_LEVEL`` (default INFO), failing closed on unsupported names."""
    level = os.environ.get("MCP_LOG_LEVEL", "INFO").strip().upper()
    if level not in SUPPORTED_LOG_LEVELS:
        raise ValueError("MCP_LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL")
    return level


def configure_structured_logging(level: str, *, environment: str = "local") -> None:
    """Send the service loggers to stdout once, leaving third-party and root loggers alone."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLogFormatter(environment=environment))
    for name in LOGGER_NAMES:
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.addHandler(handler)
        logger.setLevel(level)
        logger.propagate = False


def _json_value(value: object) -> object:
    if isinstance(value, Enum):
        return _json_value(value.value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
