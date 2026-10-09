"""Internal service authentication for the host AI-mode listener."""

import re
import secrets

from flask import Flask, Response, jsonify, request

AI_SERVICE_TOKEN_HEADER = "X-PropertyScope-AI-Token"  # noqa: S105 - header name, not a secret


def validate_service_token(token: str) -> None:
    """Use one credential format for issuance and the HTTP entrypoint."""
    if re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token) is None:
        raise RuntimeError("AI_MODE_SERVICE_TOKEN must contain 32-128 URL-safe characters")


def protect_entry(application: Flask, token: str) -> None:
    """Protect readiness, API and history while keeping process liveness public."""
    validate_service_token(token)

    @application.before_request
    def authenticate_request() -> tuple[Response, int] | None:
        if request.path == "/health/live":
            return None
        supplied = request.headers.get(AI_SERVICE_TOKEN_HEADER, "")
        if not secrets.compare_digest(supplied.encode("utf-8"), token.encode("utf-8")):
            return jsonify(
                {"code": "unauthorized", "detail": "Service authentication required"}
            ), 401
        return None
