"""Release readiness review routes: Feature 1's proxy to the shared Multi-Agent Server.

The browser never talks to the Multi-Agent Server. These routes pin the workflow template to
``f1-release-readiness-review``, scope every list to Feature 1, refuse runs that another feature
or template created, and relay the server's Problem Details unchanged. When the server is not
configured or not reachable they answer ``503 multi_agent_unavailable``; release review and
publication elsewhere in Feature 1 keep working.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from functools import wraps
from typing import Any

import httpx
from flask import Blueprint, Response, jsonify, request

from propertyscope_data_platform.assistant import ASSISTANT_FEATURE_KEY
from propertyscope_data_platform.clients import DependencyUnavailableError, MultiAgentClient
from propertyscope_data_platform.http_support import forward, problem, upstream_json_object
from shared_contracts.multi_agent import MAX_RUN_PAGE_LIMIT, WORKFLOW_RUN_ID_HEADER

RELEASE_REVIEW_TEMPLATE_ID = "f1-release-readiness-review"
RELEASE_REVIEW_FEATURE_ID = ASSISTANT_FEATURE_KEY
DEFAULT_RELEASE_REVIEW_PAGE_LIMIT = 20
HISTORY_CURSORS = ("after_history", "after_audit")
_START_FIELDS = frozenset({"input", "requested_by", "template_id"})
_INVALID_REQUEST = "invalid_release_review_request"
# Names and notes end up in the run's audit trail, so the proxy checks them before relaying.
# Feature 1 has no authenticated operator identity: names stay caller-supplied but bounded to
# letters, digits, spaces and a few name punctuation marks, starting with a letter or digit.
MAX_ACTOR_LENGTH = 100
MAX_NOTE_LENGTH = 2_000
_ACTOR = re.compile(r"[^\W_][\w .,'\N{RIGHT SINGLE QUOTATION MARK}@()-]*")
# Notes are free prose; line breaks and tabs are the only control characters they may contain.
_NOTE_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

RouteHandler = Callable[..., Response]
JsonObject = dict[str, Any]


def _review_route(handler: RouteHandler) -> RouteHandler:
    """Map an unavailable server to 503 and keep every review response out of caches."""

    @wraps(handler)
    def wrapper(*args: Any, **kwargs: Any) -> Response:
        try:
            response = handler(*args, **kwargs)
        except DependencyUnavailableError as exc:
            response = problem(503, "multi_agent_unavailable", str(exc))
        response.headers["Cache-Control"] = "no-store"
        return response

    return wrapper


def _object_body() -> dict[str, Any]:
    """Return the JSON object request body or raise ``ValueError``."""
    value: Any = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise ValueError("request body must be a JSON object")
    return value


class _FieldError(ValueError):
    """One rejected request field, reported as a structured ``invalid_release_review_request``."""

    def __init__(self, field: str, code: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.code = code

    def response(self) -> Response:
        return problem(
            422,
            _INVALID_REQUEST,
            str(self),
            errors=[{"field": self.field, "message": str(self), "code": self.code}],
        )


def checked_actor(value: Any, field: str) -> str:
    """Return a bounded, printable person or surface name for the audit trail."""
    if value is None:
        raise _FieldError(field, "invalid_actor", f"{field} is required")
    if not isinstance(value, str):
        raise _FieldError(field, "invalid_actor", f"{field} must be a string")
    actor = value.strip()
    if not actor:
        raise _FieldError(field, "invalid_actor", f"{field} must not be empty")
    if len(actor) > MAX_ACTOR_LENGTH:
        raise _FieldError(
            field, "invalid_actor", f"{field} must be at most {MAX_ACTOR_LENGTH} characters"
        )
    if _ACTOR.fullmatch(actor) is None:
        raise _FieldError(
            field,
            "invalid_actor",
            f"{field} must start with a letter or digit and contain only letters, digits, "
            "spaces and . , ' @ ( ) - _",
        )
    return actor


def checked_note(value: Any) -> str:
    """Return a bounded decision note without control characters other than line breaks."""
    if not isinstance(value, str):
        raise _FieldError("note", "invalid_note", "note must be a string")
    note = value.strip()
    if len(note) > MAX_NOTE_LENGTH:
        raise _FieldError(
            "note", "invalid_note", f"note must be at most {MAX_NOTE_LENGTH} characters"
        )
    if _NOTE_CONTROL.search(note):
        raise _FieldError("note", "invalid_note", "note must not contain control characters")
    return note


def _decision_body(body: dict[str, Any]) -> dict[str, Any]:
    """Check the decision's audit-trail text; the server still validates the decision itself."""
    checked = {**body, "actor": checked_actor(body.get("actor"), "actor")}
    if "note" in body:
        checked["note"] = checked_note(body["note"])
    return checked


