"""Flask application factory: the authenticated Multi-Agent Server HTTP API."""

from __future__ import annotations

import hmac
import logging
import sys
from importlib.metadata import PackageNotFoundError, version
from time import monotonic
from uuid import UUID, uuid4

from flask import Flask, Response, g, jsonify, request
from pydantic import BaseModel, ValidationError
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

from multi_agent_server.errors import InvalidRequestError, MultiAgentError, RunNotFoundError
from multi_agent_server.service import WorkflowService
from multi_agent_server.settings import MultiAgentSettings, build_service
from shared_contracts import (
    PROBLEM_DETAIL_MEDIA_TYPE,
    REQUEST_ID_HEADER,
    TRACEPARENT_HEADER,
    FieldIssue,
    HealthStatus,
    ProblemDetail,
    ReadinessCheckProjection,
    is_valid_request_id,
    is_valid_traceparent,
    project_readiness,
)
from shared_contracts.multi_agent import (
    MAX_RUN_PAGE_LIMIT,
    MULTI_AGENT_API_PREFIX,
    MULTI_AGENT_SERVICE_NAME,
    WORKFLOW_RUN_ID_HEADER,
    HumanDecisionRequest,
    WorkflowRun,
    WorkflowRunRequest,
    WorkflowState,
)

LOGGER = logging.getLogger("multi_agent_server")
PUBLIC_PATHS = frozenset({"/health", "/health/live"})
PROBLEM_TITLES = {
    400: "Invalid request",
    401: "Unauthorized",
    404: "Not found",
    405: "Method not allowed",
    409: "Conflict",
    413: "Request too large",
    415: "Unsupported media type",
    422: "Invalid request",
    500: "Internal server error",
    503: "Service unavailable",
}


def _package_version() -> str:
    try:
        return version("multi-agent-server")
    except PackageNotFoundError:
        return "0+unknown"


def configure_logging() -> None:
    """One-line JSON request logs on stdout, matching AI-mode's log schema."""
    from ai_mode.observability import JsonLogFormatter

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLogFormatter(service=MULTI_AGENT_SERVICE_NAME, environment="local"))
    LOGGER.handlers.clear()
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False


def problem(
    status: int, code: str, detail: str, *, errors: tuple[FieldIssue, ...] = ()
) -> tuple[Response, int]:
    """Build the Problem Details response used for every error."""
    body = ProblemDetail(
        type=f"urn:propertyscope:multi-agent:{code}",
        title=PROBLEM_TITLES.get(status, "Request failed"),
        status=status,
        detail=detail,
        code=code,
        instance=request.path,
        request_id=g.get("request_id"),
        errors=errors,
    )
    response = jsonify(body.model_dump(mode="json"))
    response.content_type = PROBLEM_DETAIL_MEDIA_TYPE
    return response, status


def _json(model: BaseModel, status: int = 200) -> tuple[Response, int]:
    return jsonify(model.model_dump(mode="json")), status


def _run_response(run: WorkflowRun, status: int = 200) -> tuple[Response, int]:
    response, code = _json(run, status)
    response.headers[WORKFLOW_RUN_ID_HEADER] = str(run.id)
    return response, code


def _body() -> dict[str, object]:
    if not request.is_json:
        raise InvalidRequestError("Request body must be application/json")
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise InvalidRequestError("Request body must be a JSON object")
    return payload


