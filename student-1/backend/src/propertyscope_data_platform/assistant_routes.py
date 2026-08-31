"""Assistant, agent-run, and allowlisted tool routes for Feature 1."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from typing import Any, Protocol

import httpx
from flask import Blueprint, Response, jsonify, request
from pydantic import ValidationError
from werkzeug.datastructures import Headers

from propertyscope_data_platform.approval import approved_tool_call
from propertyscope_data_platform.assistant import (
    ASSISTANT_FEATURE_KEY,
    ASSISTANT_TOOL_ALLOWLIST,
    AssistantTurnRequest,
    build_assistant_objective,
    capability_guide,
)
from propertyscope_data_platform.clients import (
    AiModeClient,
    ConsumerImportClient,
    DataStoreClient,
)
from propertyscope_data_platform.http_support import (
    forward,
    json_body,
    problem,
    required_uuid,
    tool_envelope,
)
from propertyscope_data_platform.run_insight import build_run_inspection

ReleaseInspector = Callable[[DataStoreClient, uuid.UUID], Response]


class ReleasePublisher(Protocol):
    def __call__(
        self,
        store: DataStoreClient,
        consumers: ConsumerImportClient,
        release_id: uuid.UUID,
        body: Mapping[str, Any],
        idempotency_key: str,
        *,
        tool_output: bool = False,
    ) -> Response: ...


def register_assistant_tool_routes(
    api: Blueprint,
    store: DataStoreClient,
    ai_mode: AiModeClient,
    consumers: ConsumerImportClient,
    *,
    base: str,
    internal: str,
    inspect_release: ReleaseInspector,
    publish_release: ReleasePublisher,
) -> None:
    """Register assistant and tool routes on the service's single public Blueprint."""

    @api.post(f"{base}/dataset-releases/<uuid:release_id>/agent-runs")
    def release_agent_run(release_id: uuid.UUID) -> Response:
        release_response = store.request(
            "GET", f"{internal}/releases/{release_id}", headers=request.headers
        )
        if release_response.status_code >= 400:
            return forward(release_response)
        release_data = release_response.json()["release"]
        predecessor_id = "none"
        if release_data.get("dataset_id") and release_data.get("target_feature"):
            accepted_response = store.request(
                "GET",
                f"{internal}/releases",
                headers=request.headers,
                params={"status": "accepted", "limit": 100},
            )
            predecessor = next(
                (
                    item
                    for item in accepted_response.json().get("items", [])
                    if item["dataset_id"] == release_data["dataset_id"]
                    and item["target_feature"] == release_data["target_feature"]
                    and item["id"] != str(release_id)
                ),
                None,
            )
            if predecessor:
                predecessor_id = predecessor["id"]
        supplied_objective = str(json_body(optional=True).get("objective", "")).strip()
        objective = (
            f"release_id: {release_id}. "
            f"predecessor_release_id: {predecessor_id}. Use only these exact identifiers; "
            "never send placeholders to tools. "
        ) + (
            supplied_objective[:3500]
            if supplied_objective
            else "Compare its accepted predecessor, preserve accepted data, and propose "
            "only a reviewed safe recovery."
        )
        upstream = ai_mode.create_run(
            {
                "feature_key": "student-1-propertyscope-data-platform",
                "objective": objective,
                "trusted_identifiers": [
                    {"kind": "release_id", "value": str(release_id)},
                    *(
                        [{"kind": "release_id", "value": predecessor_id}]
                        if predecessor_id != "none"
                        else []
                    ),
                ],
                "prompt_set": "default.v7",
                "limits": {
                    "max_iterations": 6,
                    "max_tool_calls": 12,
                    "time_budget_ms": 300000,
                    "max_model_repairs": 2,
                },
            },
            request.headers,
        )
        return forward(upstream)

    @api.post(f"{base}/assistant/turns")
    def assistant_turn() -> Response:
        """Create one feature-scoped durable run for one conversational turn."""
        try:
            command = AssistantTurnRequest.model_validate(json_body())
        except ValidationError as exc:
            issue = exc.errors(include_url=False)[0]
            location = ".".join(str(item) for item in issue.get("loc", ())) or "request"
            return problem(422, "invalid_assistant_turn", f"{location}: {issue['msg']}")
        upstream = ai_mode.create_run(
            {
                "feature_key": ASSISTANT_FEATURE_KEY,
                "objective": build_assistant_objective(command),
                "trusted_identifiers": command.context.trusted_identifiers(),
                "prompt_set": "default.v7",
                "tool_allowlist": list(ASSISTANT_TOOL_ALLOWLIST),
                "limits": {
                    "max_iterations": 6,
                    "max_tool_calls": 10,
                    "time_budget_ms": 180000,
                    "max_model_repairs": 2,
                },
            },
            request.headers,
        )
        return forward(upstream)

    @api.get(f"{base}/assistant/turns/<uuid:run_id>")
    def assistant_turn_detail(run_id: uuid.UUID) -> Response:
        detail, owned = assistant_run(ai_mode, run_id, request.headers)
        if detail.status_code >= 400:
            return forward(detail)
        if not owned:
            return problem(404, "assistant_turn_not_found", "Assistant turn does not exist")
        return forward(detail)

    @api.get(f"{base}/assistant/turns/<uuid:run_id>/events")
    def assistant_turn_events(run_id: uuid.UUID) -> Response:
        detail, owned = assistant_run(ai_mode, run_id, request.headers)
        if detail.status_code >= 400:
            return forward(detail)
        if not owned:
            return problem(404, "assistant_turn_not_found", "Assistant turn does not exist")
        suffix = ""
        if request.query_string:
            suffix = "?" + request.query_string.decode("ascii", errors="ignore")
        return forward(ai_mode.get(f"/api/v1/agent-runs/{run_id}/events{suffix}", request.headers))

    @api.post(f"{base}/assistant/turns/<uuid:run_id>/cancel")
    def assistant_turn_cancel(run_id: uuid.UUID) -> Response:
        detail, owned = assistant_run(ai_mode, run_id, request.headers)
        if detail.status_code >= 400:
            return forward(detail)
        if not owned:
            return problem(404, "assistant_turn_not_found", "Assistant turn does not exist")
        return forward(ai_mode.cancel_run(str(run_id), request.headers))

    @api.get(f"{base}/agent-runs/<uuid:run_id>")
    def agent_run(run_id: uuid.UUID) -> Response:
        return forward(ai_mode.get(f"/api/v1/agent-runs/{run_id}", request.headers))

    @api.get(f"{base}/agent-runs")
    def agent_runs() -> Response:
        params: dict[str, str | list[str]] = {
            "feature_key": "student-1-propertyscope-data-platform"
        }
        for name in ("status", "model_profile", "cursor", "limit"):
            values = request.args.getlist(name)
            if values:
                params[name] = values if name == "status" else values[-1]
        return forward(ai_mode.get("/api/v1/agent-runs", request.headers, params=params))

    @api.get(f"{base}/agent-runs/<uuid:run_id>/events")
    def agent_events(run_id: uuid.UUID) -> Response:
        suffix = ""
        if request.query_string:
            suffix = "?" + request.query_string.decode("ascii", errors="ignore")
        return forward(ai_mode.get(f"/api/v1/agent-runs/{run_id}/events{suffix}", request.headers))

    # AI tools bind exactly to the checked catalogue paths and output schemas.
    @api.post(f"{base}/tools/sources.list.v1")
    def tool_sources() -> Response:
        body = json_body()
        params: dict[str, Any] = {"limit": min(int(body.get("limit", 25)), 50)}
        if body.get("status"):
            params["status"] = str(body["status"])
        return tool_envelope(
            store.request("GET", f"{internal}/sources", headers=request.headers, params=params)
        )

    @api.post(f"{base}/tools/releases.list.v1")
    def tool_releases() -> Response:
        body = json_body()
        params: dict[str, Any] = {"limit": min(int(body.get("limit", 25)), 50)}
        for name in ("status", "dataset_id", "target_feature"):
            if body.get(name):
                params[name] = str(body[name])
        upstream = store.request(
            "GET", f"{internal}/releases", headers=request.headers, params=params
        )
        if upstream.status_code >= 400:
            return forward(upstream)
        fields = (
            "id",
            "dataset_id",
            "source_definition_id",
            "ingestion_run_id",
            "target_feature",
            "release_version",
            "schema_version",
            "record_count",
            "status",
            "supersedes_release_id",
            "accepted_at",
            "created_at",
            "updated_at",
        )
        summaries = [
            {name: item.get(name) for name in fields if name in item}
            for item in upstream.json().get("items", [])[:50]
            if isinstance(item, dict)
        ]
        return jsonify({"items": summaries, "count": len(summaries)})

    @api.post(f"{base}/tools/platform.capabilities.v1")
    def tool_platform_capabilities() -> Response:
        body = json_body()
        if body:
            return problem(422, "invalid_tool_input", "Capability guide takes no input fields")
        return jsonify(capability_guide())

    @api.post(f"{base}/tools/runs.list.v1")
    def tool_runs() -> Response:
        body = json_body()
        params: dict[str, Any] = {
            "limit": min(int(body.get("limit", 10)), 25),
            "status": str(body.get("status", "succeeded")),
        }
        upstream = store.request("GET", f"{internal}/runs", headers=request.headers, params=params)
        if upstream.status_code >= 400:
            return forward(upstream)
        fields = (
            "id",
            "job_definition_id",
            "job_name",
            "source_definition_id",
            "source_name",
            "status",
            "run_mode",
            "requested_scope_json",
            "rows_discovered",
            "rows_staged",
            "rows_accepted",
            "rows_rejected",
            "requested_at",
            "started_at",
            "finished_at",
        )
        summaries = [
            {name: item.get(name) for name in fields if name in item}
            for item in upstream.json().get("items", [])[:25]
            if isinstance(item, dict)
        ]
        return jsonify({"items": summaries, "count": len(summaries)})

    @api.post(f"{base}/tools/runs.inspect.v1")
    def tool_run() -> Response:
        run_id = required_uuid(json_body(), "run_id")
        run_response = store.request("GET", f"{internal}/runs/{run_id}", headers=request.headers)
        if run_response.status_code >= 400:
            return forward(run_response)
        tasks = store.request(
            "GET",
            f"{internal}/runs/{run_id}/tasks",
            headers=request.headers,
            params={"limit": 100},
        )
        quality = store.request(
            "GET",
            f"{internal}/runs/{run_id}/quality-results",
            headers=request.headers,
            params={"limit": 100},
        )
        return jsonify(
            {
                "run": run_response.json()["run"],
                "tasks": tasks.json().get("items", []),
                "quality_results": quality.json().get("items", []),
            }
        )

    @api.post(f"{base}/tools/runs.explain.v1")
    def tool_run_explain() -> Response:
        run_id = required_uuid(json_body(), "run_id")
        run_response = store.request("GET", f"{internal}/runs/{run_id}", headers=request.headers)
        if run_response.status_code >= 400:
            return forward(run_response)
        tasks = store.request(
            "GET",
            f"{internal}/runs/{run_id}/tasks",
            headers=request.headers,
            params={"limit": 100},
        )
        quality = store.request(
            "GET",
            f"{internal}/runs/{run_id}/quality-results",
            headers=request.headers,
            params={"limit": 100},
        )
        return jsonify(
            build_run_inspection(
                run_response.json()["run"],
                tasks.json().get("items", []),
                quality.json().get("items", []),
            )
        )

    @api.post(f"{base}/tools/releases.inspect.v1")
    def tool_release() -> Response:
        return inspect_release(store, required_uuid(json_body(), "release_id"))

    @api.post(f"{base}/tools/releases.compare.v1")
    def tool_release_compare() -> Response:
        body = json_body()
        candidate = store.request(
            "GET",
            f"{internal}/releases/{required_uuid(body, 'candidate_release_id')}",
            headers=request.headers,
        )
        predecessor = store.request(
            "GET",
            f"{internal}/releases/{required_uuid(body, 'predecessor_release_id')}",
            headers=request.headers,
        )
        if candidate.status_code >= 400:
            return forward(candidate)
        if predecessor.status_code >= 400:
            return forward(predecessor)
        left, right = candidate.json()["release"], predecessor.json()["release"]
        fields = ("schema_version", "record_count", "content_sha256", "coverage_json", "status")
        differences = [
            {"field": field, "candidate": left.get(field), "predecessor": right.get(field)}
            for field in fields
            if left.get(field) != right.get(field)
        ]
        return jsonify({"candidate": left, "predecessor": right, "differences": differences})

    @api.post(f"{base}/tools/coverage.inspect.v1")
    def tool_coverage() -> Response:
        body = json_body()
        locality = str(body.get("locality", "")).strip()
        if not locality:
            return problem(422, "invalid_request", "locality is required")
        search = store.request(
            "GET",
            f"{internal}/properties/search",
            headers=request.headers,
            params={"q": locality, "state": "NSW", "limit": 25},
        )
        if search.status_code >= 400:
            return forward(search)
        evidence: dict[tuple[str, str], dict[str, Any]] = {}
        for item in search.json().get("items", []):
            if body.get("postcode") and item.get("postcode") != body["postcode"]:
                continue
            response = store.request(
                "GET",
                f"{internal}/properties/{item['property_ref']}/coverage",
                headers=request.headers,
            )
            for row in response.json().get("items", []):
                evidence[(row["dataset_id"], row["target_feature"])] = row
        return jsonify({"items": list(evidence.values())[:50]})

    @api.post(f"{base}/tools/properties.search.v1")
    def tool_property_search() -> Response:
        body = json_body()
        response = store.request(
            "GET",
            f"{internal}/properties/search",
            headers=request.headers,
            params={"q": body.get("query", ""), "state": "NSW", "limit": body.get("limit", 10)},
        )
        if response.status_code >= 400:
            return forward(response)
        data = response.json()
        return jsonify({"items": data.get("items", []), "count": data.get("count", 0)})

    @api.post(f"{base}/tools/properties.inspect.v1")
    def tool_property_inspect() -> Response:
        property_ref = required_uuid(json_body(), "property_ref")
        upstream = store.request(
            "GET", f"{internal}/properties/{property_ref}", headers=request.headers
        )
        if upstream.status_code >= 400:
            return forward(upstream)
        snapshot = upstream.json()
        return jsonify(
            {
                "property": snapshot["property"],
                "identifiers": snapshot.get("identifiers", [])[:25],
                "aliases": snapshot.get("aliases", [])[:25],
                "coverage": snapshot.get("coverage", [])[:25],
            }
        )

    @api.post(f"{base}/tools/runs.retry.v1")
    def tool_retry() -> Response:
        body = json_body()
        key = str(body.get("idempotency_key", "")).strip()
        if not key or not approved_tool_call(ai_mode, request.headers, "data.run_retry.v1", body):
            return problem(
                422,
                "human_approval_required",
                "Protected retry requires an approved agent run and idempotency key",
            )
        run_id = required_uuid(body, "run_id")
        original = store.request("GET", f"{internal}/runs/{run_id}", headers=request.headers)
        if original.status_code >= 400:
            return forward(original)
        source_run = original.json()["run"]
        created = store.request(
            "POST",
            f"{internal}/jobs/{source_run['job_definition_id']}/runs",
            headers=request.headers,
            json={
                "run_mode": "full_refresh",
                "scope": source_run["requested_scope_json"],
                "parent_run_id": str(run_id),
                "idempotency_key": key,
                "request_id": request.headers.get("X-Request-ID", str(uuid.uuid4())),
            },
        )
        if created.status_code >= 400:
            return forward(created)
        result = created.json()
        return jsonify({"child_run_id": result["run"]["id"], "replayed": not result["created"]})

    @api.post(f"{base}/tools/releases.publish.v1")
    def tool_publish() -> Response:
        body = json_body()
        key = str(body.get("idempotency_key", "")).strip()
        if not key or not approved_tool_call(
            ai_mode, request.headers, "data.release_publish.v1", body
        ):
            return problem(
                422,
                "human_approval_required",
                "Protected publication requires an approved agent run and idempotency key",
            )
        release_id = required_uuid(body, "release_id")
        return publish_release(
            store,
            consumers,
            release_id,
            {"comment": f"Approved agent operation {key}"},
            key,
            tool_output=True,
        )


def assistant_run(
    ai_mode: AiModeClient,
    run_id: uuid.UUID,
    headers: Mapping[str, str] | Headers,
) -> tuple[httpx.Response, bool]:
    """Load a run and prove it was created through the read-only assistant surface."""
    detail = ai_mode.get(f"/api/v1/agent-runs/{run_id}", headers)
    if detail.status_code >= 400:
        return detail, False
    try:
        payload = detail.json()
    except ValueError:
        return detail, False
    run = payload.get("run") if isinstance(payload, dict) else None
    if not isinstance(run, dict):
        return detail, False
    allowlist = run.get("tool_allowlist")
    owned = (
        run.get("feature_key") == ASSISTANT_FEATURE_KEY
        and isinstance(allowlist, list)
        and tuple(allowlist) == ASSISTANT_TOOL_ALLOWLIST
    )
    return detail, owned
