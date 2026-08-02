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
    PROBLEM_DETAIL_MEDIA_TYPE,
    REQUEST_ID_HEADER,
    TRACEPARENT_HEADER,
    TRACEPARENT_PATTERN_TEXT,
    AgentRun,
    AgentRunDetail,
    AgentRunEventPage,
    AgentRunRequest,
    FeatureManifest,
    HealthResponse,
    HumanReviewRequest,
    ModelRegistry,
    ProblemDetail,
    ToolDefinition,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = REPOSITORY_ROOT / "shared" / "contracts" / "schemas"
OPENAPI_ROOT = REPOSITORY_ROOT / "shared" / "contracts" / "openapi"

SCHEMA_MODELS: dict[str, type[BaseModel]] = {
    "agent-run-request.schema.json": AgentRunRequest,
    "agent-run.schema.json": AgentRun,
    "agent-run-detail.schema.json": AgentRunDetail,
    "agent-run-event-page.schema.json": AgentRunEventPage,
    "health-response.schema.json": HealthResponse,
    "human-review-request.schema.json": HumanReviewRequest,
    "problem-detail.schema.json": ProblemDetail,
    "tool-definition.schema.json": ToolDefinition,
    "feature-manifest.schema.json": FeatureManifest,
    "model-registry.schema.json": ModelRegistry,
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
                                    "schema": {"$ref": "#/components/schemas/HealthResponse"}
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
                                    "schema": {"$ref": "#/components/schemas/HealthResponse"}
                                }
                            },
                        },
                        "503": {
                            "description": "A required readiness dependency is unavailable",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/HealthResponse"}
                                }
                            },
                        },
                    },
                }
            },
            "/api/v1/agent-runs": {
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
                }
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


def expected_files() -> dict[Path, str]:
    """Return every generated path and its canonical content."""
    files = {
        SCHEMA_ROOT / filename: _json(model.model_json_schema())
        for filename, model in SCHEMA_MODELS.items()
    }
    files[OPENAPI_ROOT / "ai-mode.v1.openapi.json"] = _json(_openapi())
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