def _run_id(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise RunNotFoundError(f"Workflow run {value[:64]} does not exist") from exc


def create_app(
    settings: MultiAgentSettings | None = None,
    *,
    service: WorkflowService | None = None,
) -> Flask:
    """Create the API with replaceable settings and service (tests inject both)."""
    runtime = settings or MultiAgentSettings.from_environment()
    if runtime.token is None:
        raise ValueError("MULTI_AGENT_SERVICE_TOKEN is required to serve the HTTP API")
    token = runtime.token
    if service is None:
        configure_logging()
        service = build_service(runtime)
        recovered = service.recover_interrupted()
        if recovered:
            LOGGER.warning("Marked %d interrupted workflow run(s) as failed", recovered)
    workflows = service
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = runtime.max_request_bytes
    app.extensions["multi_agent_service"] = workflows
    service_version = _package_version()

    @app.before_request
    def correlate() -> tuple[Response, int] | None:
        g.started = monotonic()
        supplied = request.headers.get(REQUEST_ID_HEADER, "").strip()
        g.request_id = supplied if is_valid_request_id(supplied) else str(uuid4())
        traceparent = request.headers.get(TRACEPARENT_HEADER, "").strip().lower()
        if traceparent and not is_valid_traceparent(traceparent):
            return problem(400, "traceparent_invalid", "traceparent must use W3C version 00")
        return None

    @app.before_request
    def authenticate() -> tuple[Response, int] | None:
        if request.path in PUBLIC_PATHS:
            return None
        supplied = request.headers.get("Authorization", "")
        if not hmac.compare_digest(supplied.encode(), f"Bearer {token}".encode()):
            return problem(401, "unauthorized", "Valid service authentication is required")
        return None

    @app.after_request
    def finish(response: Response) -> Response:
        response.headers[REQUEST_ID_HEADER] = g.get("request_id", "")
        response.headers["Cache-Control"] = "no-store"
        LOGGER.info(
            "HTTP request completed",
            extra={
                "event": "http.request.completed",
                "request_id": g.get("request_id"),
                "run_id": response.headers.get(WORKFLOW_RUN_ID_HEADER),
                "status_code": response.status_code,
                "method": request.method,
                "path": request.url_rule.rule if request.url_rule is not None else request.path,
                "duration_ms": max(0, int((monotonic() - g.get("started", monotonic())) * 1000)),
                "outcome": "failure" if response.status_code >= 400 else "success",
            },
        )
        return response

    def _liveness() -> tuple[Response, int]:
        projection = project_readiness(
            service=MULTI_AGENT_SERVICE_NAME,
            version=service_version,
            checks={
                "process": ReadinessCheckProjection(
                    required=True,
                    status=HealthStatus.HEALTHY,
                    detail="Multi-Agent Server is accepting HTTP requests",
                )
            },
        )
        return jsonify(projection.model_dump(mode="json")), projection.http_status

    app.add_url_rule("/health", "health", _liveness, methods=["GET"])
    app.add_url_rule("/health/live", "health_live", _liveness, methods=["GET"])

    @app.get("/health/ready")
    def readiness() -> tuple[Response, int]:
        store_ready, store_detail = workflows.store.health()
        tools_ready, tools_detail = workflows.gateway.health()
        templates = workflows.registry.all()
        invalid = workflows.registry.invalid
        template_detail = f"{len(templates)} template(s) registered" + (
            f"; {len(invalid)} invalid manifest(s)" if invalid else ""
        )
        projection = project_readiness(
            service=MULTI_AGENT_SERVICE_NAME,
            version=service_version,
            checks={
                "state_store": ReadinessCheckProjection(
                    required=True,
                    status=HealthStatus.HEALTHY if store_ready else HealthStatus.UNHEALTHY,
                    detail=store_detail,
                ),
                "templates": ReadinessCheckProjection(
                    required=False,
                    status=(
                        HealthStatus.HEALTHY if templates and not invalid else HealthStatus.DEGRADED
                    ),
                    detail=template_detail,
                ),
                "tool_gateway": ReadinessCheckProjection(
                    required=False,
                    status=HealthStatus.HEALTHY if tools_ready else HealthStatus.DEGRADED,
                    detail=f"{workflows.gateway.transport}: {tools_detail}"[:500],
                ),
                "provider": ReadinessCheckProjection(
                    required=False,
                    status=HealthStatus.HEALTHY,
                    detail=f"{workflows.provider_mode} agents",
                ),
            },
        )
        return jsonify(projection.model_dump(mode="json")), projection.http_status

    @app.get(f"{MULTI_AGENT_API_PREFIX}/templates")
    def list_templates() -> tuple[Response, int]:
        return _json(workflows.describe_templates())

    @app.get(f"{MULTI_AGENT_API_PREFIX}/templates/<template_id>")
    def get_template(template_id: str) -> tuple[Response, int]:
        return _json(workflows.describe_template(template_id))

    @app.post(f"{MULTI_AGENT_API_PREFIX}/runs")
    def create_run() -> tuple[Response, int]:
        payload = WorkflowRunRequest.model_validate(_body())
        run = workflows.create_run(payload, request_id=g.request_id)
        response, status = _run_response(run, 202)
        response.headers["Location"] = f"{MULTI_AGENT_API_PREFIX}/runs/{run.id}"
        return response, status

    @app.get(f"{MULTI_AGENT_API_PREFIX}/runs")
    def list_runs() -> tuple[Response, int]:
        raw_limit = request.args.get("limit", "20")
        if not raw_limit.isdecimal() or not 1 <= int(raw_limit) <= MAX_RUN_PAGE_LIMIT:
            raise InvalidRequestError(f"limit must be an integer from 1 to {MAX_RUN_PAGE_LIMIT}")
        state = request.args.get("state") or None
        if state is not None and state not in {item.value for item in WorkflowState}:
            raise InvalidRequestError("state is not a workflow state")
        return _json(
            workflows.list_runs(
                template_id=request.args.get("template_id") or None,
                feature_id=request.args.get("feature_id") or None,
                state=state,
                limit=int(raw_limit),
            )
        )

    @app.get(f"{MULTI_AGENT_API_PREFIX}/runs/<run_id>")
    def get_run(run_id: str) -> tuple[Response, int]:
        return _run_response(workflows.get_run(_run_id(run_id)))

    @app.post(f"{MULTI_AGENT_API_PREFIX}/runs/<run_id>/decision")
    def decide(run_id: str) -> tuple[Response, int]:
        identifier = _run_id(run_id)
        payload = HumanDecisionRequest.model_validate(_body())
        return _run_response(workflows.decide(identifier, payload, request_id=g.request_id))

    @app.post(f"{MULTI_AGENT_API_PREFIX}/runs/<run_id>/cancel")
    def cancel(run_id: str) -> tuple[Response, int]:
        identifier = _run_id(run_id)
        payload = request.get_json(silent=True) if request.is_json else None
        actor = payload.get("actor") if isinstance(payload, dict) else None
        if actor is not None and (not isinstance(actor, str) or not 0 < len(actor) <= 100):
            raise InvalidRequestError("actor must be a short string")
        run = workflows.cancel(identifier, actor=actor or "api-client", request_id=g.request_id)
        return _run_response(run)

    @app.get(f"{MULTI_AGENT_API_PREFIX}/runs/<run_id>/history")
    def history(run_id: str) -> tuple[Response, int]:
        return _json(workflows.history(_run_id(run_id)))

    @app.errorhandler(MultiAgentError)
    def domain_error(error: MultiAgentError) -> tuple[Response, int]:
        return problem(error.status, error.code, error.detail, errors=error.errors)

    @app.errorhandler(ValidationError)
    def validation_error(error: ValidationError) -> tuple[Response, int]:
        issues = tuple(
            FieldIssue(
                field=".".join(str(part) for part in issue["loc"]) or "body",
                message=issue["msg"][:500],
                code=issue["type"][:100],
            )
            for issue in error.errors(include_url=False)[:20]
        )
        return problem(422, "invalid_request_body", "Request violates the contract", errors=issues)

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_: RequestEntityTooLarge) -> tuple[Response, int]:
        return problem(413, "request_too_large", "Request body exceeds the configured limit")

    @app.errorhandler(HTTPException)
    def http_error(error: HTTPException) -> tuple[Response, int]:
        status = error.code or 500
        return problem(
            status, (error.name or "error").lower().replace(" ", "_"), error.description or ""
        )

    @app.errorhandler(Exception)
    def unexpected(error: Exception) -> tuple[Response, int]:
        LOGGER.exception("Unhandled multi-agent request failure")
        return problem(500, "internal_error", "The request could not be completed")

    return app
