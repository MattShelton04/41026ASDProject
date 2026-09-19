"""Versioned HTTP API for persisted agent runs."""

from __future__ import annotations

import logging
from hashlib import sha256
from typing import cast
from uuid import UUID

from flask import Blueprint, Response, current_app, g, jsonify, request, url_for
from pydantic import ValidationError

from agent_core import (
    TERMINAL_STATUSES,
    AgentCoreError,
    ConcurrentRunUpdateError,
    apply_human_review,
    create_run,
)
from ai_mode.http import problem_response as _problem
from ai_mode.http import validation_issues
from ai_mode.persistence import IdempotencyConflictError, PersistenceError
from ai_mode.queue import RunQueueFullError
from ai_mode.services import AppServices
from shared_contracts import (
    AGENT_RUN_ID_HEADER,
    DEFAULT_EVENT_PAGE_SIZE,
    IDEMPOTENCY_KEY_HEADER,
    LAST_EVENT_ID_HEADER,
    MAX_EVENT_CURSOR,
    MAX_EVENT_PAGE_SIZE,
    MAX_IDEMPOTENCY_KEY_LENGTH,
    AgentRunEventPage,
    AgentRunRequest,
    HumanReviewRequest,
    ModelRoleName,
    ReviewDecision,
)
from shared_contracts.grounding import RETRIEVAL_TOOL

api = Blueprint("agent_api", __name__, url_prefix="/api/v1")
LOGGER = logging.getLogger(__name__)


def _services() -> AppServices:
    return cast(AppServices, current_app.extensions["ai_mode_services"])


def _request_hash(command: AgentRunRequest) -> str:
    """Preserve hashes for legacy requests that predate the empty trust ledger field."""
    exclude = set()
    if not command.trusted_identifiers:
        exclude.add("trusted_identifiers")
    if command.grounding is None:
        exclude.add("grounding")
    payload = command.model_dump_json(exclude=exclude)
    return sha256(payload.encode("utf-8")).hexdigest()


