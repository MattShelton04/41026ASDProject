"""Release readiness review routes: Feature 1's proxy to the shared Multi-Agent Server.

The browser never talks to the Multi-Agent Server. These routes pin the workflow template to
``f1-release-readiness-review``, scope every list to Feature 1, refuse runs that another feature
or template created, and relay the server's Problem Details unchanged. When the server is not
configured or not reachable they answer ``503 multi_agent_unavailable``; release review and
publication elsewhere in Feature 1 keep working.
"""

from __future__ import annotations

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

RouteHandler = Callable[..., Response]


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
            payload["requested_by"] = body["requested_by"]
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
            body = _object_body()
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
