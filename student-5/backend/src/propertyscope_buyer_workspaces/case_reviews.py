"""Case-owned, read-only action plans over the host Multi-Agent HTTP contract."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from functools import wraps
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

from flask import Flask, Response, g, jsonify, request
from pydantic import ValidationError

from propertyscope_buyer_workspaces.api import _owned_case, _problem
from propertyscope_buyer_workspaces.clients import (
    BuyerStoreGateway,
    ClientResponse,
    DatabaseProtocolError,
    DatabaseUnavailableError,
    HttpTransport,
    UrllibTransport,
)
from propertyscope_buyer_workspaces.configuration import BackendSettings
from shared_contracts.multi_agent import (
    HumanDecisionRequest,
    WorkflowRun,
    WorkflowRunHistory,
    WorkflowRunPage,
    WorkflowTemplateDescriptor,
)

FEATURE = "student-5-buyer-journey"
TEMPLATE = "f5-buyer-case-action-plan"
TOOLS = ("buyer.action-plan.context.v1",)
SECTIONS = {
    "case": "tool_inspect_case",
    "notes": "tool_list_notes",
    "tasks": "tool_list_tasks",
    "evidence": "tool_collect_evidence",
}


def _scoped_arguments(arguments: Mapping[str, Any]) -> bool:
    return (
        set(arguments) == {"section"}
        and isinstance(arguments.get("section"), str)
        and arguments["section"] in SECTIONS
    )


class MultiAgentUnavailableError(RuntimeError):
    """No configured or reachable workflow service."""


class MultiAgentProtocolError(RuntimeError):
    """The dependency violated its public contract."""


class MultiAgentClient:
    """Send only server credentials and correlation to the configured host service."""

    def __init__(self, origin: str, token: str, *, transport: HttpTransport | None = None) -> None:
        self.origin = origin.rstrip("/")
        self._token = token
        self._transport = transport or UrllibTransport()

    @property
    def configured(self) -> bool:
        return bool(self._token.strip())

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, Any] | None = None,
        params: Mapping[str, str | int] | None = None,
    ) -> ClientResponse:
        if not self.configured:
            raise MultiAgentUnavailableError
        query = f"?{urlencode(params)}" if params else ""
        try:
            return self._transport.request(
                method,
                f"{self.origin}/api/v1/multi-agent{path}{query}",
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "X-Request-ID": g.request_id,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                params=None,
                json_body=body,
                timeout_seconds=10,
            )
        except DatabaseUnavailableError as exc:
            raise MultiAgentUnavailableError from exc
        except DatabaseProtocolError as exc:
            raise MultiAgentProtocolError from exc

    def create_run(self, body: Mapping[str, Any]) -> ClientResponse:
        return self.request("POST", "/runs", body=body)


def _body(allowed: set[str]) -> dict[str, Any]:
    value = request.get_json(silent=True)
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError("Submit an object containing only the supported fields")
    return value


def _actor(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value.strip()) <= 100
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise ValueError("Provide a name of up to 100 characters for the decision record")
    return value.strip()


def _json(response: ClientResponse) -> dict[str, Any]:
    try:
        value = response.json()
    except DatabaseProtocolError as exc:
        raise MultiAgentProtocolError from exc
    if not isinstance(value, dict):
        raise MultiAgentProtocolError
    return value


def _error(response: ClientResponse) -> tuple[Response, int] | None:
    if response.status_code < 400:
        return None
    # Preserve known error semantics, never echo transport text or arbitrary upstream bodies.
    code = _json(response).get("code")
    messages = {
        "invalid_request": "The workflow request is invalid",
        "invalid_request_body": "Check the workflow fields and try again",
        "invalid_workflow_input": "Check the case and review context",
        "invalid_state_transition": "Refresh the plan before recording another decision",
        "run_not_found": "The action plan does not exist",
        "template_not_found": "The action plan is not available in this deployment",
        "workflow_capacity_exceeded": "The workflow service is busy; try again later",
    }
    if response.status_code in {401, 403}:
        raise MultiAgentUnavailableError
    if code not in messages or response.status_code not in {400, 404, 409, 413, 422, 503}:
        raise MultiAgentProtocolError
    return _problem(response.status_code, code, messages[code])


def _template(response: ClientResponse) -> WorkflowTemplateDescriptor:
    descriptor = WorkflowTemplateDescriptor.model_validate(_json(response))
    if (
        descriptor.template.id != TEMPLATE
        or descriptor.template.feature_id != FEATURE
        or set(descriptor.template.allowed_tools) != set(TOOLS)
    ):
        raise MultiAgentProtocolError
    return descriptor


def _run(response: ClientResponse, case_id: UUID, run_id: UUID | None = None) -> WorkflowRun:
    value = WorkflowRun.model_validate(_json(response))
    if (
        value.feature_id != FEATURE
        or value.template_id != TEMPLATE
        or value.input.get("buyer_case_id") != str(case_id)
        or (run_id is not None and value.id != run_id)
    ):
        raise LookupError
    # A poisoned dependency must not expose evidence from another case through its plan.
    if value.plan:
        for step in value.plan.steps:
            if step.tool not in TOOLS or not _scoped_arguments(step.arguments):
                raise MultiAgentProtocolError
    outputs = [attempt.worker_output for attempt in value.superseded]
    if value.worker_output:
        outputs.append(value.worker_output)
    for output in outputs:
        for item in output.evidence:
            if item.tool_name not in TOOLS or not _scoped_arguments(item.arguments):
                raise MultiAgentProtocolError
    return value


def register_case_reviews(
    app: Flask, store: BuyerStoreGateway, settings: BackendSettings, multi_agent: MultiAgentClient
) -> None:
    """Every operation rechecks the case; run IDs never substitute for ownership."""
    base = "/api/buyer-workspaces/v1/buyer-cases/<uuid:case_id>"
    collection = f"{base}/evidence-reviews"

    @app.after_request
    def no_cache(response: Response) -> Response:
        if "/evidence-reviews" in request.path or request.path.endswith(
            "/buyer.action-plan.context.v1"
        ):
            response.headers["Cache-Control"] = "no-store"
        return response

    def guarded(handler: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(handler)
        def call(case_id: UUID, **kwargs: Any) -> Any:
            try:
                _, refused = _owned_case(store, settings, str(case_id), g.request_id)
                if refused is not None:
                    return refused
                return handler(case_id, **kwargs)
            except MultiAgentUnavailableError:
                return _problem(503, "multi_agent_unavailable", "Case action plans are unavailable")
            except (MultiAgentProtocolError, ValidationError):
                return _problem(
                    502,
                    "multi_agent_protocol_error",
                    "The workflow service returned an invalid response",
                )
            except LookupError:
                return _problem(404, "run_not_found", "The action plan does not exist in this case")
            except ValueError as exc:
                return _problem(422, "invalid_workflow_input", str(exc))

        return call

    def owned_run(case_id: UUID, run_id: UUID) -> WorkflowRun | tuple[Response, int]:
        upstream = multi_agent.request("GET", f"/runs/{run_id}")
        return _error(upstream) or _run(upstream, case_id, run_id)

    @app.post("/api/buyer-workspaces/v1/tools/buyer.action-plan.context.v1")
    def action_plan_context() -> Any:
        # X-Agent-Run-ID is supplied by the HTTP/MCP gateway, outside model arguments.
        # Read the persisted run to bind this invocation before any case record is read.
        try:
            run_id = UUID(request.headers.get("X-Agent-Run-ID", ""))
            body = _body({"section"})
            if not _scoped_arguments(body):
                raise ValueError("Select case, notes, tasks or evidence")
            upstream = multi_agent.request("GET", f"/runs/{run_id}")
            if error := _error(upstream):
                return error
            run = WorkflowRun.model_validate(_json(upstream))
            case_id = UUID(str(run.input.get("buyer_case_id", "")))
            _run(upstream, case_id, run_id)
            _, refused = _owned_case(store, settings, str(case_id), g.request_id)
            if refused is not None:
                return refused
            # These are the existing bounded case readers, with the server-selected ID.
            return app.view_functions[SECTIONS[body["section"]]](case_id=str(case_id))
        except MultiAgentUnavailableError:
            return _problem(503, "multi_agent_unavailable", "Case action plans are unavailable")
        except (MultiAgentProtocolError, ValidationError):
            return _problem(
                502,
                "multi_agent_protocol_error",
                "The workflow service returned an invalid response",
            )
        except LookupError:
            return _problem(404, "run_not_found", "The action plan does not exist")
        except ValueError:
            return _problem(
                422,
                "invalid_workflow_input",
                "A valid workflow invocation and evidence section are required",
            )

    @app.get(f"{collection}/capabilities")
    @guarded
    def case_review_capabilities(case_id: UUID) -> Response:
        # A configured token does not mean the host service is running (notably in CI).
        # Probe the approved template without starting a run or exposing upstream errors.
        try:
            upstream = multi_agent.request("GET", f"/templates/{TEMPLATE}")
            if upstream.status_code != 200:
                return jsonify({"enabled": False})
            _template(upstream)
        except (MultiAgentUnavailableError, MultiAgentProtocolError, ValidationError):
            return jsonify({"enabled": False})
        return jsonify({"enabled": True})

    @app.get(f"{collection}/template")
    @guarded
    def case_review_template(case_id: UUID) -> Any:
        upstream = multi_agent.request("GET", f"/templates/{TEMPLATE}")
        if error := _error(upstream):
            return error
        descriptor = _template(upstream)
        # Host filesystem paths are not useful to the browser.
        return jsonify(descriptor.model_dump(mode="json", exclude={"source"}))

    @app.post(collection)
    @guarded
    def case_review_start(case_id: UUID) -> Any:
        body = _body({"input", "requested_by"})
        values = body.get("input")
        if not isinstance(values, dict) or set(values) - {"buyer_case_id", "reviewer_note"}:
            raise ValueError("Provide the selected case and optional reviewer context")
        if values.get("buyer_case_id") != str(case_id):
            raise ValueError("The action plan must use the selected buyer case")
        note = values.get("reviewer_note", "")
        if not isinstance(note, str) or len(note) > 500:
            raise ValueError("Reviewer context must be at most 500 characters")
        payload: dict[str, Any] = {
            "template_id": TEMPLATE,
            "input": {"buyer_case_id": str(case_id), "reviewer_note": note.strip()},
        }
        if body.get("requested_by") is not None:
            payload["requested_by"] = _actor(body["requested_by"])
        upstream = multi_agent.create_run(payload)
        if error := _error(upstream):
            return error
        if upstream.status_code != 202:
            raise MultiAgentProtocolError
        run = _run(upstream, case_id)
        response = jsonify(run.model_dump(mode="json"))
        response.status_code = 202
        response.headers["Location"] = (
            f"/api/buyer-workspaces/v1/buyer-cases/{case_id}/evidence-reviews/{run.id}"
        )
        response.headers["X-Workflow-Run-ID"] = str(run.id)
        return response

    @app.get(collection)
    @guarded
    def case_review_list(case_id: UUID) -> Any:
        limit = min(max(int(request.args.get("limit", "20")), 1), 20)
        params: dict[str, str | int] = {
            "feature_id": FEATURE,
            "template_id": TEMPLATE,
            "limit": limit,
        }
        if state := request.args.get("state"):
            params["state"] = state
        upstream = multi_agent.request("GET", "/runs", params=params)
        if error := _error(upstream):
            return error
        page = WorkflowRunPage.model_validate(_json(upstream))
        if len(page.items) > limit:
            raise MultiAgentProtocolError
        items = []
        # Summaries carry no input/case identifier: inspect a bounded page before exposing rows.
        for item in page.items:
            if item.feature_id != FEATURE or item.template_id != TEMPLATE:
                continue
            detail = multi_agent.request("GET", f"/runs/{item.id}")
            if detail.status_code == 404:
                continue
            if error := _error(detail):
                return error
            try:
                _run(detail, case_id, item.id)
            except LookupError:
                continue
            items.append(item.model_dump(mode="json"))
        return jsonify({"items": items, "count": len(items)})

    @app.get(f"{collection}/<uuid:run_id>")
    @guarded
    def case_review_detail(case_id: UUID, run_id: UUID) -> Any:
        run = owned_run(case_id, run_id)
        return jsonify(run.model_dump(mode="json")) if isinstance(run, WorkflowRun) else run

    @app.post(f"{collection}/<uuid:run_id>/decision")
    @guarded
    def case_review_decide(case_id: UUID, run_id: UUID) -> Any:
        body = _body({"decision", "actor", "note", "accepted_step_ids"})
        body["actor"] = _actor(body.get("actor"))
        try:
            decision = HumanDecisionRequest.model_validate(body)
        except ValidationError as exc:
            raise ValueError("Check the decision, reviewer name, note and selected steps") from exc
        run = owned_run(case_id, run_id)
        if not isinstance(run, WorkflowRun):
            return run
        upstream = multi_agent.request(
            "POST", f"/runs/{run_id}/decision", body=decision.model_dump(mode="json")
        )
        if error := _error(upstream):
            return error
        return jsonify(_run(upstream, case_id, run_id).model_dump(mode="json"))

    @app.post(f"{collection}/<uuid:run_id>/cancel")
    @guarded
    def case_review_cancel(case_id: UUID, run_id: UUID) -> Any:
        body = _body({"actor"}) if request.data else {}
        if "actor" in body:
            body["actor"] = _actor(body["actor"])
        run = owned_run(case_id, run_id)
        if not isinstance(run, WorkflowRun):
            return run
        upstream = multi_agent.request("POST", f"/runs/{run_id}/cancel", body=body)
        if error := _error(upstream):
            return error
        return jsonify(_run(upstream, case_id, run_id).model_dump(mode="json"))

    @app.get(f"{collection}/<uuid:run_id>/history")
    @guarded
    def case_review_history(case_id: UUID, run_id: UUID) -> Any:
        run = owned_run(case_id, run_id)
        if not isinstance(run, WorkflowRun):
            return run
        cursors = {
            key: request.args[key]
            for key in ("after_history", "after_audit")
            if key in request.args
        }
        upstream = multi_agent.request("GET", f"/runs/{run_id}/history", params=cursors)
        if error := _error(upstream):
            return error
        value = WorkflowRunHistory.model_validate(_json(upstream))
        if (
            value.run_id != run_id
            or any(item.run_id != run_id for item in value.history)
            or any(item.run_id != run_id for item in value.audit)
        ):
            raise MultiAgentProtocolError
        return jsonify(value.model_dump(mode="json"))
