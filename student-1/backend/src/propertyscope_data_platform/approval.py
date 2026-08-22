"""Human-approval evidence verification at the AI-mode boundary."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from werkzeug.datastructures import Headers

from propertyscope_data_platform.clients import AiModeClient


def approved_tool_call(
    ai_mode: AiModeClient,
    headers: Mapping[str, str] | Headers,
    tool_name: str,
    arguments: Mapping[str, Any],
) -> bool:
    """Verify a protected callback against AI-mode's durable review evidence."""
    raw_run_id = headers.get("X-Agent-Run-ID", "").strip()
    try:
        run_id = uuid.UUID(raw_run_id)
    except ValueError:
        return False
    response = ai_mode.get(f"/api/v1/agent-runs/{run_id}", headers)
    if response.status_code != 200:
        return False
    reviews = response.json().get("reviews", [])
    return any(
        review.get("decision") == "approve"
        and review.get("tool_call", {}).get("tool_name") == tool_name
        and review.get("tool_call", {}).get("arguments") == dict(arguments)
        for review in reviews
        if isinstance(review, dict)
    )
