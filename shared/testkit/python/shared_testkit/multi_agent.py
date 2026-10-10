"""In-memory fake of the Multi-Agent Server HTTP API for feature backend tests.

``FakeMultiAgentServer`` implements the same routes, authentication, Problem Details errors,
state rules and response contracts as ``ai-services/multi-agent-server`` without agents,
models, tools or persistence. A started run settles immediately at ``awaiting_human`` with a
plan, Worker output and Reviewer report built from the template, so a feature can exercise
its "start review", "show findings" and "record decision" paths deterministically.

Use it in three ways:

* ``httpx.Client(transport=fake.transport(), base_url="http://multi-agent")``;
* as a WSGI app, for example ``httpx.WSGITransport(app=fake)`` or Werkzeug's test client;
* ``with fake.serve() as base_url:`` for code that opens real sockets (``requests``,
  ``urllib``), on an ephemeral loopback port.

Feature code must not import ``multi_agent_server``; this fake and the generated contracts are
the supported test seam.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs
from uuid import UUID, uuid4
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from pydantic import ValidationError

from shared_contracts import (
    PROBLEM_DETAIL_MEDIA_TYPE,
    REQUEST_ID_HEADER,
    FieldIssue,
    HealthStatus,
    ProblemDetail,
    ReadinessCheckProjection,
    is_valid_request_id,
    project_readiness,
)
from shared_contracts.multi_agent import (
    MAX_HISTORY_CURSOR,
    MAX_RUN_PAGE_LIMIT,
    MAX_WORKFLOW_ROUNDS,
    MISSING_INPUT,
    MULTI_AGENT_API_PREFIX,
    MULTI_AGENT_SERVICE_NAME,
    TERMINAL_WORKFLOW_STATES,
    WORKFLOW_RUN_ID_HEADER,
    AgentRole,
    AuditEvent,
    CoordinationAuditEntry,
    EvidenceOutcome,
    EvidenceReference,
    FindingOutcome,
    FindingSeverity,
    HumanDecision,
    HumanDecisionKind,
    HumanDecisionRequest,
    JsonObject,
    ModelAttribution,
    PlanStep,
    ReviewFinding,
    ReviewReport,
    StageRecord,
    WorkerOutput,
    WorkerStepResult,
    WorkflowAction,
    WorkflowAttempt,
    WorkflowError,
    WorkflowHistoryEntry,
    WorkflowPlan,
    WorkflowRun,
    WorkflowRunHistory,
    WorkflowRunPage,
    WorkflowRunRequest,
    WorkflowRunSummary,
    WorkflowState,
    WorkflowTemplate,
    WorkflowTemplateDescriptor,
    WorkflowTemplateList,
    WorkflowToolDescriptor,
    resolve_placeholders,
)

if TYPE_CHECKING:
    import httpx

FAKE_MULTI_AGENT_TOKEN = "fake-multi-agent-token-0123456789abcdef"  # noqa: S105 - test-only fake token
FAKE_PROVIDER = "fake"
FAKE_MODEL = "fake-multi-agent-v1"
_ZERO_HASH = "0" * 64
_DECISION_STATES = {
    HumanDecisionKind.APPROVE: WorkflowState.APPROVED,
    HumanDecisionKind.PARTIAL: WorkflowState.PARTIALLY_ACCEPTED,
    HumanDecisionKind.REJECT: WorkflowState.REJECTED,
}
_TITLES = {
    400: "Invalid request",
    401: "Unauthorized",
    404: "Not found",
    405: "Method not allowed",
    409: "Conflict",
    422: "Invalid request",
}
StartResponse = Callable[[str, list[tuple[str, str]]], object]


class FakeProblem(Exception):  # noqa: N818 - mirrors the server's Problem Details error
    """An error response the fake returns as Problem Details."""

    def __init__(
        self, status: int, code: str, detail: str, errors: tuple[FieldIssue, ...] = ()
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail
        self.errors = errors


@dataclass(slots=True)
class FakeResponse:
    """A framework-neutral response: status, headers and JSON body."""

    status: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body)


@dataclass(slots=True)
class _Record:
    run: WorkflowRun
    history: list[WorkflowHistoryEntry] = field(default_factory=list)
    audit: list[CoordinationAuditEntry] = field(default_factory=list)
    failed_checks: tuple[str, ...] = ()
    recommendation: HumanDecisionKind | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def _attribution(role: AgentRole) -> ModelAttribution:
    return ModelAttribution(
        role=role,
        provider=FAKE_PROVIDER,
        model=FAKE_MODEL,
        prompt_id=role.value,
        prompt_version="v1",
        prompt_hash=_ZERO_HASH,
    )


def _actions(state: WorkflowState) -> tuple[WorkflowAction, ...]:
    if state is WorkflowState.AWAITING_HUMAN:
        return ("approve", "correct", "partial", "reject", "cancel")
    if state in TERMINAL_WORKFLOW_STATES:
        return ()
    return ("cancel",)


def _input_issues(template: WorkflowTemplate, values: JsonObject) -> tuple[FieldIssue, ...]:
    """A small subset of the server's JSON Schema validation: closed, required, typed, enum."""
    fields = {item.name: item for item in template.inputs}
    issues = [
        FieldIssue(field="input", message=f"unexpected input {name}", code="additionalProperties")
        for name in sorted(set(values) - set(fields))
    ]
    types: dict[str, tuple[type, ...]] = {
        "string": (str,),
        "integer": (int,),
        "number": (int, float),
        "boolean": (bool,),
    }
    for name, spec in fields.items():
        if name not in values:
            if spec.required:
                issues.append(FieldIssue(field=name, message="is required", code="required"))
            continue
        value = values[name]
        wrong_bool = isinstance(value, bool) and spec.type != "boolean"
        if wrong_bool or not isinstance(value, types[spec.type]):
            issues.append(FieldIssue(field=name, message=f"must be {spec.type}", code="type"))
        elif spec.enum is not None and value not in spec.enum:
            issues.append(FieldIssue(field=name, message="is not an allowed value", code="enum"))
        elif spec.format == "uuid":
            try:
                UUID(str(value))
            except ValueError:
                issues.append(FieldIssue(field=name, message="must be a UUID", code="format"))
    return tuple(issues)


