"""Safe structured stdout logging for AI-mode operational events."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from enum import Enum
from typing import Final
from uuid import UUID

_CORE_CONTEXT_FIELDS: Final[tuple[str, ...]] = (
    "request_id",
    "run_id",
    "step_id",
    "tool_call_id",
    "trace_id",
    "span_id",
    "feature_key",
    "outcome",
    "duration_ms",
    "error_code",
)
_OPTIONAL_FIELDS: Final[tuple[str, ...]] = (
    "status_code",
    "method",
    "path",
    "model",
    "model_profile",
    "model_role",
    "prompt_tokens",
    "output_tokens",
    "cached_prompt_tokens",
    "reasoning_tokens",
    "repair_count",
    "retryable",
    "tool_name",
    "tool_version",
    "run_status",
    "iteration_count",
    "tool_call_count",
)


class JsonLogFormatter(logging.Formatter):
    """Render an allowlisted, one-line event without serializing arbitrary extras."""

    def __init__(self, *, service: str, environment: str) -> None:
        super().__init__()
        self._service = service
        self._environment = environment

    def format(self, record: logging.LogRecord) -> str:
        """Return one deterministic-schema JSON object suitable for stdout collectors."""
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


def configure_structured_logging(*, service: str, environment: str, level: str) -> None:
    """Configure the service logger once without changing third-party/root loggers."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLogFormatter(service=service, environment=environment))
    logger = logging.getLogger("ai_mode")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False


def _json_value(value: object) -> object:
    if isinstance(value, (UUID, Enum)):
        return str(value.value if isinstance(value, Enum) else value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
