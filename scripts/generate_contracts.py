"""Generate or verify deterministic JSON Schema and OpenAPI contract artefacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from shared_contracts import (
    DEFAULT_EVENT_PAGE_SIZE,
    IDEMPOTENCY_KEY_HEADER,
    LAST_EVENT_ID_HEADER,
    MAX_EVENT_PAGE_SIZE,
    MAX_IDEMPOTENCY_KEY_LENGTH,
    MAX_REQUEST_ID_LENGTH,
    MAX_RUN_PAGE_SIZE,
    PROBLEM_DETAIL_MEDIA_TYPE,
    REQUEST_ID_HEADER,
    TRACEPARENT_HEADER,
    TRACEPARENT_PATTERN_TEXT,
    AgentRun,
    AgentRunDetail,
    AgentRunEventPage,
    AgentRunEvidenceDetail,
    AgentRunPage,
    AgentRunRequest,
    DeploymentProjectionV1,
    DeploymentSelectionV1,
    FeatureManifest,
    FeatureOnboarding,
    HealthResponse,
    HumanReviewRequest,
    ModelRegistry,
    ProblemDetail,
    ToolDefinition,
    TypedHealthProjection,
)
from shared_contracts.grounding import GroundedAnswer, GroundedClaim, GroundingRequest
from shared_contracts.multi_agent import (
    MAX_RUN_PAGE_LIMIT,
    MULTI_AGENT_API_PREFIX,
    WORKFLOW_RUN_ID_HEADER,
    CoordinationAuditEntry,
    HumanDecision,
    HumanDecisionRequest,
    PlanStep,
    ReviewFinding,
    WorkerOutput,
    WorkflowHistoryEntry,
    WorkflowRun,
    WorkflowRunHistory,
    WorkflowRunPage,
    WorkflowRunRequest,
    WorkflowState,
    WorkflowTemplate,
    WorkflowTemplateDescriptor,
    WorkflowTemplateList,
)
from shared_contracts.retrieval import (
    CorpusDocument,
    CorpusIngestRequest,
    CorpusVersion,
    EvidenceCitation,
    RetrievalRequest,
    RetrievalResponse,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = REPOSITORY_ROOT / "shared" / "contracts" / "schemas"
OPENAPI_ROOT = REPOSITORY_ROOT / "shared" / "contracts" / "openapi"

SCHEMA_MODELS: dict[str, type[BaseModel]] = {
    "grounding-request.v1.schema.json": GroundingRequest,
    "grounded-claim.v1.schema.json": GroundedClaim,
    "grounded-answer.v1.schema.json": GroundedAnswer,
    "corpus-document.v1.schema.json": CorpusDocument,
    "corpus-ingest-request.v1.schema.json": CorpusIngestRequest,
    "corpus-version.v1.schema.json": CorpusVersion,
    "evidence-citation.v1.schema.json": EvidenceCitation,
    "retrieval-request.v1.schema.json": RetrievalRequest,
    "retrieval-response.v1.schema.json": RetrievalResponse,
    "agent-run-request.schema.json": AgentRunRequest,
    "agent-run.schema.json": AgentRun,
    "agent-run-detail.schema.json": AgentRunDetail,
    "agent-run-evidence-detail.schema.json": AgentRunEvidenceDetail,
    "agent-run-event-page.schema.json": AgentRunEventPage,
    "agent-run-page.schema.json": AgentRunPage,
    "health-response.schema.json": HealthResponse,
    "human-review-request.schema.json": HumanReviewRequest,
    "problem-detail.schema.json": ProblemDetail,
    "tool-definition.schema.json": ToolDefinition,
    "feature-manifest.schema.json": FeatureManifest,
    "feature-onboarding.schema.json": FeatureOnboarding,
    "deployment-selection.v1.schema.json": DeploymentSelectionV1,
    "deployment-projection.v1.schema.json": DeploymentProjectionV1,
    "typed-health-projection.v1.schema.json": TypedHealthProjection,
    "model-registry.schema.json": ModelRegistry,
}
# Release 2 Multi-Agent Server (ADR-047). Kept out of the AI-mode OpenAPI document.
MULTI_AGENT_SCHEMA_MODELS: dict[str, type[BaseModel]] = {
    "workflow-template.v1.schema.json": WorkflowTemplate,
    "workflow-template-descriptor.v1.schema.json": WorkflowTemplateDescriptor,
    "workflow-template-list.v1.schema.json": WorkflowTemplateList,
    "workflow-run-request.v1.schema.json": WorkflowRunRequest,
    "workflow-run.v1.schema.json": WorkflowRun,
    "workflow-run-page.v1.schema.json": WorkflowRunPage,
    "workflow-run-history.v1.schema.json": WorkflowRunHistory,
    "workflow-plan-step.v1.schema.json": PlanStep,
    "workflow-worker-output.v1.schema.json": WorkerOutput,
    "workflow-review-finding.v1.schema.json": ReviewFinding,
    "workflow-human-decision-request.v1.schema.json": HumanDecisionRequest,
    "workflow-human-decision.v1.schema.json": HumanDecision,
    "workflow-history-entry.v1.schema.json": WorkflowHistoryEntry,
    "workflow-coordination-audit-entry.v1.schema.json": CoordinationAuditEntry,
}


def _json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _openapi() -> dict[str, Any]:
    schemas: dict[str, Any] = {}
    for model in SCHEMA_MODELS.values():
        schema = model.model_json_schema(ref_template="#/components/schemas/{model}")
        schemas.update(schema.pop("$defs", {}))
        schemas[model.__name__] = schema
    run_parameter = {
        "name": "run_id",
        "in": "path",
        "required": True,
        "schema": {"type": "string", "format": "uuid"},
    }
    problem_response = {
        "description": "Problem Details-compatible error",
        "content": {
            PROBLEM_DETAIL_MEDIA_TYPE: {"schema": {"$ref": "#/components/schemas/ProblemDetail"}}
        },
    }
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "ASD AI-mode API",
            "version": "0.1.0",
            "description": "Release 0 shared bounded agent-run orchestration API.",
        },
        "paths": {
            "/health/live": {
                "get": {
                    "operationId": "getLiveness",
                    "responses": {
                        "200": {
                            "description": "Process is live",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/TypedHealthProjection"}
                                }
                            },
                        }
                    },
                }
            },
            "/health/ready": {
                "get": {
                    "operationId": "getReadiness",
                    "responses": {
                        "200": {
                            "description": "Service is ready or AI provider is degraded",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/TypedHealthProjection"}
                                }
                            },
                        },
                        "503": {
                            "description": "A required readiness dependency is unavailable",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/TypedHealthProjection"}
                                }
                            },
                        },
                    },
                }
            },
            "/api/v1/agent-runs": {
                "get": {
                    "operationId": "listAgentRuns",
                    "parameters": [
                        {
                            "name": "status",
                            "in": "query",
                            "required": False,
                            "schema": {
                                "type": "array",
                                "items": {"$ref": "#/components/schemas/RunStatus"},
                            },
                        },
                        {
                            "name": "feature_key",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "string", "maxLength": 100},
                        },
                        {
                            "name": "model_profile",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "string", "maxLength": 100},
                        },
                        {
                            "name": "cursor",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "string", "maxLength": 512},
                        },
                        {
                            "name": "limit",
                            "in": "query",
                            "required": False,
                            "schema": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": MAX_RUN_PAGE_SIZE,
                                "default": 50,
                            },
                        },
                    ],
                    "responses": {
                        "200": {
                            "description": "Stable page of safe agent-run summaries",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/AgentRunPage"}
                                }
                            },
                        },
                        "400": problem_response,
                    },
                },
                "post": {
                    "operationId": "createAgentRun",
                    "parameters": [
                        {"$ref": "#/components/parameters/RequestId"},
                        {"$ref": "#/components/parameters/Traceparent"},
                        {"$ref": "#/components/parameters/IdempotencyKey"},
                    ],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/AgentRunRequest"}
                            }
                        },
                    },
                    "responses": {
                        "202": {
                            "description": "Run persisted and accepted",
                            "headers": {
                                "Location": {"schema": {"type": "string"}},
                                "X-Agent-Run-ID": {"schema": {"type": "string", "format": "uuid"}},
                            },
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/AgentRun"}
                                }
                            },
                        },
                        "400": problem_response,
                        "409": problem_response,
                        "413": problem_response,
                        "415": problem_response,
                        "422": problem_response,
                        "503": problem_response,
                    },
                },
            },
            "/api/v1/model-profiles": {
                "get": {
                    "operationId": "getModelProfiles",
                    "responses": {
                        "200": {
                            "description": "Supported models and bounded runtime profiles",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ModelRegistry"}
                                }
                            },
                        },
                        "503": problem_response,
                    },
                }
            },
            "/api/v1/agent-runs/{run_id}": {
                "get": {
                    "operationId": "getAgentRun",
                    "parameters": [run_parameter],
                    "responses": {
                        "200": {
                            "description": "Current run and safe ordered history",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/AgentRunDetail"}
                                }
                            },
                        },
                        "404": problem_response,
                    },
                }
            },
            "/api/v1/agent-runs/{run_id}/cancel": {
                "post": {
                    "operationId": "cancelAgentRun",
                    "parameters": [run_parameter],
                    "responses": {
                        "200": {
                            "description": "Cancellation intent recorded",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/AgentRun"}
                                }
                            },
                        },
                        "404": problem_response,
                    },
                }
            },
            "/api/v1/agent-runs/{run_id}/events": {
                "get": {
                    "operationId": "getAgentRunEvents",
                    "parameters": [
                        run_parameter,
                        {
                            "name": "after",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "integer", "minimum": 0, "default": 0},
                        },
                        {
                            "name": "limit",
                            "in": "query",
                            "required": False,
                            "schema": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": MAX_EVENT_PAGE_SIZE,
                                "default": DEFAULT_EVENT_PAGE_SIZE,
                            },
                        },
                        {
                            "name": LAST_EVENT_ID_HEADER,
                            "in": "header",
                            "required": False,
                            "schema": {"type": "integer", "minimum": 0},
                        },
                    ],
                    "responses": {
                        "200": {
                            "description": "Ordered safe progress events after the cursor",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/AgentRunEventPage"}
                                }
                            },
                        },
                        "400": problem_response,
                        "404": problem_response,
                    },
                }
            },
            "/api/v1/agent-runs/{run_id}/reviews": {
                "post": {
                    "operationId": "reviewAgentRun",
                    "parameters": [run_parameter],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/HumanReviewRequest"}
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Review atomically applied",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/AgentRunDetail"}
                                }
                            },
                        },
                        "404": problem_response,
                        "409": problem_response,
                        "422": problem_response,
                        "503": problem_response,
                    },
                }
            },
            "/api/v1/operations/agent-runs/{run_id}": {
                "get": {
                    "operationId": "getAgentRunEvidence",
                    "parameters": [run_parameter],
                    "responses": {
                        "200": {
                            "description": "Policy-projected run evidence",
                            "headers": {"ETag": {"schema": {"type": "string"}}},
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/AgentRunEvidenceDetail"
                                    }
                                }
                            },
                        },
                        "304": {"description": "Projected run version is unchanged"},
                        "404": problem_response,
                    },
                }
            },
        },
        "components": {
            "parameters": {
                "RequestId": {
                    "name": REQUEST_ID_HEADER,
                    "in": "header",
                    "required": False,
                    "schema": {"type": "string", "maxLength": MAX_REQUEST_ID_LENGTH},
                },
                "Traceparent": {
                    "name": TRACEPARENT_HEADER,
                    "in": "header",
                    "required": False,
                    "schema": {
                        "type": "string",
                        "pattern": TRACEPARENT_PATTERN_TEXT,
                    },
                },
                "IdempotencyKey": {
                    "name": IDEMPOTENCY_KEY_HEADER,
                    "in": "header",
                    "required": False,
                    "schema": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": MAX_IDEMPOTENCY_KEY_LENGTH,
                    },
                },
            },
            "schemas": schemas,
        },
    }


def _ref(model: str) -> dict[str, str]:
    return {"$ref": f"#/components/schemas/{model}"}


def _json_response(description: str, model: str, **extra: Any) -> dict[str, Any]:
    return {
        "description": description,
        **extra,
        "content": {"application/json": {"schema": _ref(model)}},
    }


def _multi_agent_openapi() -> dict[str, Any]:
    """OpenAPI 3.1 for the host Multi-Agent Server (``ai-services/multi-agent-server``)."""
    schemas: dict[str, Any] = {}
    for model in (*MULTI_AGENT_SCHEMA_MODELS.values(), ProblemDetail, TypedHealthProjection):
        schema = model.model_json_schema(ref_template="#/components/schemas/{model}")
        schemas.update(schema.pop("$defs", {}))
        schemas[model.__name__] = schema
    problem = {
        "description": "Problem Details error",
        "content": {PROBLEM_DETAIL_MEDIA_TYPE: {"schema": _ref("ProblemDetail")}},
    }
    run_id = {
        "name": "run_id",
        "in": "path",
        "required": True,
        "schema": {"type": "string", "format": "uuid"},
    }
    correlated = [{"$ref": "#/components/parameters/RequestId"}]
    run_headers = {"headers": {WORKFLOW_RUN_ID_HEADER: {"schema": {"type": "string"}}}}
    prefix = MULTI_AGENT_API_PREFIX
    health = _json_response("Process is live", "TypedHealthProjection")
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "PropertyScope Multi-Agent Server API",
            "version": "1.0.0",
            "description": (
                "Planner → Worker → Reviewer → Human Review workflows over feature-owned "
                "templates (ADR-047). Every route except /health and /health/live requires "
                "Authorization: Bearer <MULTI_AGENT_SERVICE_TOKEN>. Every response carries "
                "X-Request-ID; run responses also carry X-Workflow-Run-ID."
            ),
        },
        "security": [{"serviceToken": []}],
        "paths": {
            "/health": {
                "get": {"operationId": "getHealth", "security": [], "responses": {"200": health}}
            },
            "/health/live": {
                "get": {"operationId": "getLiveness", "security": [], "responses": {"200": health}}
            },
            "/health/ready": {
                "get": {
                    "operationId": "getReadiness",
                    "responses": {
                        "200": _json_response("Ready or degraded", "TypedHealthProjection"),
                        "401": problem,
                        "503": _json_response("State store unavailable", "TypedHealthProjection"),
                    },
                }
            },
            f"{prefix}/templates": {
                "get": {
                    "operationId": "listWorkflowTemplates",
                    "responses": {
                        "200": _json_response("Registered templates", "WorkflowTemplateList"),
                        "401": problem,
                    },
                }
            },
            f"{prefix}/templates/{{template_id}}": {
                "get": {
                    "operationId": "getWorkflowTemplate",
                    "parameters": [
                        {
                            "name": "template_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string", "maxLength": 100},
                        }
                    ],
                    "responses": {
                        "200": _json_response("One template", "WorkflowTemplateDescriptor"),
                        "401": problem,
                        "404": problem,
                    },
                }
            },
            f"{prefix}/runs": {
                "get": {
                    "operationId": "listWorkflowRuns",
                    "parameters": [
                        {"name": "template_id", "in": "query", "schema": {"type": "string"}},
                        {"name": "feature_id", "in": "query", "schema": {"type": "string"}},
                        {
                            "name": "state",
                            "in": "query",
                            "schema": {"enum": [state.value for state in WorkflowState]},
                        },
                        {
                            "name": "limit",
                            "in": "query",
                            "schema": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": MAX_RUN_PAGE_LIMIT,
                                "default": 20,
                            },
                        },
                    ],
                    "responses": {
                        "200": _json_response("Newest-first run summaries", "WorkflowRunPage"),
                        "400": problem,
                        "401": problem,
                    },
                },
                "post": {
                    "operationId": "startWorkflowRun",
                    "parameters": correlated,
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": _ref("WorkflowRunRequest")}},
                    },
                    "responses": {
                        "202": _json_response(
                            "Run persisted in planning; agents run in the background",
                            "WorkflowRun",
                            headers={
                                "Location": {"schema": {"type": "string"}},
                                WORKFLOW_RUN_ID_HEADER: {"schema": {"type": "string"}},
                            },
                        ),
                        "400": problem,
                        "401": problem,
                        "404": problem,
                        "413": problem,
                        "422": problem,
                        "503": problem,
                    },
                },
            },
            f"{prefix}/runs/{{run_id}}": {
                "get": {
                    "operationId": "getWorkflowRun",
                    "parameters": [run_id],
                    "responses": {
                        "200": _json_response("Complete run", "WorkflowRun", **run_headers),
                        "401": problem,
                        "404": problem,
                    },
                }
            },
            f"{prefix}/runs/{{run_id}}/decision": {
                "post": {
                    "operationId": "decideWorkflowRun",
                    "parameters": [run_id, *correlated],
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": _ref("HumanDecisionRequest")}},
                    },
                    "responses": {
                        "200": _json_response("Decision recorded", "WorkflowRun", **run_headers),
                        "401": problem,
                        "404": problem,
                        "409": problem,
                        "422": problem,
                        "503": problem,
                    },
                }
            },
            f"{prefix}/runs/{{run_id}}/cancel": {
                "post": {
                    "operationId": "cancelWorkflowRun",
                    "parameters": [run_id, *correlated],
                    "requestBody": {
                        "required": False,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {"actor": {"type": "string", "maxLength": 100}},
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": _json_response("Run cancelled", "WorkflowRun", **run_headers),
                        "401": problem,
                        "404": problem,
                        "409": problem,
                    },
                }
            },
            f"{prefix}/runs/{{run_id}}/history": {
                "get": {
                    "operationId": "getWorkflowRunHistory",
                    "parameters": [run_id],
                    "responses": {
                        "200": _json_response("Transitions and audit", "WorkflowRunHistory"),
                        "401": problem,
                        "404": problem,
                    },
                }
            },
        },
        "components": {
            "securitySchemes": {
                "serviceToken": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "MULTI_AGENT_SERVICE_TOKEN",
                }
            },
            "parameters": {
                "RequestId": {
                    "name": REQUEST_ID_HEADER,
                    "in": "header",
                    "required": False,
                    "schema": {"type": "string", "maxLength": MAX_REQUEST_ID_LENGTH},
                }
            },
            "schemas": schemas,
        },
    }


def expected_files() -> dict[Path, str]:
    """Return every generated path and its canonical content."""
    files = {
        SCHEMA_ROOT / filename: _json(model.model_json_schema())
        for filename, model in {**SCHEMA_MODELS, **MULTI_AGENT_SCHEMA_MODELS}.items()
    }
    files[OPENAPI_ROOT / "ai-mode.v1.openapi.json"] = _json(_openapi())
    files[OPENAPI_ROOT / "multi-agent.v1.openapi.json"] = _json(_multi_agent_openapi())
    return files


def main() -> int:
    """Write artefacts, or return nonzero when checked files have drifted."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="verify without writing")
    args = parser.parse_args()
    stale: list[Path] = []
    for path, content in expected_files().items():
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                stale.append(path.relative_to(REPOSITORY_ROOT))
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
    if stale:
        print("Generated contract artefacts are stale:")
        for path in stale:
            print(f"- {path}")
        print("Run: uv run python scripts/generate_contracts.py")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