class FakeMultiAgentServer:
    """Deterministic, in-memory stand-in for the Multi-Agent Server API.

    ``recommendation`` and ``failed_checks`` shape every Reviewer report (override per run with
    :meth:`settle`). ``tool_results`` maps tool names to the excerpt recorded as evidence.
    With ``auto_settle=False`` new runs stay in ``planning`` until a test calls :meth:`settle`
    or :meth:`fail`, which exercises a feature's polling path.
    """

    def __init__(
        self,
        templates: Iterable[WorkflowTemplate] = (),
        *,
        token: str = FAKE_MULTI_AGENT_TOKEN,
        recommendation: HumanDecisionKind = HumanDecisionKind.APPROVE,
        failed_checks: Iterable[str] = (),
        tool_results: Mapping[str, JsonObject] | None = None,
        auto_settle: bool = True,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self.token = token
        self.recommendation = recommendation
        self.failed_checks = tuple(failed_checks)
        self.tool_results = dict(tool_results or {})
        self.auto_settle = auto_settle
        self._clock = clock
        self._templates: dict[str, WorkflowTemplate] = {}
        self._runs: dict[UUID, _Record] = {}
        self._lock = threading.RLock()
        self.requests: list[tuple[str, str, Any]] = []
        for template in templates:
            self.add_template(template)

    # ------------------------------------------------------------ test controls

    def add_template(self, template: WorkflowTemplate) -> None:
        """Register (or replace) a template the fake will accept."""
        self._templates[template.id] = template

    def run(self, run_id: UUID | str) -> WorkflowRun:
        """The current snapshot of a run (raises ``KeyError`` when unknown)."""
        return self._runs[UUID(str(run_id))].run

    def runs(self) -> tuple[WorkflowRun, ...]:
        """Every run, oldest first."""
        return tuple(record.run for record in self._runs.values())

    def settle(
        self,
        run_id: UUID | str,
        *,
        recommendation: HumanDecisionKind | None = None,
        failed_checks: Iterable[str] | None = None,
    ) -> WorkflowRun:
        """Complete the Planner, Worker and Reviewer stages: ``planning``/``working`` to
        ``awaiting_human``."""
        with self._lock:
            record = self._runs[UUID(str(run_id))]
            if record.run.state not in {WorkflowState.PLANNING, WorkflowState.WORKING}:
                raise ValueError(f"cannot settle a run in {record.run.state.value}")
            if recommendation is not None:
                record.recommendation = recommendation
            if failed_checks is not None:
                record.failed_checks = tuple(failed_checks)
            self._settle(record)
            return record.run

    def fail(
        self, run_id: UUID | str, *, code: str = "tool_failed", message: str = "Fake failure"
    ) -> WorkflowRun:
        """Move an unfinished run to ``failed`` with a structured error."""
        with self._lock:
            record = self._runs[UUID(str(run_id))]
            if record.run.state in TERMINAL_WORKFLOW_STATES:
                raise ValueError("run is already finished")
            now = self._clock()
            previous = record.run.state
            record.run = record.run.evolve(
                state=WorkflowState.FAILED,
                updated_at=now,
                completed_at=now,
                error=WorkflowError(code=code, message=message, stage=AgentRole.WORKER),
                available_actions=(),
            )
            self._history(
                record, previous, WorkflowState.FAILED, "system", AgentRole.SYSTEM, message
            )
            self._audit(record, AuditEvent.RUN_FAILED, AgentRole.SYSTEM, "system", {"code": code})
            return record.run

    # ------------------------------------------------------------ transports

    def transport(self) -> httpx.MockTransport:
        """An ``httpx`` transport that answers from this fake."""
        import httpx

        def handler(request: httpx.Request) -> httpx.Response:
            response = self.handle(
                request.method,
                request.url.path,
                query=request.url.query.decode(),
                headers=dict(request.headers),
                body=request.content,
            )
            return httpx.Response(response.status, headers=response.headers, content=response.body)

        return httpx.MockTransport(handler)

    def __call__(self, environ: Mapping[str, Any], start_response: StartResponse) -> list[bytes]:
        """WSGI entry point."""
        length = int(environ.get("CONTENT_LENGTH") or 0)
        body = environ["wsgi.input"].read(length) if length else b""
        headers = {
            key[5:].replace("_", "-").lower(): str(value)
            for key, value in environ.items()
            if key.startswith("HTTP_")
        }
        if environ.get("CONTENT_TYPE"):
            headers["content-type"] = str(environ["CONTENT_TYPE"])
        response = self.handle(
            str(environ["REQUEST_METHOD"]),
            str(environ.get("PATH_INFO", "/")),
            query=str(environ.get("QUERY_STRING", "")),
            headers=headers,
            body=body,
        )
        reason = {200: "OK", 202: "Accepted"}.get(response.status, "Error")
        start_response(f"{response.status} {reason}", list(response.headers.items()))
        return [response.body]

    @contextmanager
    def serve(self, host: str = "127.0.0.1") -> Iterator[str]:
        """Serve the fake on an ephemeral loopback port; yields the base URL."""

        class _Quiet(WSGIRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                return None

        server: WSGIServer = make_server(host, 0, self, handler_class=_Quiet)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://{host}:{server.server_port}"
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    # ------------------------------------------------------------ request handling

    def handle(
        self,
        method: str,
        path: str,
        *,
        query: str = "",
        headers: Mapping[str, str] | None = None,
        body: bytes = b"",
    ) -> FakeResponse:
        """Dispatch one request; every error is Problem Details like the real server."""
        lowered = {key.lower(): value for key, value in (headers or {}).items()}
        supplied = lowered.get(REQUEST_ID_HEADER.lower(), "").strip()
        request_id = supplied if is_valid_request_id(supplied) else str(uuid4())
        try:
            payload = self._parse(lowered, body)
            self.requests.append((method, path, payload))
            if path in {"/health", "/health/live"} and method == "GET":
                return self._health(request_id)
            if lowered.get("authorization") != f"Bearer {self.token}":
                raise FakeProblem(401, "unauthorized", "Valid service authentication is required")
            with self._lock:
                status, data, extra = self._route(method, path, query, payload, request_id)
        except FakeProblem as problem:
            return self._problem(problem, path, request_id)
        except ValidationError as error:
            issues = tuple(
                FieldIssue(
                    field=".".join(str(part) for part in issue["loc"]) or "body",
                    message=issue["msg"][:500],
                    code=issue["type"][:100],
                )
                for issue in error.errors(include_url=False)[:20]
            )
            invalid = FakeProblem(
                422, "invalid_request_body", "Request violates the contract", issues
            )
            return self._problem(invalid, path, request_id)
        headers_out = {
            "Content-Type": "application/json",
            REQUEST_ID_HEADER: request_id,
            "Cache-Control": "no-store",
            **extra,
        }
        return FakeResponse(status, headers_out, json.dumps(data).encode())

    @staticmethod
    def _parse(headers: Mapping[str, str], body: bytes) -> Any:
        if not body:
            return None
        if not headers.get("content-type", "").startswith("application/json"):
            return _NotJson()
        try:
            return json.loads(body)
        except ValueError:
            return _NotJson()

    def _route(
        self, method: str, path: str, query: str, payload: Any, request_id: str
    ) -> tuple[int, Any, dict[str, str]]:
        if path == "/health/ready" and method == "GET":
            return 200, self._readiness(), {}
        if not path.startswith(MULTI_AGENT_API_PREFIX):
            raise FakeProblem(404, "not_found", "The requested URL was not found")
        parts = [part for part in path[len(MULTI_AGENT_API_PREFIX) :].split("/") if part]
        routes: dict[tuple[str, int], Callable[[], tuple[int, Any, dict[str, str]]]] = {
            ("templates", 1): lambda: self._only(method, "GET", lambda: self._templates_list()),
            ("templates", 2): lambda: self._only(method, "GET", lambda: self._template(parts[1])),
            ("runs", 1): lambda: (
                self._create(payload, request_id)
                if method == "POST"
                else self._only(method, "GET", lambda: self._list(query))
            ),
            ("runs", 2): lambda: self._only(method, "GET", lambda: self._get(parts[1])),
        }
        if len(parts) == 3 and parts[0] == "runs":
            action = parts[2]
            if action == "history":
                return self._only(method, "GET", lambda: self._history_body(parts[1], query))
            if action == "decision":
                return self._only(
                    method, "POST", lambda: self._decide(parts[1], payload, request_id)
                )
            if action == "cancel":
                return self._only(
                    method, "POST", lambda: self._cancel(parts[1], payload, request_id)
                )
        route = routes.get((parts[0] if parts else "", len(parts)))
        if route is None:
            raise FakeProblem(404, "not_found", "The requested URL was not found")
        return route()

    @staticmethod
    def _only(
        method: str, allowed: str, handler: Callable[[], Any]
    ) -> tuple[int, Any, dict[str, str]]:
        if method != allowed:
            raise FakeProblem(405, "method_not_allowed", "The method is not allowed for the URL")
        result = handler()
        return result if isinstance(result, tuple) else (200, result, {})

    # ------------------------------------------------------------ endpoints

    def _descriptor(self, template: WorkflowTemplate) -> WorkflowTemplateDescriptor:
        return WorkflowTemplateDescriptor(
            template=template,
            input_schema=template.input_schema(),
            tools=tuple(
                WorkflowToolDescriptor(name=name, side_effect="read_only", available=True)
                for name in template.allowed_tools
            ),
            source="fake",
        )

    def _templates_list(self) -> Any:
        items = tuple(self._descriptor(item) for item in self._templates.values())
        return WorkflowTemplateList(items=items, count=len(items)).model_dump(mode="json")

    def _template(self, template_id: str) -> Any:
        return self._descriptor(self._template_or_404(template_id)).model_dump(mode="json")

    def _template_or_404(self, template_id: str) -> WorkflowTemplate:
        try:
            return self._templates[template_id]
        except KeyError as exc:
            raise FakeProblem(
                404, "template_not_found", f"Workflow template {template_id} is not registered"
            ) from exc

    def _record(self, run_id: str) -> _Record:
        try:
            return self._runs[UUID(run_id)]
        except (ValueError, KeyError) as exc:
            raise FakeProblem(
                404, "run_not_found", f"Workflow run {run_id[:64]} does not exist"
            ) from exc

    @staticmethod
    def _object(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise FakeProblem(400, "invalid_request", "Request body must be a JSON object")
        return payload

    def _create(self, payload: Any, request_id: str) -> tuple[int, Any, dict[str, str]]:
        request = WorkflowRunRequest.model_validate(self._object(payload))
        template = self._template_or_404(request.template_id)
        issues = _input_issues(template, request.input)
        if issues:
            raise FakeProblem(
                422,
                "invalid_workflow_input",
                "Workflow input does not satisfy the template's input schema",
                issues,
            )
        now = self._clock()
        actor = request.requested_by or "anonymous"
        run = WorkflowRun(
            id=uuid4(),
            template_id=template.id,
            template_version=template.version,
            feature_id=template.feature_id,
            state=WorkflowState.PLANNING,
            round=1,
            input=request.input,
            requested_by=actor,
            request_id=request_id,
            provider_mode="deterministic",
            created_at=now,
            updated_at=now,
            stages=(
                StageRecord(stage=AgentRole.PLANNER, round=1, status="running", started_at=now),
            ),
            available_actions=("cancel",),
        )
        record = _Record(run, failed_checks=self.failed_checks, recommendation=self.recommendation)
        self._runs[run.id] = record
        self._history(record, None, WorkflowState.PLANNING, actor, AgentRole.SYSTEM, "Run created")
        self._audit(
            record, AuditEvent.RUN_CREATED, AgentRole.SYSTEM, actor, {"template_id": template.id}
        )
        if self.auto_settle:
            self._settle(record)
        location = f"{MULTI_AGENT_API_PREFIX}/runs/{run.id}"
        return (
            202,
            record.run.model_dump(mode="json"),
            {"Location": location, WORKFLOW_RUN_ID_HEADER: str(run.id)},
        )

    def _list(self, query: str) -> Any:
        values = {key: items[-1] for key, items in parse_qs(query).items()}
        raw_limit = values.get("limit", "20")
        if not raw_limit.isdecimal() or not 1 <= int(raw_limit) <= MAX_RUN_PAGE_LIMIT:
            raise FakeProblem(
                400, "invalid_request", f"limit must be an integer from 1 to {MAX_RUN_PAGE_LIMIT}"
            )
        state = values.get("state")
        if state is not None and state not in {item.value for item in WorkflowState}:
            raise FakeProblem(400, "invalid_request", "state is not a workflow state")
        runs = [
            record.run
            for record in reversed(self._runs.values())
            if values.get("template_id") in {None, record.run.template_id}
            and values.get("feature_id") in {None, record.run.feature_id}
            and state in {None, record.run.state.value}
        ][: int(raw_limit)]
        items = tuple(_summary(run) for run in runs)
        return WorkflowRunPage(items=items, count=len(items)).model_dump(mode="json")

    def _run_response(self, run: WorkflowRun) -> tuple[int, Any, dict[str, str]]:
        return 200, run.model_dump(mode="json"), {WORKFLOW_RUN_ID_HEADER: str(run.id)}

    def _get(self, run_id: str) -> tuple[int, Any, dict[str, str]]:
        return self._run_response(self._record(run_id).run)

    def _history_body(self, run_id: str, query: str = "") -> Any:
        # Same order as the server: run ID shape, then cursors, then the lookup.
        try:
            UUID(run_id)
        except ValueError:
            self._record(run_id)
        values = {key: items[-1] for key, items in parse_qs(query).items()}
        cursors = {}
        for name in ("after_history", "after_audit"):
            raw = values.get(name, "0")
            if not raw.isdecimal() or int(raw) > MAX_HISTORY_CURSOR:
                raise FakeProblem(
                    400,
                    "invalid_request",
                    f"{name} must be an integer from 0 to {MAX_HISTORY_CURSOR}",
                )
            cursors[name] = int(raw)
        record = self._record(run_id)
        return WorkflowRunHistory(
            run_id=record.run.id,
            state=record.run.state,
            history=tuple(e for e in record.history if e.sequence > cursors["after_history"]),
            audit=tuple(e for e in record.audit if e.sequence > cursors["after_audit"]),
        ).model_dump(mode="json")

    def _decide(
        self, run_id: str, payload: Any, request_id: str
    ) -> tuple[int, Any, dict[str, str]]:
        record = self._record(run_id)
        decision = HumanDecisionRequest.model_validate(self._object(payload))
        run = record.run
        if run.state is not WorkflowState.AWAITING_HUMAN:
            raise FakeProblem(
                409,
                "invalid_state_transition",
                f"Cannot record a decision for a run in {run.state.value}",
            )
        assert run.plan is not None and run.worker_output is not None and run.review is not None
        known = {step.id for step in run.plan.steps}
        unknown = [step for step in decision.accepted_step_ids if step not in known]
        if unknown:
            raise FakeProblem(
                422, "invalid_decision", f"Unknown accepted step(s): {', '.join(unknown)}"
            )
        now = self._clock()
        rework = decision.decision is HumanDecisionKind.CORRECT and run.round < MAX_WORKFLOW_ROUNDS
        if decision.decision is HumanDecisionKind.CORRECT:
            target = WorkflowState.WORKING if rework else WorkflowState.CORRECTED
        else:
            target = _DECISION_STATES[decision.decision]
        recorded = HumanDecision(
            **decision.model_dump(),
            round=run.round,
            decided_at=now,
            resulting_state=target,
            request_id=request_id,
        )
        terminal = target in TERMINAL_WORKFLOW_STATES
        changes: dict[str, Any] = {
            "state": target,
            "updated_at": now,
            "completed_at": now if terminal else None,
            "decisions": (*run.decisions, recorded),
            "available_actions": _actions(target),
        }
        if rework:
            changes.update(
                round=run.round + 1,
                superseded=(
                    *run.superseded,
                    WorkflowAttempt(
                        round=run.round, worker_output=run.worker_output, review=run.review
                    ),
                ),
                worker_output=None,
                review=None,
            )
        record.run = run.evolve(**changes)
        self._history(
            record,
            WorkflowState.AWAITING_HUMAN,
            target,
            decision.actor,
            AgentRole.HUMAN,
            f"Human decision: {decision.decision.value}",
        )
        self._audit(
            record,
            AuditEvent.DECISION_RECORDED,
            AgentRole.HUMAN,
            decision.actor,
            {"decision": decision.decision.value, "resulting_state": target.value},
        )
        if rework and self.auto_settle:
            self._settle(record)
        return self._run_response(record.run)

    def _cancel(
        self, run_id: str, payload: Any, request_id: str
    ) -> tuple[int, Any, dict[str, str]]:
        record = self._record(run_id)
        actor = payload.get("actor") if isinstance(payload, dict) else None
        if actor is not None and (not isinstance(actor, str) or not 0 < len(actor) <= 100):
            raise FakeProblem(400, "invalid_request", "actor must be a short string")
        run = record.run
        if run.state in TERMINAL_WORKFLOW_STATES:
            raise FakeProblem(
                409, "invalid_state_transition", f"Cannot cancel a run in {run.state.value}"
            )
        now = self._clock()
        record.run = run.evolve(
            state=WorkflowState.CANCELLED, updated_at=now, completed_at=now, available_actions=()
        )
        who = actor or "api-client"
        self._history(record, run.state, WorkflowState.CANCELLED, who, AgentRole.HUMAN, "Cancelled")
        self._audit(record, AuditEvent.RUN_CANCELLED, AgentRole.HUMAN, who, {})
        return self._run_response(record.run)

    def _readiness(self) -> Any:
        return project_readiness(
            service=MULTI_AGENT_SERVICE_NAME,
            version="fake",
            checks={
                "state_store": ReadinessCheckProjection(
                    required=True, status=HealthStatus.HEALTHY, detail="in-memory fake"
                ),
                "templates": ReadinessCheckProjection(
                    required=False,
                    status=HealthStatus.HEALTHY if self._templates else HealthStatus.DEGRADED,
                    detail=f"{len(self._templates)} template(s) registered",
                ),
            },
        ).model_dump(mode="json")

    def _health(self, request_id: str) -> FakeResponse:
        projection = project_readiness(
            service=MULTI_AGENT_SERVICE_NAME,
            version="fake",
            checks={
                "process": ReadinessCheckProjection(
                    required=True, status=HealthStatus.HEALTHY, detail="fake"
                )
            },
        )
        return FakeResponse(
            200,
            {"Content-Type": "application/json", REQUEST_ID_HEADER: request_id},
            json.dumps(projection.model_dump(mode="json")).encode(),
        )

    @staticmethod
    def _problem(problem: FakeProblem, path: str, request_id: str) -> FakeResponse:
        body = ProblemDetail(
            type=f"urn:propertyscope:multi-agent:{problem.code}",
            title=_TITLES.get(problem.status, "Request failed"),
            status=problem.status,
            detail=problem.detail,
            code=problem.code,
            instance=path,
            request_id=request_id,
            errors=problem.errors,
        )
        return FakeResponse(
            problem.status,
            {
                "Content-Type": PROBLEM_DETAIL_MEDIA_TYPE,
                REQUEST_ID_HEADER: request_id,
                "Cache-Control": "no-store",
            },
            json.dumps(body.model_dump(mode="json")).encode(),
        )

    # ------------------------------------------------------------ run building

    def _settle(self, record: _Record) -> None:
        run = record.run
        template = self._templates[run.template_id]
        now = self._clock()
        round_number = run.round
        plan = run.plan or _plan(template, run.input)
        correction = run.decisions[-1].note if run.decisions else None
        evidence = tuple(self._evidence(step, round_number) for step in plan.steps)
        worker = WorkerOutput(
            round=round_number,
            summary=f"Fake Worker ran {len(plan.steps)} step(s).",
            steps=tuple(
                WorkerStepResult(
                    step_id=step.id,
                    status="completed",
                    findings=(f"Fake result for {step.tool}.",),
                    evidence_ids=(item.id,),
                )
                for step, item in zip(plan.steps, evidence, strict=True)
            ),
            evidence=evidence,
            correction_note=correction,
            produced_by=_attribution(AgentRole.WORKER),
        )
        review = self._review(template, plan, record, round_number)
        previous = run.state
        stages = (
            *(stage for stage in run.stages if stage.status != "running"),
            *(
                StageRecord(
                    stage=role,
                    round=round_number,
                    status="completed",
                    started_at=now,
                    completed_at=now,
                )
                for role in (
                    (AgentRole.WORKER, AgentRole.REVIEWER)
                    if previous is WorkflowState.WORKING
                    else (AgentRole.PLANNER, AgentRole.WORKER, AgentRole.REVIEWER)
                )
            ),
        )
        record.run = run.evolve(
            state=WorkflowState.AWAITING_HUMAN,
            updated_at=now,
            plan=plan,
            worker_output=worker,
            review=review,
            stages=stages[-20:],
            available_actions=_actions(WorkflowState.AWAITING_HUMAN),
        )
        if previous is WorkflowState.PLANNING:
            self._history(
                record,
                previous,
                WorkflowState.WORKING,
                "planner",
                AgentRole.PLANNER,
                "Plan created",
            )
            self._audit(
                record,
                AuditEvent.PLAN_CREATED,
                AgentRole.PLANNER,
                "planner",
                {"steps": len(plan.steps)},
            )
        self._history(
            record,
            WorkflowState.WORKING,
            WorkflowState.REVIEWING,
            "worker",
            AgentRole.WORKER,
            "Evidence gathered",
        )
        self._audit(
            record,
            AuditEvent.WORKER_COMPLETED,
            AgentRole.WORKER,
            "worker",
            {"evidence": len(evidence)},
        )
        self._history(
            record,
            WorkflowState.REVIEWING,
            WorkflowState.AWAITING_HUMAN,
            "reviewer",
            AgentRole.REVIEWER,
            "Review ready for a human decision",
        )
        self._audit(
            record,
            AuditEvent.REVIEW_COMPLETED,
            AgentRole.REVIEWER,
            "reviewer",
            {"recommendation": review.recommendation.value},
        )

    def _evidence(self, step: PlanStep, round_number: int) -> EvidenceReference:
        excerpt = self.tool_results.get(step.tool, {})
        digest = hashlib.sha256(
            json.dumps(excerpt, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return EvidenceReference(
            id=f"ev-{step.id}-r{round_number}",
            step_id=step.id,
            tool_name=step.tool,
            tool_version="v1",
            arguments=step.arguments,
            outcome=EvidenceOutcome.SUCCEEDED,
            transport="fake",
            result_digest=digest,
            duration_ms=0,
            excerpt=excerpt,
            tool_call_id=uuid4(),
        )

    @staticmethod
    def _review(
        template: WorkflowTemplate, plan: WorkflowPlan, record: _Record, round_number: int
    ) -> ReviewReport:
        failed = set(record.failed_checks)
        findings = tuple(
            ReviewFinding(
                id=f"f-{check.id}",
                check_id=check.id,
                severity=check.severity if check.id in failed else FindingSeverity.INFO,
                outcome=FindingOutcome.FAIL if check.id in failed else FindingOutcome.PASS,
                message=check.description,
                recommendation=check.recommendation if check.id in failed else None,
                step_ids=tuple(step.id for step in plan.steps if step.id == check.rule.step),
            )
            for check in template.reviewer_checks
        )
        recommendation = record.recommendation or HumanDecisionKind.APPROVE
        return ReviewReport(
            round=round_number,
            summary=f"Fake review: {len(failed)} failed check(s); {recommendation.value}.",
            recommendation=recommendation,
            findings=findings,
            produced_by=_attribution(AgentRole.REVIEWER),
        )

    def _history(
        self,
        record: _Record,
        source: WorkflowState | None,
        target: WorkflowState,
        actor: str,
        role: AgentRole,
        reason: str,
    ) -> None:
        record.history.append(
            WorkflowHistoryEntry(
                sequence=len(record.history) + 1,
                run_id=record.run.id,
                request_id=record.run.request_id,
                at=self._clock(),
                from_state=source,
                to_state=target,
                round=record.run.round,
                actor=actor,
                role=role,
                reason=reason,
            )
        )

    def _audit(
        self, record: _Record, event: AuditEvent, role: AgentRole, actor: str, detail: JsonObject
    ) -> None:
        record.audit.append(
            CoordinationAuditEntry(
                sequence=len(record.audit) + 1,
                run_id=record.run.id,
                request_id=record.run.request_id,
                at=self._clock(),
                event=event,
                role=role,
                actor=actor,
                round=record.run.round,
                detail=detail,
            )
        )


class _NotJson:
    """Marker for a body that is not a JSON document."""


def _plan(template: WorkflowTemplate, inputs: JsonObject) -> WorkflowPlan:
    steps = []
    for index, step in enumerate(template.steps, start=1):
        arguments = {}
        for key, value in step.arguments.items():
            resolved = resolve_placeholders(value, inputs)
            if resolved is not MISSING_INPUT:
                arguments[key] = resolved
        steps.append(
            PlanStep(
                id=step.id,
                index=index,
                title=step.title,
                purpose=step.purpose,
                tool=step.tool,
                arguments=arguments,
                required=step.required,
            )
        )
    return WorkflowPlan(
        summary=f"Fake plan for {template.title}.",
        steps=tuple(steps),
        evidence_needed=tuple(step.title for step in template.steps),
        produced_by=_attribution(AgentRole.PLANNER),
    )


def _summary(run: WorkflowRun) -> WorkflowRunSummary:
    return WorkflowRunSummary(
        id=run.id,
        template_id=run.template_id,
        template_version=run.template_version,
        feature_id=run.feature_id,
        state=run.state,
        round=run.round,
        requested_by=run.requested_by,
        provider_mode=run.provider_mode,
        created_at=run.created_at,
        updated_at=run.updated_at,
        completed_at=run.completed_at,
        recommendation=run.review.recommendation if run.review else None,
        failed_findings=run.review.failed_counts() if run.review else {},
        decision=run.decisions[-1].decision if run.decisions else None,
    )