READINESS_REVIEW_DISABLED_DETAIL = "Multi-agent review is not enabled in this deployment."
AI_REVIEW_DISABLED_DETAIL = "AI review is not enabled in this deployment."


def review_capabilities(*, multi_agent_configured: bool, ai_mode_configured: bool) -> JsonObject:
    """Which review actions this deployment enables, from configuration alone (no network).

    ``enabled`` is false only when the deployment gave the backend no credential for the service,
    as in the cloud baseline with the AI tier off. An enabled service can still be temporarily
    unreachable; its own routes then answer 503 as before.
    """
    return {
        "readiness_review": {
            "enabled": multi_agent_configured,
            "detail": None if multi_agent_configured else READINESS_REVIEW_DISABLED_DETAIL,
        },
        "ai_review": {
            "enabled": ai_mode_configured,
            "detail": None if ai_mode_configured else AI_REVIEW_DISABLED_DETAIL,
        },
    }


def register_release_review_routes(
    api: Blueprint, multi_agent: MultiAgentClient, *, base: str
) -> None:
    """Register the release-review proxy family on Feature 1's public Blueprint."""
    collection = f"{base}/release-reviews"

    def owned_run(run_id: uuid.UUID) -> tuple[httpx.Response, Response | None]:
        """Load a run; the second value is the refusal to send when it is not Feature 1's review."""
        detail = multi_agent.get_run(run_id, request.headers)
        if detail.status_code >= 400:
            return detail, forward(detail)
        run = upstream_json_object(detail)
        if (
            run.get("feature_id") != RELEASE_REVIEW_FEATURE_ID
            or run.get("template_id") != RELEASE_REVIEW_TEMPLATE_ID
        ):
            return detail, problem(404, "release_review_not_found", "Release review does not exist")
        return detail, None

    @api.get(f"{collection}/template")
    @_review_route
    def release_review_template() -> Response:
        return forward(multi_agent.template(RELEASE_REVIEW_TEMPLATE_ID, request.headers))

    @api.post(collection)
    @_review_route
    def start_release_review() -> Response:
        try:
            body = _object_body()
        except ValueError as exc:
            return problem(422, _INVALID_REQUEST, str(exc))
        unexpected = sorted(set(body) - _START_FIELDS)
        if unexpected:
            return problem(422, _INVALID_REQUEST, f"unexpected field(s): {', '.join(unexpected)}")
        workflow_input = body.get("input")
        if not isinstance(workflow_input, dict):
            return problem(422, _INVALID_REQUEST, "input must be a JSON object")
        # The template is fixed here: a client-supplied template_id is never forwarded.
        payload: dict[str, Any] = {
            "template_id": RELEASE_REVIEW_TEMPLATE_ID,
            "input": workflow_input,
        }
        if body.get("requested_by") is not None:
            try:
                payload["requested_by"] = checked_actor(body["requested_by"], "requested_by")
            except _FieldError as exc:
                return exc.response()
        upstream = multi_agent.create_run(payload, request.headers)
        response = forward(upstream)
        response.headers.pop("Location", None)
        if upstream.status_code == 202:
            try:
                run_id = uuid.UUID(str(upstream_json_object(upstream).get("id", "")))
            except ValueError as exc:
                raise DependencyUnavailableError(
                    "The Multi-Agent Server returned an invalid run identifier"
                ) from exc
            # Point the browser at this feature's route, never at the host server.
            response.headers["Location"] = f"{collection}/{run_id}"
            response.headers[WORKFLOW_RUN_ID_HEADER] = str(run_id)
        return response

    @api.get(collection)
    @_review_route
    def list_release_reviews() -> Response:
        params: dict[str, str | int] = {
            "template_id": RELEASE_REVIEW_TEMPLATE_ID,
            "feature_id": RELEASE_REVIEW_FEATURE_ID,
        }
        raw_limit = request.args.getlist("limit")
        if raw_limit:
            try:
                limit = int(raw_limit[-1])
            except ValueError:
                return problem(422, _INVALID_REQUEST, "limit must be an integer")
            params["limit"] = min(max(limit, 1), MAX_RUN_PAGE_LIMIT)
        else:
            params["limit"] = DEFAULT_RELEASE_REVIEW_PAGE_LIMIT
        states = request.args.getlist("state")
        if states and states[-1]:
            params["state"] = states[-1]
        upstream = multi_agent.list_runs(params, request.headers)
        if upstream.status_code != 200:
            return forward(upstream)
        page = upstream_json_object(upstream)
        raw_items = page.get("items")
        # Defence in depth: the server already filtered by query, but never leak another run.
        items = [
            item
            for item in (raw_items if isinstance(raw_items, list) else [])
            if isinstance(item, dict)
            and item.get("feature_id") == RELEASE_REVIEW_FEATURE_ID
            and item.get("template_id") == RELEASE_REVIEW_TEMPLATE_ID
        ]
        return jsonify({"items": items, "count": len(items)})

    @api.get(f"{collection}/<uuid:run_id>")
    @_review_route
    def release_review_detail(run_id: uuid.UUID) -> Response:
        detail, refused = owned_run(run_id)
        return refused if refused is not None else forward(detail)

    @api.post(f"{collection}/<uuid:run_id>/decision")
    @_review_route
    def decide_release_review(run_id: uuid.UUID) -> Response:
        try:
            body = _decision_body(_object_body())
        except _FieldError as exc:
            return exc.response()
        except ValueError as exc:
            return problem(422, _INVALID_REQUEST, str(exc))
        _, refused = owned_run(run_id)
        if refused is not None:
            return refused
        return forward(multi_agent.decide(run_id, body, request.headers))

    @api.post(f"{collection}/<uuid:run_id>/cancel")
    @_review_route
    def cancel_release_review(run_id: uuid.UUID) -> Response:
        body: dict[str, Any] | None = None
        if request.data:
            try:
                body = _object_body()
                if body.get("actor") is not None:
                    body = {**body, "actor": checked_actor(body["actor"], "actor")}
            except _FieldError as exc:
                return exc.response()
            except ValueError as exc:
                return problem(422, _INVALID_REQUEST, str(exc))
        _, refused = owned_run(run_id)
        if refused is not None:
            return refused
        return forward(multi_agent.cancel(run_id, body, request.headers))

    @api.get(f"{collection}/<uuid:run_id>/history")
    @_review_route
    def release_review_history(run_id: uuid.UUID) -> Response:
        _, refused = owned_run(run_id)
        if refused is not None:
            return refused
        # Incremental polling cursors pass through; the server validates them and its
        # Problem Details are relayed unchanged.
        cursors: dict[str, str | int] = {
            name: values[-1]
            for name in HISTORY_CURSORS
            if (values := request.args.getlist(name)) and values[-1]
        }
        return forward(multi_agent.history(run_id, request.headers, cursors))
