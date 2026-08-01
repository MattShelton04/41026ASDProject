"""Development-only authenticated HTML evidence view for agent runs."""

from __future__ import annotations

import html
import json
import secrets
from collections.abc import Mapping, Sequence
from typing import cast
from uuid import UUID

from flask import Blueprint, Response, current_app, request

from ai_mode.services import AppServices

SENSITIVE_KEYS = frozenset({"api_key", "authorization", "cookie", "password", "secret", "token"})


def create_evidence_blueprint(access_token: str) -> Blueprint:
    """Create the optional view only when an explicit access token is configured."""
    blueprint = Blueprint("agent_evidence", __name__, url_prefix="/development/agent-runs")

    @blueprint.get("/<uuid:run_id>")
    def run_detail(run_id: UUID) -> Response:
        supplied = request.headers.get("Authorization", "")
        expected = f"Bearer {access_token}"
        if not secrets.compare_digest(supplied, expected):
            return Response("Not found", status=404, content_type="text/plain; charset=utf-8")
        services = cast(AppServices, current_app.extensions["ai_mode_services"])
        detail = services.store.get(run_id)
        if detail is None:
            return Response("Not found", status=404, content_type="text/plain; charset=utf-8")
        safe_json = json.dumps(
            _redact(detail.model_dump(mode="json")),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Agent run evidence</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem auto;
            max-width: 72rem; padding: 0 1rem; }}
    pre {{ background: #111827; color: #e5e7eb; overflow: auto;
           padding: 1rem; border-radius: .5rem; }}
  </style>
</head>
<body>
  <h1>Agent run evidence</h1>
  <p>Safe persisted state for <code>{html.escape(str(run_id))}</code>.</p>
  <pre>{html.escape(safe_json)}</pre>
</body>
</html>"""
        return Response(document, status=200, content_type="text/html; charset=utf-8")

    return blueprint


def _redact(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if str(key).lower() in SENSITIVE_KEYS else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_redact(item) for item in value]
    return value
