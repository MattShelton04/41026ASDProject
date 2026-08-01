"""Versioned HTTP API for persisted agent runs."""

from __future__ import annotations

import logging
from typing import cast
from uuid import UUID

from flask import Blueprint, Response, current_app, g, jsonify, request, url_for
from pydantic import ValidationError

from agent_core import AgentCoreError, apply_human_review, create_run
from ai_mode.queue import RunQueueFullError
from ai_mode.services import AppServices
from shared_contracts import (
    AGENT_RUN_ID_HEADER,
    AgentRunRequest,
    FieldIssue,
    HumanReviewRequest,
    ProblemDetail,
    ReviewDecision,
)

api = Blueprint("agent_api", __name__, url_prefix="/api/v1")
LOGGER = logging.getLogger(__name__)


def _services() -> AppServices:
    return cast(AppServices, current_app.extensions["ai_mode_services"])


@api.post("/agent-runs")
def create_agent_run() -> tuple[Response, int, dict[str, str]] | tuple[Response, int]:
    """Validate, persist, and enqueue a bounded agent run."""
    if not request.is_json:
        return _problem(415, "unsupported_media_type", "Content-Type must be application/json")
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _problem(400, "invalid_json", "Request body must be a JSON object")
    try:
        command = AgentRunRequest.model_validate(payload)
    except ValidationError as exc:
        issues = tuple(
            FieldIssue(
                field=".".join(str(part) for part in error["loc"]),
                message=error["msg"],
                code=error["type"],
            )
            for error in exc.errors(include_url=False)
        )
        return _problem(422, "validation_failed", "Request validation failed", errors=issues)

    services = _services()
    run = create_run(
        command,
        run_id=services.ids.new(),
        request_id=g.request_id,
        now=services.clock.now(),
    )
    services.store.create(run)
    _signal_run(services, run.id)
    location = url_for("agent_api.get_agent_run", run_id=run.id)
    response = jsonify(run.model_dump(mode="json"))
    response.headers[AGENT_RUN_ID_HEADER] = str(run.id)
    return response, 202, {"Location": location}


@api.get("/agent-runs/<uuid:run_id>")
def get_agent_run(run_id: UUID) -> tuple[Response, int]:
    """Return a safe current snapshot and ordered four-phase history."""
    detail = _services().store.get(run_id)
    if detail is None:
        return _problem(404, "agent_run_not_found", "Agent run does not exist")
    response = jsonify(detail.model_dump(mode="json"))
    response.headers[AGENT_RUN_ID_HEADER] = str(run_id)
    return response, 200


@api.post("/agent-runs/<uuid:run_id>/cancel")
def cancel_agent_run(run_id: UUID) -> tuple[Response, int]:
    """Idempotently record cancellation intent at the state owner."""
    run = _services().store.request_cancellation(run_id, now=_services().clock.now())
    if run is None:
        return _problem(404, "agent_run_not_found", "Agent run does not exist")
    _signal_run(_services(), run_id)
    response = jsonify(run.model_dump(mode="json"))
    response.headers[AGENT_RUN_ID_HEADER] = str(run_id)
    return response, 200


@api.post("/agent-runs/<uuid:run_id>/reviews")
def review_agent_run(run_id: UUID) -> tuple[Response, int]:
    """Approve or reject exactly one pending protected action."""
    payload = request.get_json(silent=True) if request.is_json else None
    if not isinstance(payload, dict):
        return _problem(400, "invalid_json", "Request body must be a JSON object")
    try:
        command = HumanReviewRequest.model_validate(payload)
    except ValidationError as exc:
        issues = tuple(
            FieldIssue(
                field=".".join(str(part) for part in error["loc"]),
                message=error["msg"],
                code=error["type"],
            )
            for error in exc.errors(include_url=False)
        )
        return _problem(422, "validation_failed", "Review validation failed", errors=issues)
    services = _services()
    detail = services.store.get(run_id)
    if detail is None:
        return _problem(404, "agent_run_not_found", "Agent run does not exist")
    try:
        application = apply_human_review(
            detail,
            command,
            review_id=services.ids.new(),
            now=services.clock.now(),
        )
    except AgentCoreError as exc:
        return _problem(409, "review_not_pending", str(exc))
    services.store.save(
        application.run,
        expected_version=detail.run.version,
        step=application.step,
        review=application.review,
    )
    if command.decision is ReviewDecision.APPROVE:
        _signal_run(services, run_id)
    refreshed = services.store.get(run_id)
    if refreshed is None:
        return _problem(503, "state_store_unavailable", "Reviewed run could not be reloaded")
    response = jsonify(refreshed.model_dump(mode="json"))
    response.headers[AGENT_RUN_ID_HEADER] = str(run_id)
    return response, 200


def _signal_run(services: AppServices, run_id: UUID) -> None:
    """Best-effort wake-up; durable worker discovery owns eventual scheduling."""
    try:
        services.queue.enqueue(run_id)
    except RunQueueFullError:
        LOGGER.warning("run wake-up queue is full", extra={"run_id": str(run_id)})


def _problem(
    status: int,
    code: str,
    detail: str,
    *,
    errors: tuple[FieldIssue, ...] = (),
) -> tuple[Response, int]:
    problem = ProblemDetail(
        title=_problem_title(status),
        status=status,
        detail=detail,
        code=code,
        instance=request.path,
        request_id=g.request_id,
        errors=errors,
    )
    response = jsonify(problem.model_dump(mode="json"))
    response.content_type = "application/problem+json"
    return response, status


def _problem_title(status: int) -> str:
    return {
        400: "Invalid JSON",
        404: "Not found",
        409: "Conflict",
        415: "Unsupported media type",
        422: "Invalid request",
        503: "Service unavailable",
    }.get(status, "Request failed")
