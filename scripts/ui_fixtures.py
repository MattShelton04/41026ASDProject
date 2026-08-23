"""Deterministic same-contract response catalogue for frontend-only UI development."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs
from uuid import NAMESPACE_URL, uuid5

SCENARIOS = (
    "populated",
    "empty",
    "slow",
    "error",
    "partial",
    "long-content",
    "large",
    "validation-error",
)


@dataclass(frozen=True)
class FixtureResponse:
    """One deterministic HTTP response returned by the fixture host."""

    status: int
    body: dict[str, Any]
    content_type: str = "application/json"
    delay_seconds: float = 0.0


REQUEST_ID = "ui-fixture-request-0001"
TIMESTAMP = "2026-08-23T00:00:00Z"
SOURCE_ID = "10000000-0000-0000-0000-000000000001"
JOB_ID = "20000000-0000-0000-0000-000000000001"
RUN_ID = "30000000-0000-0000-0000-000000000001"
TASK_ID = "40000000-0000-0000-0000-000000000001"
ARTIFACT_ID = "50000000-0000-0000-0000-000000000001"
RELEASE_ID = "60000000-0000-0000-0000-000000000001"
CANDIDATE_RELEASE_ID = "60000000-0000-0000-0000-000000000011"
REVIEW_RELEASE_ID = "60000000-0000-0000-0000-000000000012"
PROPERTY_ID = "11111111-1111-4111-8111-111111111111"
AGENT_RUN_ID = "70000000-0000-4000-8000-000000000001"
DATASET_ID = "property-identities"
FEATURE_KEY = "feature-1"
AGENT_FEATURE_KEY = "student-1-propertyscope-data-platform"
REPORT_SCHEMA = "propertyscope.report-section.v1"
PRODUCT_SCHEMA = "propertyscope.property-snapshot.v1"
LONG_TEXT = (
    "Long deterministic fixture content — Greater Sydney property evidence and operational "
    "status remain traceable even when a publisher supplies an unusually verbose name. "
    "<script>window.fixtureMustRemainText = true</script> "
    + "Evidence remains bounded and reviewable. "
    * 8
)


def _problem(status: int, title: str, detail: str, code: str) -> FixtureResponse:
    return FixtureResponse(
        status,
        {
            "type": "about:blank",
            "title": title,
            "status": status,
            "detail": detail,
            "code": code,
            "request_id": REQUEST_ID,
        },
        "application/problem+json",
    )


def _records(scenario: str) -> dict[str, list[dict[str, Any]]]:
    long = scenario == "long-content"
    source_name = LONG_TEXT if long else "Example NSW property records"
    address = LONG_TEXT if long else "11 Example Street, Sydney NSW 2000"
    status_text = LONG_TEXT if long else "Fixture records are current and ready for review."
    sources = [
        {
            "id": SOURCE_ID,
            "version": 3,
            "name": source_name,
            "publisher": "PropertyScope project",
            "source_url": "https://example.invalid/propertyscope/fixtures/property.csv",
            "adapter_key": "fixture-snapshot",
            "cadence": "on-demand",
            "licence_id": "synthetic-test-data",
            "licence_url": "https://creativecommons.org/publicdomain/zero/1.0/",
            "redistribution_policy": "committed-synthetic-fixture",
            "target_features": [FEATURE_KEY],
            "target_features_json": [FEATURE_KEY],
            "status": "active",
            "notes": status_text,
            "created_at": TIMESTAMP,
            "updated_at": TIMESTAMP,
        }
    ]
    jobs = [
        {
            "id": JOB_ID,
            "version": 5,
            "source_definition_id": SOURCE_ID,
            "name": LONG_TEXT if long else "Example property records update",
            "profile_key": "fixture-property-full",
            "profile_version": "1",
            "adapter_key": "fixture-snapshot",
            "release_builder_key": "property-snapshot",
            "import_profile_key": "fixture-property",
            "import_profile_version": "1",
            "target_feature": FEATURE_KEY,
            "dataset_id": DATASET_ID,
            "refresh_strategy": "full_snapshot",
            "default_run_mode": "full_refresh",
            "scope_json": {"profile": "showcase", "maximum_records": 20},
            "quality_policy_key": "property-identity-v1",
            "quality_policy_version": "1",
            "max_parallelism": 1,
            "timeout_seconds": 60,
            "max_objects": 2,
            "max_bytes": 1_000_000,
            "max_rows": 1_000,
            "status": "active",
            "schedule_text": "On demand",
            "created_at": TIMESTAMP,
            "updated_at": TIMESTAMP,
        }
    ]
    runs = [
        {
            "id": RUN_ID,
            "job_definition_id": JOB_ID,
            "job_name": LONG_TEXT if long else "Example property records update",
            "target_feature": FEATURE_KEY,
            "run_mode": "full_refresh",
            "status": "succeeded",
            "requested_at": TIMESTAMP,
            "started_at": TIMESTAMP,
            "finished_at": "2026-08-23T00:00:03Z",
            "rows_processed": 20,
            "rows_accepted": 20,
            "request_id": REQUEST_ID,
            "execution_semantics": "new_pipeline_run",
            "error_json": None,
            "status_message": status_text,
        }
    ]
    releases = [
        {
            "id": RELEASE_ID,
            "version": 2,
            "dataset_id": DATASET_ID,
            "source_definition_id": SOURCE_ID,
            "ingestion_run_id": RUN_ID,
            "target_feature": FEATURE_KEY,
            "release_version": "2026.08.23-fixture",
            "schema_version": PRODUCT_SCHEMA,
            "status": "accepted",
            "record_count": 20,
            "content_sha256": "a" * 64,
            "artifact_record_id": ARTIFACT_ID,
            "coverage_json": {
                "state": "NSW",
                "locality": "Sydney",
                "complete": True,
                "limitation": status_text,
            },
            "manifest_json": {"fixture": True, "scenario": scenario},
            "review_comment": "Deterministic fixture publication.",
            "accepted_at": TIMESTAMP,
            "created_at": TIMESTAMP,
        }
    ]
    releases.extend(
        [
            {
                **releases[0],
                "id": CANDIDATE_RELEASE_ID,
                "release_version": "2026.08.24-fixture-candidate",
                "status": "candidate",
                "accepted_at": None,
                "content_sha256": "b" * 64,
            },
            {
                **releases[0],
                "id": REVIEW_RELEASE_ID,
                "release_version": "2026.08.25-fixture-review",
                "status": "awaiting_review",
                "accepted_at": None,
                "content_sha256": "c" * 64,
            },
        ]
    )
    properties = [
        {
            "property_ref": PROPERTY_ID,
            "address_display": address,
            "locality": "Sydney",
            "state": "NSW",
            "postcode": "2000",
            "latitude": -33.8688,
            "longitude": 151.2093,
            "score": 0.98,
            "resolution_status": "verified",
            "geometry": {"type": "Point", "coordinates": [151.2093, -33.8688]},
            "updated_at": TIMESTAMP,
        }
    ]
    products = [
        {
            "dataset_id": DATASET_ID,
            "display_name": LONG_TEXT if long else "Property identity register",
            "source_key": "fixture-property",
            "job_profile": "fixture-property-full",
            "import_profile": "property-fixture",
            "target_feature": FEATURE_KEY,
            "product_schema_version": PRODUCT_SCHEMA,
            "builder_key": "property-snapshot",
            "builder_version": "1.0.0",
            "supported_scope_profiles": ["showcase", "test"],
            "redistribution_decision": "committed-synthetic-fixture",
            "download_permitted": True,
            "capability_state": "fixture_backed",
            "ordering_rule": "property_ref, source_address_id",
            "max_rows": 50_000,
            "max_bytes": 50_000_000,
            "known_limitations": [
                "Address identity is not legal title, parcel, ownership, valuation, "
                "or occupancy evidence."
            ],
            "latest_accepted_release": releases[0],
        }
    ]
    return {
        "sources": sources,
        "jobs": jobs,
        "runs": runs,
        "releases": releases,
        "properties": properties,
        "products": products,
    }


def _expanded(items: list[dict[str, Any]], scenario: str) -> list[dict[str, Any]]:
    if scenario != "large" or not items:
        return items
    # Keep the canonical row so foreign keys between fixture families remain navigable.
    expanded: list[dict[str, Any]] = [dict(items[0])]
    for index in range(2, 81):
        item = dict(items[(index - 1) % len(items)])
        for key in ("id", "property_ref"):
            if key in item:
                item[key] = str(uuid5(NAMESPACE_URL, f"propertyscope-ui:{item[key]}:{index}"))
        if "dataset_id" in item and "id" not in item:
            item["dataset_id"] = f"{item['dataset_id']}-{index:03d}"
        if "name" in item:
            item["name"] = f"{item['name']} {index:03d}"
        if "address_display" in item:
            item["address_display"] = f"{index} Example Street, Sydney NSW 2000"
        expanded.append(item)
    return expanded


def _collection(items: list[dict[str, Any]], scenario: str) -> dict[str, Any]:
    selected = [] if scenario == "empty" else _expanded(items, scenario)
    return {
        "items": selected,
        "count": len(selected),
        "limit": 100,
        "offset": 0,
        "next_offset": None,
    }


def fixture_response(
    method: str,
    path: str,
    query: str,
    scenario: str,
) -> FixtureResponse:
    """Resolve a public API request without changing any production browser code."""
    if scenario not in SCENARIOS:
        return _problem(400, "Unknown UI fixture scenario", scenario, "unknown_fixture_scenario")
    delay = 1.25 if scenario == "slow" and path.startswith("/api/") else 0.0
    if path in {"/healthz", "/health/ready", "/__ui-fixture__/ready"}:
        return FixtureResponse(200, {"status": "ready", "scenario": scenario}, delay_seconds=delay)
    if scenario == "error" and path.startswith("/api/"):
        response = _problem(
            503,
            "Fixture dependency unavailable",
            "This deterministic failure is recoverable; retry the request.",
            "fixture_dependency_unavailable",
        )
        return FixtureResponse(
            response.status,
            response.body,
            response.content_type,
            delay,
        )
    partial_optional = scenario == "partial" and any(
        marker in path
        for marker in (
            "/overview",
            "/map-context",
            "/coverage",
            "/report-section",
            "/artifacts",
            "/events",
        )
    )
    if scenario == "validation-error" and method in {"POST", "PUT", "PATCH"}:
        return _problem(
            422,
            "Fixture validation failed",
            "The submitted value conflicts with the deterministic validation fixture.",
            "fixture_validation_error",
        )

    records = _records(scenario)
    sources = records["sources"]
    jobs = records["jobs"]
    runs = records["runs"]
    releases = records["releases"]
    properties = records["properties"]
    products = records["products"]
    params = parse_qs(query)

    if path == "/api/shared-health/data-platform":
        return FixtureResponse(
            200,
            {
                "status": "healthy",
                "service": "data-platform",
                "dependencies": {"database": True},
            },
            delay_seconds=delay,
        )
    if path == "/api/shared-health/ai-mode":
        return FixtureResponse(
            200,
            {
                "status": "healthy",
                "service": "ai-mode",
                "checks": {
                    "llm_provider": {
                        "status": "ready",
                        "detail": "Deterministic fixture provider; no credentials or network used.",
                    }
                },
            },
            delay_seconds=delay,
        )
    if path in {
        "/api/ai-mode/agent-runs",
        "/api/data-platform/v1/agent-runs",
        "/api/v1/agent-runs",
    }:
        return FixtureResponse(200, _agent_run_page(scenario), delay_seconds=delay)
    for agent_prefix in (
        "/api/ai-mode/agent-runs/",
        "/api/data-platform/v1/agent-runs/",
        "/api/v1/agent-runs/",
        "/api/v1/operations/agent-runs/",
    ):
        if path.startswith(agent_prefix):
            identifier = path.removeprefix(agent_prefix).split("/", 1)[0]
            summary = _select(_expanded(_agent_runs(scenario), scenario), "id", identifier)
            if summary is None:
                return _not_found("Agent run", identifier, "agent_run_not_found")
            if path.endswith("/events"):
                if partial_optional:
                    return _optional_unavailable()
                return FixtureResponse(200, _agent_event_page(summary["id"]), delay_seconds=delay)
            if agent_prefix == "/api/v1/operations/agent-runs/":
                return FixtureResponse(
                    200, _agent_evidence_detail(summary, scenario), delay_seconds=delay
                )
            return FixtureResponse(200, _agent_run_detail(summary, scenario), delay_seconds=delay)
    prefix = "/api/data-platform/v1/"
    if not path.startswith(prefix):
        return _problem(404, "Fixture route not found", path, "fixture_route_not_found")
    route = path.removeprefix(prefix).strip("/")

    if route == "overview":
        if partial_optional:
            return _optional_unavailable()
        return FixtureResponse(
            200,
            {
                "runs": [{"status": "succeeded", "count": 1}],
                "releases": [
                    {"status": "accepted", "count": 1},
                    {"status": "candidate", "count": 1},
                    {"status": "awaiting_review", "count": 1},
                ],
                "failed_quality_checks": 0,
                "properties": 1,
            },
            delay_seconds=delay,
        )
    if route == "runtime-capabilities":
        return FixtureResponse(
            200,
            {
                "profile": "showcase",
                "full_data_enabled": False,
                "source_profiles": ["showcase", "test"],
            },
            delay_seconds=delay,
        )
    if route == "properties/search":
        search_body: dict[str, Any] = _collection(properties, scenario)
        search_body.pop("limit")
        search_body.pop("offset")
        search_body.pop("next_offset")
        search_body["supported"] = True
        search_body["query"] = params.get("q", [""])[0]
        return FixtureResponse(200, search_body, delay_seconds=delay)
    if route.startswith("properties/"):
        prop = _select(_expanded(properties, scenario), "property_ref", route.split("/")[1])
        if prop is None:
            return _not_found("Property", route.split("/")[1], "property_not_found")
        if partial_optional:
            return _optional_unavailable()
        return FixtureResponse(200, _property_response(route, prop, scenario), delay_seconds=delay)
    if route == "sources":
        return FixtureResponse(
            200, _mutation_or_collection(method, sources, scenario), delay_seconds=delay
        )
    if route.startswith("sources/"):
        source = _select(_expanded(sources, scenario), "id", route.split("/")[1])
        if source is None:
            return _not_found("Source", route.split("/")[1], "source_not_found")
        return FixtureResponse(200, {"source": source}, delay_seconds=delay)
    if route == "jobs":
        return FixtureResponse(
            200, _mutation_or_collection(method, jobs, scenario), delay_seconds=delay
        )
    if route.startswith("jobs/"):
        job = _select(_expanded(jobs, scenario), "id", route.split("/")[1])
        if job is None:
            return _not_found("Job", route.split("/")[1], "job_not_found")
        if route.endswith("/capabilities"):
            return FixtureResponse(200, _job_capabilities(), delay_seconds=delay)
        if route.endswith("/plans"):
            return FixtureResponse(200, _job_plan(), delay_seconds=delay)
        if route.endswith("/runs"):
            return FixtureResponse(201, {"run": runs[0]}, delay_seconds=delay)
        return FixtureResponse(200, {"job": job}, delay_seconds=delay)
    if route == "ingestion-runs":
        return FixtureResponse(200, _collection(runs, scenario), delay_seconds=delay)
    if route.startswith("ingestion-runs/"):
        run = _select(_expanded(runs, scenario), "id", route.split("/")[1])
        if run is None:
            return _not_found("Ingestion run", route.split("/")[1], "ingestion_run_not_found")
        if partial_optional:
            return _optional_unavailable()
        return FixtureResponse(200, _run_response(route, run, scenario), delay_seconds=delay)
    if route == "dataset-releases":
        return FixtureResponse(
            200 if method == "GET" else 201,
            _mutation_or_collection(method, releases, scenario, entity_key="release"),
            delay_seconds=delay,
        )
    if route.startswith("dataset-releases/"):
        release = _select(_expanded(releases, scenario), "id", route.split("/")[1])
        if release is None:
            return _not_found("Dataset release", route.split("/")[1], "release_not_found")
        return FixtureResponse(
            200,
            _release_response(route, release, scenario),
            delay_seconds=delay,
        )
    if route == "data-products":
        selected_products = [] if scenario == "empty" else _expanded(products, scenario)
        return FixtureResponse(
            200,
            {"items": selected_products, "count": len(selected_products), "next_cursor": None},
            delay_seconds=delay,
        )
    if route.startswith("data-products/"):
        product = _select(_expanded(products, scenario), "dataset_id", route.split("/")[1])
        if product is None:
            return _not_found("Data product", route.split("/")[1], "data_product_not_found")
        return FixtureResponse(200, product, delay_seconds=delay)
    return _problem(404, "Fixture route not found", route, "fixture_route_not_found")


def _mutation_or_collection(
    method: str,
    items: list[dict[str, Any]],
    scenario: str,
    *,
    entity_key: str = "item",
) -> dict[str, Any]:
    if method == "GET":
        return _collection(items, scenario)
    return {entity_key: items[0]}


def _select(items: list[dict[str, Any]], key: str, value: str) -> dict[str, Any] | None:
    return next((item for item in items if item.get(key) == value), None)


def _not_found(label: str, identifier: str, code: str) -> FixtureResponse:
    return _problem(404, f"{label} not found", f"No fixture record matches {identifier}.", code)


def _optional_unavailable() -> FixtureResponse:
    return _problem(
        503,
        "Optional fixture evidence unavailable",
        "Primary records remain available while this optional section is unavailable.",
        "fixture_optional_evidence_unavailable",
    )


def _property_response(route: str, prop: dict[str, Any], scenario: str) -> dict[str, Any]:
    if route.endswith("/map-context"):
        if scenario == "partial":
            return {"property_ref": prop["property_ref"], "coordinates": {}}
        return {
            "property_ref": prop["property_ref"],
            "address_display": prop["address_display"],
            "latitude": prop["latitude"],
            "longitude": prop["longitude"],
            "geometry": {"type": "Point", "coordinates": [151.2093, -33.8688]},
        }
    coverage = [
        {
            "dataset_id": DATASET_ID,
            "target_feature": FEATURE_KEY,
            "dataset_release_id": RELEASE_ID,
            "coverage_status": "accepted",
            "release_version": "2026.08.23-fixture",
            "schema_version": PRODUCT_SCHEMA,
            "coverage_scope": {"state": "NSW", "locality": "Sydney"},
            "checked_at": TIMESTAMP,
            "accepted_at": TIMESTAMP,
        }
    ]
    if route.endswith("/coverage"):
        items = [] if scenario == "empty" else coverage
        return {"items": items, "count": len(items)}
    if route.endswith("/report-section"):
        return {
            "schema_version": REPORT_SCHEMA,
            "property_ref": prop["property_ref"],
            "address_display": prop["address_display"],
            "evidence_count": 1,
            "identity": {
                "gnaf_pid": "GNAF-FIXTURE-0001",
                "resolution_status": "verified",
                "locality": "Sydney",
                "postcode": "2000",
                "state": "NSW",
                "longitude": prop["longitude"],
                "latitude": prop["latitude"],
                "geometry": {"type": "Point", "coordinates": [151.2093, -33.8688]},
            },
            "release_evidence": coverage,
        }
    detail = dict(prop)
    if scenario == "partial":
        detail.pop("latitude", None)
        detail.pop("longitude", None)
    return {
        "property": detail,
        "identifiers": [
            {
                "scheme": "gnaf_pid",
                "identifier_value": "GNAF-FIXTURE-0001",
                "match_method": "deterministic",
                "match_confidence": 1,
                "is_current": True,
                "evidence_json": {"fixture": True},
            }
        ],
        "aliases": [],
        "coverage": coverage,
    }


def _job_capabilities() -> dict[str, Any]:
    return {
        "run_modes": ["full_refresh", "reprocess_cached"],
        "source_profiles": ["showcase", "test"],
        "scope_profiles": {
            "showcase": {"maximum_records": 20},
            "test": {"maximum_records": 5},
        },
        "network_required": False,
    }


def _job_plan() -> dict[str, Any]:
    return {
        "job_definition_id": JOB_ID,
        "run_mode": "full_refresh",
        "network_required": False,
        "scope": {"profile": "showcase", "maximum_records": 20},
        "tasks": ["acquire", "validate", "load", "build-release"],
        "warnings": [],
    }


def _quality_results(scenario: str) -> list[dict[str, Any]]:
    message = LONG_TEXT if scenario == "long-content" else "All required fixture rows are present."
    return [
        {
            "id": "80000000-0000-4000-8000-000000000001",
            "run_id": RUN_ID,
            "rule_key": "fixture-row-count",
            "dimension": "completeness",
            "severity": "blocking",
            "status": "passed",
            "observed_value_json": {"rows": 20},
            "expected_value_json": {"minimum": 1},
            "message": message,
            "sample_json": None,
        }
    ]


def _artifacts() -> list[dict[str, Any]]:
    return [
        {
            "id": ARTIFACT_ID,
            "run_id": RUN_ID,
            "kind": "normalised-data",
            "filename": "property-identities.ndjson",
            "content_sha256": "a" * 64,
            "size_bytes": 2048,
            "created_at": TIMESTAMP,
            "lineage_json": {"fixture": True, "source": SOURCE_ID},
        }
    ]


def _run_response(route: str, run: dict[str, Any], scenario: str) -> dict[str, Any]:
    if route.endswith("/tasks"):
        return {
            "items": [
                {
                    "id": TASK_ID,
                    "name": "Load deterministic records",
                    "status": "succeeded",
                    "started_at": TIMESTAMP,
                    "finished_at": TIMESTAMP,
                }
            ]
        }
    if route.endswith("/quality-results"):
        return _collection(_quality_results(scenario), scenario)
    if route.endswith("/artifacts"):
        return _collection(_artifacts(), scenario)
    if any(
        route.endswith(f"/{action}") for action in ("resume", "retry", "reprocess-cached", "cancel")
    ):
        return {"run": run}
    return {"run": run}


def _release_response(route: str, release: dict[str, Any], scenario: str) -> dict[str, Any]:
    if route.endswith("/manifest"):
        return {
            "fixture": True,
            "schema_version": PRODUCT_SCHEMA,
            "files": ["property-identities.ndjson"],
        }
    if route.endswith("/records"):
        items = [] if scenario == "empty" else _expanded(_records(scenario)["properties"], scenario)
        return {
            "release": {"id": release["id"], "status": release["status"]},
            "profile": "property-fixture",
            "columns": [
                "source_address_id",
                "property_ref",
                "address_display",
                "flat_type",
                "unit_number",
                "street_number_first",
                "street_number_suffix",
                "street_number_last",
                "street_name",
                "street_type",
                "locality",
                "postcode",
                "source_status",
                "geocode_type",
                "source_crs",
                "geometry",
                "source_row_sha256",
                "normalisation_version",
            ],
            "items": [_preview_record(item) for item in items[:25]],
            "count": min(len(items), 25),
            "total": len(items),
            "limit": 25,
            "offset": 0,
            "next_offset": 25 if len(items) > 25 else None,
        }
    if any(
        route.endswith(f"/{action}")
        for action in ("submit-review", "publish", "reject", "agent-runs")
    ):
        return {"release": release}
    return {"release": release, "receipts": [], "manifest": release["manifest_json"]}


def _preview_record(prop: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_address_id": "fixture-address-0001",
        "property_ref": prop["property_ref"],
        "address_display": prop["address_display"],
        "flat_type": None,
        "unit_number": None,
        "street_number_first": "11",
        "street_number_suffix": None,
        "street_number_last": None,
        "street_name": "Example",
        "street_type": "Street",
        "locality": prop["locality"],
        "postcode": prop["postcode"],
        "source_status": "current",
        "geocode_type": "property_centre",
        "source_crs": "EPSG:4326",
        "geometry": prop["geometry"],
        "source_row_sha256": "d" * 64,
        "normalisation_version": "1.0.0",
    }


def _agent_runs(scenario: str) -> list[dict[str, Any]]:
    objective = (
        LONG_TEXT if scenario == "long-content" else "Review the accepted property fixture release."
    )
    return [
        {
            "id": AGENT_RUN_ID,
            "feature_key": AGENT_FEATURE_KEY,
            "objective_preview": objective[:160],
            "status": "succeeded",
            "latest_phase": "adapt",
            "latest_step_status": "succeeded",
            "model_profile": "fixture-model",
            "prompt_set": "default.v4",
            "iteration_count": 1,
            "tool_call_count": 1,
            "version": 4,
            "review_required": False,
            "error_code": None,
            "created_at": TIMESTAMP,
            "updated_at": TIMESTAMP,
            "duration_ms": 3000,
        }
    ]


def _agent_run_page(scenario: str) -> dict[str, Any]:
    items = [] if scenario == "empty" else _expanded(_agent_runs(scenario), scenario)
    return {"items": items, "next_cursor": None, "as_of": TIMESTAMP}


def _agent_event_page(run_id: str) -> dict[str, Any]:
    return {
        "items": [
            {
                "id": 1,
                "run_id": run_id,
                "run_version": 4,
                "event_type": "run_succeeded",
                "status": "succeeded",
                "occurred_at": TIMESTAMP,
                "step_id": None,
                "step_phase": None,
                "step_status": None,
            }
        ],
        "next_cursor": 1,
        "terminal": True,
    }


def _limits() -> dict[str, int]:
    return {
        "max_iterations": 6,
        "max_tool_calls": 12,
        "time_budget_ms": 120_000,
        "max_model_repairs": 1,
    }


def _agent_run_detail(summary: dict[str, Any], scenario: str) -> dict[str, Any]:
    result = LONG_TEXT if scenario == "long-content" else "No blocking issue was found."
    return {
        "run": {
            "id": summary["id"],
            "request_id": REQUEST_ID,
            "traceparent": None,
            "feature_key": summary["feature_key"],
            "objective": "Review the accepted property fixture release.",
            "status": summary["status"],
            "prompt_set": summary["prompt_set"],
            "model_profile": summary["model_profile"],
            "limits": _limits(),
            "iteration_count": summary["iteration_count"],
            "tool_call_count": summary["tool_call_count"],
            "version": summary["version"],
            "cancel_requested": False,
            "created_at": summary["created_at"],
            "updated_at": summary["updated_at"],
            "final_result": {"summary": result},
            "error": None,
        },
        "steps": [],
        "reviews": [],
    }


def _agent_evidence_detail(summary: dict[str, Any], scenario: str) -> dict[str, Any]:
    detail = _agent_run_detail(summary, scenario)["run"]
    return {
        "run": summary,
        "objective": detail["objective"],
        "limits": _limits(),
        "cancel_requested": False,
        "final_result": detail["final_result"],
        "error": None,
        "steps": [],
        "reviews": [],
        "correlation": {
            "request_id": REQUEST_ID,
            "run_id": summary["id"],
            "traceparent": None,
            "trace_id": None,
            "telemetry_url": None,
        },
    }