@api.post("/agent-runs")
def create_agent_run() -> tuple[Response, int, dict[str, str]] | tuple[Response, int]:
    """Validate, persist, and enqueue a bounded agent run."""
    if not request.is_json:
        return _problem(415, "unsupported_media_type", "Content-Type must be application/json")
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _problem(400, "invalid_json", "Request body must be a JSON object")
    services = _services()
    effective_payload = dict(payload)
    effective_payload.setdefault("model_profile", services.default_model_profile)
    corpus = dict(services.rag_corpora).get(str(effective_payload.get("feature_key", "")))
    if corpus is not None:
        if effective_payload.get("grounding") is None:
            effective_payload["grounding"] = {"corpus_id": corpus}
        effective_payload["prompt_set"] = "default.v9"
        allowlist = effective_payload.get("tool_allowlist")
        if isinstance(allowlist, list) and RETRIEVAL_TOOL not in allowlist:
            effective_payload["tool_allowlist"] = [*allowlist, RETRIEVAL_TOOL]
    try:
        command = AgentRunRequest.model_validate(effective_payload)
    except ValidationError as exc:
        return _problem(
            422,
            "validation_failed",
            "Request validation failed",
            errors=validation_issues(exc),
        )
    if command.grounding is not None and command.grounding.corpus_id != corpus:
        return _problem(
            422, "grounding_scope_unavailable", "Grounding scope is not enabled for this feature"
        )

    if services.model_registry is not None:
        profile = services.model_registry.profile(command.model_profile)
        if profile is None:
            return _problem(
                422,
                "model_profile_not_supported",
                f"Model profile is not registered: {command.model_profile}",
            )
        if not profile.supports(ModelRoleName.PLANNER, ModelRoleName.ADAPTER):
            return _problem(
                422,
                "model_profile_role_incompatible",
                "Model profile must support the planner and adapter roles",
            )
    run = create_run(
        command,
        run_id=services.ids.new(),
        request_id=g.request_id,
        now=services.clock.now(),
        traceparent=g.traceparent,
    )
    idempotency_key = request.headers.get(IDEMPOTENCY_KEY_HEADER, "").strip()
    if len(idempotency_key) > MAX_IDEMPOTENCY_KEY_LENGTH:
        return _problem(400, "idempotency_key_invalid", "Idempotency-Key is too long")
    created = True
    try:
        if idempotency_key:
            request_hash = _request_hash(command)
            run, created = services.store.create_or_get(
                run,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
        else:
            services.store.create(run)
    except IdempotencyConflictError as exc:
        return _problem(409, "idempotency_conflict", str(exc))
    except PersistenceError:
        return _problem(503, "state_store_unavailable", "Agent run could not be persisted")
    if created:
        _signal_run(services, run.id)
    location = url_for("agent_api.get_agent_run", run_id=run.id)
    response = jsonify(run.model_dump(mode="json"))
    response.headers[AGENT_RUN_ID_HEADER] = str(run.id)
    return response, 202, {"Location": location}


@api.get("/model-profiles")
def get_model_profiles() -> tuple[Response, int]:
    """Return safe supported-model metadata and operational profile limits."""
    services = _services()
    registry = services.model_registry
    if registry is None:
        return _problem(503, "model_registry_unavailable", "Model registry is unavailable")
    payload = registry.model_dump(mode="json")
    payload["default_profile"] = services.default_model_profile
    return jsonify(payload), 200


@api.get("/agent-runs/<uuid:run_id>")
def get_agent_run(run_id: UUID) -> tuple[Response, int]:
    """Return a safe current snapshot and ordered four-phase history."""
    detail = _services().store.get(run_id)
    if detail is None:
        return _problem(404, "agent_run_not_found", "Agent run does not exist")
    response = jsonify(detail.model_dump(mode="json"))
    response.headers[AGENT_RUN_ID_HEADER] = str(run_id)
    return response, 200


@api.get("/agent-runs/<uuid:run_id>/events")
def get_agent_run_events(run_id: UUID) -> tuple[Response, int]:
    """Return resumable, ordered progress events using an exclusive cursor."""
    detail = _services().store.get(run_id)
    if detail is None:
        return _problem(404, "agent_run_not_found", "Agent run does not exist")
    raw_cursor = request.headers.get(LAST_EVENT_ID_HEADER) or request.args.get("after", "0")
    raw_limit = request.args.get("limit", str(DEFAULT_EVENT_PAGE_SIZE))
    try:
        cursor = int(raw_cursor)
        limit = int(raw_limit)
    except ValueError:
        return _problem(400, "event_cursor_invalid", "Event cursor and limit must be integers")
    if not 0 <= cursor <= MAX_EVENT_CURSOR or not 1 <= limit <= MAX_EVENT_PAGE_SIZE:
        return _problem(
            400,
            "event_cursor_invalid",
            f"Event cursor is out of range or limit is not between 1 and {MAX_EVENT_PAGE_SIZE}",
        )
    available = _services().store.list_events(run_id, after_id=cursor, limit=limit + 1)
    events = available[:limit]
    has_more = len(available) > limit
    page = AgentRunEventPage(
        items=events,
        next_cursor=events[-1].id if events else cursor,
        terminal=detail.run.status in TERMINAL_STATUSES and not has_more,
    )
    response = jsonify(page.model_dump(mode="json"))
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
    if not request.is_json:
        return _problem(415, "unsupported_media_type", "Content-Type must be application/json")
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _problem(400, "invalid_json", "Request body must be a JSON object")
    try:
        command = HumanReviewRequest.model_validate(payload)
    except ValidationError as exc:
        return _problem(
            422,
            "validation_failed",
            "Review validation failed",
            errors=validation_issues(exc),
        )
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
    try:
        services.store.save(
            application.run,
            expected_version=detail.run.version,
            step=application.step,
            review=application.review,
        )
    except ConcurrentRunUpdateError:
        return _problem(409, "run_concurrently_updated", "Agent run was concurrently updated")
    except PersistenceError:
        return _problem(503, "state_store_unavailable", "Review could not be persisted")
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
        LOGGER.warning(
            "Run wake-up queue is full",
            extra={
                "event": "agent.queue.wakeup_dropped",
                "run_id": run_id,
                "outcome": "degraded",
                "error_code": "run_queue_full",
            },
        )
