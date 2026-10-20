"""Market case brief routes: Feature 2's proxy to the shared Multi-Agent Server.

The browser never talks to the Multi-Agent Server; its service token must not reach the page.
These routes pin the workflow template to ``f2-market-case-brief``, scope every list to Feature 2,
refuse runs another feature or template created, and relay the server's Problem Details unchanged.
When the server is unconfigured or unreachable they answer ``503 multi_agent_unavailable`` and the
rest of Feature 2 - saved cases, evidence tables and deterministic summaries - keeps working.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Mapping
from functools import wraps
from typing import Any

import httpx
from flask import Blueprint, Response, jsonify, request

from propertyscope_market_intelligence.clients import (
    DependencyUnavailableError,
    MultiAgentClient,
)
from propertyscope_market_intelligence.domain import FEATURE_KEY
from shared_contracts import REQUEST_ID_HEADER
from shared_contracts.multi_agent import MAX_RUN_PAGE_LIMIT, WORKFLOW_RUN_ID_HEADER

MARKET_BRIEF_TEMPLATE_ID = "f2-market-case-brief"
MARKET_BRIEF_FEATURE_ID = FEATURE_KEY
DEFAULT_MARKET_BRIEF_PAGE_LIMIT = 20
HISTORY_CURSORS = ("after_history", "after_audit")
_START_FIELDS = frozenset({"input", "requested_by", "template_id"})
_INVALID_REQUEST = "invalid_market_brief_request"
_PROBLEM_MEDIA_TYPE = "application/problem+json"
# Names and notes land in the run's audit trail, so the proxy bounds them before relaying.
# Feature 2 has no authenticated operator identity: names stay caller-supplied but bounded to
# letters, digits, spaces and a little name punctuation, starting with a letter or digit.
MAX_ACTOR_LENGTH = 100
MAX_NOTE_LENGTH = 2_000
_ACTOR = re.compile(r"[^\W_][\w .,'\N{RIGHT SINGLE QUOTATION MARK}@()-]*")
# Notes are free prose; line breaks and tabs are the only control characters they may carry.
_NOTE_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_RELAYED_RESPONSE_HEADERS = (REQUEST_ID_HEADER, WORKFLOW_RUN_ID_HEADER)

RouteHandler = Callable[..., Response]
JsonObject = dict[str, Any]

# True of both causes: the AI tier is off, or the host server is not running.
MARKET_BRIEF_DISABLED_DETAIL = "Multi-agent market briefs are not available in this deployment."


def brief_capabilities(*, multi_agent_available: bool) -> JsonObject:
    """Whether a market brief could run now: the server is configured and answering.

    Configuration alone is not enough to decide this. Every stack `dev.py` starts is issued a
    service token, but the Multi-Agent Server is a host process that CI never starts, so a
    configured backend can still have nothing to reach. The page asks this before it mounts the
    panel, so a deployment without the server shows one plain sentence instead of a panel whose
    first request answers 503.
    """
    return {
        "market_brief": {
            "enabled": multi_agent_available,
            "detail": None if multi_agent_available else MARKET_BRIEF_DISABLED_DETAIL,
        }
    }


def _problem(
    status: int, code: str, detail: str, *, errors: list[dict[str, str]] | None = None
) -> Response:
    """Problem Details; ``errors`` lists field issues as ``{field, message, code}``."""
    body: JsonObject = {
        "type": f"https://propertyscope.local/problems/{code}",
        "title": code.replace("_", " ").title(),
        "status": status,
        "detail": detail,
        "code": code,
        "request_id": request.headers.get(REQUEST_ID_HEADER, "unknown"),
    }
    if errors:
        body["errors"] = errors
    response = jsonify(body)
    response.status_code = status
    response.content_type = _PROBLEM_MEDIA_TYPE
    return response


def _upstream_object(upstream: httpx.Response) -> JsonObject:
    """Reject an unreadable dependency payload without blaming the caller or leaking the body."""
    try:
        data = upstream.json()
    except ValueError as exc:
        raise DependencyUnavailableError(
            "The Multi-Agent Server returned an unreadable JSON response"
        ) from exc
    if not isinstance(data, dict):
        raise DependencyUnavailableError("The Multi-Agent Server returned an invalid JSON response")
    return data


def _forward(upstream: httpx.Response) -> Response:
    """Project an upstream response and its correlation headers onto Flask."""
    if upstream.is_redirect:
        raise DependencyUnavailableError("The Multi-Agent Server returned an unexpected redirect")
    response = jsonify(_upstream_object(upstream))
    response.status_code = upstream.status_code
    if upstream.headers.get("content-type", "").split(";", 1)[0] == _PROBLEM_MEDIA_TYPE:
        response.content_type = _PROBLEM_MEDIA_TYPE
    for name in _RELAYED_RESPONSE_HEADERS:
        if name in upstream.headers:
            response.headers[name] = upstream.headers[name]
    return response


def _review_route(handler: RouteHandler) -> RouteHandler:
    """Map an unavailable server to 503 and keep every brief response out of caches."""

    @wraps(handler)
    def wrapper(*args: Any, **kwargs: Any) -> Response:
        try:
            response = handler(*args, **kwargs)
        except DependencyUnavailableError as exc:
            response = _problem(503, "multi_agent_unavailable", str(exc))
        response.headers["Cache-Control"] = "no-store"
        return response

    return wrapper


def _object_body() -> JsonObject:
    """Return the JSON object request body or raise ``ValueError``."""
    value: Any = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise ValueError("request body must be a JSON object")
    return value


class _FieldError(ValueError):
    """One rejected request field, reported as a structured ``invalid_market_brief_request``."""

    def __init__(self, field: str, code: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.code = code

    def response(self) -> Response:
        return _problem(
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


def _decision_body(body: JsonObject) -> JsonObject:
    """Check the decision's audit-trail text; the server still validates the decision itself."""
    checked = {**body, "actor": checked_actor(body.get("actor"), "actor")}
    if "note" in body:
        checked["note"] = checked_note(body["note"])
    return checked


def _page_limit(raw: list[str]) -> int | Response:
    """Return a bounded page limit, or the refusal to send for a non-integer one."""
    if not raw:
        return DEFAULT_MARKET_BRIEF_PAGE_LIMIT
    try:
        limit = int(raw[-1])
    except ValueError:
        return _problem(422, _INVALID_REQUEST, "limit must be an integer")
    return min(max(limit, 1), MAX_RUN_PAGE_LIMIT)


def register_market_review_routes(
    api: Blueprint, multi_agent: MultiAgentClient, *, base: str
) -> None:
    """Register the market-brief proxy family on Feature 2's public Blueprint."""
    collection = f"{base}/market-briefs"

    def owned_run(run_id: uuid.UUID) -> tuple[httpx.Response, Response | None]:
        """Load a run; the second value is the refusal to send when it is not Feature 2's brief."""
        detail = multi_agent.get_run(run_id, request.headers)
        if detail.status_code >= 400:
            return detail, _forward(detail)
        run = _upstream_object(detail)
        if (
            run.get("feature_id") != MARKET_BRIEF_FEATURE_ID
            or run.get("template_id") != MARKET_BRIEF_TEMPLATE_ID
        ):
            return detail, _problem(404, "market_brief_not_found", "Market brief does not exist")
        return detail, None

    # Deliberately not wrapped in _review_route: a deployment with no reachable server must
    # get 200 and a clear "disabled" here, not the 503 every other brief route gives. The probe
    # is bounded and liveness-only; the page asks this before it mounts the panel.
    @api.get(f"{collection}/capabilities")
    def market_brief_capabilities() -> Response:
        return jsonify(brief_capabilities(multi_agent_available=multi_agent.available()))

    @api.get(f"{collection}/template")
    @_review_route
    def market_brief_template() -> Response:
        return _forward(multi_agent.template(MARKET_BRIEF_TEMPLATE_ID, request.headers))

    @api.post(collection)
    @_review_route
    def start_market_brief() -> Response:
        try:
            body = _object_body()
        except ValueError as exc:
            return _problem(422, _INVALID_REQUEST, str(exc))
        unexpected = sorted(set(body) - _START_FIELDS)
        if unexpected:
            return _problem(422, _INVALID_REQUEST, f"unexpected field(s): {', '.join(unexpected)}")
        workflow_input = body.get("input")
        if not isinstance(workflow_input, dict):
            return _problem(422, _INVALID_REQUEST, "input must be a JSON object")
        # The template is fixed here: a client-supplied template_id is never forwarded.
        payload: JsonObject = {
            "template_id": MARKET_BRIEF_TEMPLATE_ID,
            "input": workflow_input,
        }
        if body.get("requested_by") is not None:
            try:
                payload["requested_by"] = checked_actor(body["requested_by"], "requested_by")
            except _FieldError as exc:
                return exc.response()
        upstream = multi_agent.create_run(payload, request.headers)
        response = _forward(upstream)
        response.headers.pop("Location", None)
        if upstream.status_code == 202:
            try:
                run_id = uuid.UUID(str(_upstream_object(upstream).get("id", "")))
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
    def list_market_briefs() -> Response:
        limit = _page_limit(request.args.getlist("limit"))
        if isinstance(limit, Response):
            return limit
        params: dict[str, str | int] = {
            "template_id": MARKET_BRIEF_TEMPLATE_ID,
            "feature_id": MARKET_BRIEF_FEATURE_ID,
            "limit": limit,
        }
        states = request.args.getlist("state")
        if states and states[-1]:
            params["state"] = states[-1]
        upstream = multi_agent.list_runs(params, request.headers)
        if upstream.status_code != 200:
            return _forward(upstream)
        page = _upstream_object(upstream)
        raw_items = page.get("items")
        # Defence in depth: the server already filtered by query, but never leak another run.
        items = [
            item
            for item in (raw_items if isinstance(raw_items, list) else [])
            if isinstance(item, Mapping)
            and item.get("feature_id") == MARKET_BRIEF_FEATURE_ID
            and item.get("template_id") == MARKET_BRIEF_TEMPLATE_ID
        ]
        return jsonify({"items": items, "count": len(items)})

    @api.get(f"{collection}/<uuid:run_id>")
    @_review_route
    def market_brief_detail(run_id: uuid.UUID) -> Response:
        detail, refused = owned_run(run_id)
        return refused if refused is not None else _forward(detail)

    @api.post(f"{collection}/<uuid:run_id>/decision")
    @_review_route
    def decide_market_brief(run_id: uuid.UUID) -> Response:
        try:
            body = _decision_body(_object_body())
        except _FieldError as exc:
            return exc.response()
        except ValueError as exc:
            return _problem(422, _INVALID_REQUEST, str(exc))
        _, refused = owned_run(run_id)
        if refused is not None:
            return refused
        return _forward(multi_agent.decide(run_id, body, request.headers))

    @api.post(f"{collection}/<uuid:run_id>/cancel")
    @_review_route
    def cancel_market_brief(run_id: uuid.UUID) -> Response:
        body: JsonObject | None = None
        if request.data:
            try:
                body = _object_body()
                if body.get("actor") is not None:
                    body = {**body, "actor": checked_actor(body["actor"], "actor")}
            except _FieldError as exc:
                return exc.response()
            except ValueError as exc:
                return _problem(422, _INVALID_REQUEST, str(exc))
        _, refused = owned_run(run_id)
        if refused is not None:
            return refused
        return _forward(multi_agent.cancel(run_id, body, request.headers))

    @api.get(f"{collection}/<uuid:run_id>/history")
    @_review_route
    def market_brief_history(run_id: uuid.UUID) -> Response:
        _, refused = owned_run(run_id)
        if refused is not None:
            return refused
        # Incremental polling cursors pass through unchanged; the server validates them and its
        # Problem Details are relayed as-is.
        cursors: dict[str, str | int] = {
            name: values[-1]
            for name in HISTORY_CURSORS
            if (values := request.args.getlist(name)) and values[-1]
        }
        return _forward(multi_agent.history(run_id, request.headers, cursors))
