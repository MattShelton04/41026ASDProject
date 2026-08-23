"""Deterministic same-contract response catalogue for frontend-only UI development."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs

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
    source_name = LONG_TEXT if long else "NSW Address Register"
    address = LONG_TEXT if long else "11 Example Street, Sydney NSW 2000"
    status_text = LONG_TEXT if long else "Fixture records are current and ready for review."
    sources = [
        {
            "id": "source-addresses",
            "version": 3,
            "name": source_name,
            "publisher": "PropertyScope deterministic fixture",
            "source_url": "https://example.test/address-register",
            "adapter_key": "fixture-addresses",
            "cadence": "monthly",
            "licence_id": "fixture-open-data-v1",
            "licence_url": "https://example.test/licence",
            "redistribution_policy": "Synthetic records may be redistributed for testing.",
            "target_features": ["property-discovery"],
            "target_features_json": ["property-discovery"],
            "status": "active",
            "notes": status_text,
            "created_at": TIMESTAMP,
            "updated_at": TIMESTAMP,
        }
    ]
    jobs = [
        {
            "id": "job-addresses",
            "version": 5,
            "source_definition_id": "source-addresses",
            "name": LONG_TEXT if long else "Refresh NSW property identities",
            "profile_key": "fixture-property-full",
            "profile_version": "1",
            "adapter_key": "fixture-addresses",
            "release_builder_key": "property-identity",
            "import_profile_key": "fixture-property",
            "import_profile_version": "1",
            "target_feature": "property-discovery",
            "dataset_id": "property-identities",
            "refresh_strategy": "full_snapshot",
            "default_run_mode": "full_refresh",
            "scope_json": {"profile": "showcase", "maximum_records": 20},
            "quality_policy_key": "property-identity-v1",
            "quality_policy_version": "1",
            "max_parallelism": 1,
            "timeout_seconds": 300,
            "max_objects": 5,
            "max_bytes": 1_000_000,
            "max_rows": 500,
            "status": "active",
            "schedule_text": "On demand",
            "created_at": TIMESTAMP,
            "updated_at": TIMESTAMP,
        }
    ]
    runs = [
        {
            "id": "run-addresses-0001",
            "job_definition_id": "job-addresses",
            "job_name": LONG_TEXT if long else "Refresh NSW property identities",
            "target_feature": "property-discovery",
            "run_mode": "full_refresh",
            "status": "succeeded",
            "requested_at": TIMESTAMP,
            "started_at": TIMESTAMP,
            "finished_at": "2026-08-23T00:00:03Z",
            "rows_processed": 20,
            "error_json": None,
            "status_message": status_text,
        }
    ]
    releases = [
        {
            "id": "release-addresses-0001",
            "version": 2,
            "dataset_id": "property-identities",
            "source_definition_id": "source-addresses",
            "ingestion_run_id": "run-addresses-0001",
            "target_feature": "property-discovery",
            "release_version": "2026.08.23-fixture",
            "schema_version": "1.0",
            "status": "accepted",
            "record_count": 20,
            "content_sha256": "a" * 64,
            "artifact_record_id": "artifact-addresses-0001",
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
                "id": "release-addresses-0002",
                "release_version": "2026.08.24-fixture-candidate",
                "status": "candidate",
                "accepted_at": None,
                "content_sha256": "b" * 64,
            },
            {
                **releases[0],
                "id": "release-addresses-0003",
                "release_version": "2026.08.25-fixture-review",
                "status": "awaiting_review",
                "accepted_at": None,
                "content_sha256": "c" * 64,
            },
        ]
    )
    properties = [
        {
            "property_ref": "ps-fixture-0001",
            "address_display": address,
            "locality": "Sydney",
            "state": "NSW",
            "postcode": "2000",
            "latitude": -33.8688,
            "longitude": 151.2093,
            "score": 0.98,
            "resolution_status": "verified",
            "updated_at": TIMESTAMP,
        }
    ]
    products = [
        {
            "dataset_id": "property-identities",
            "name": LONG_TEXT if long else "Property identity register",
            "target_feature": "property-discovery",
            "schema_version": "1.0",
            "accepted_release_id": "release-addresses-0001",
            "accepted_release_version": "2026.08.23-fixture",
            "limitations": status_text,
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
    expanded: list[dict[str, Any]] = []
    for index in range(1, 81):
        item = dict(items[(index - 1) % len(items)])
        for key in ("id", "property_ref"):
            if key in item:
                item[key] = f"{item[key]}-{index:03d}"
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
    if path in {"/healthz", "/health/ready"}:
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
    if scenario == "partial" and any(
        marker in path
        for marker in (
            "/overview",
            "/map-context",
            "/coverage",
            "/report-section",
            "/artifacts",
            "/events",
        )
    ):
        return _problem(
            503,
            "Optional fixture evidence unavailable",
            "Primary records remain available while this optional section is unavailable.",
            "fixture_optional_evidence_unavailable",
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

    if path.startswith("/api/shared-health/"):
        return FixtureResponse(
            200,
            {
                "status": "healthy",
                "service": path.rsplit("/", 1)[-1],
                "dependencies": {"database": True},
            },
            delay_seconds=delay,
        )
    if path in {"/api/ai-mode/agent-runs", "/api/data-platform/v1/agent-runs"}:
        return FixtureResponse(
            200, _collection(_agent_runs(scenario), scenario), delay_seconds=delay
        )
    if path.startswith("/api/ai-mode/agent-runs/") or path.startswith(
        "/api/data-platform/v1/agent-runs/"
    ):
        agent_body: dict[str, Any] = {
            "run": _agent_runs(scenario)[0],
            "events": _agent_events(scenario),
        }
        if path.endswith("/events"):
            agent_body = {"items": _agent_events(scenario), "next_after": 2}
        return FixtureResponse(200, agent_body, delay_seconds=delay)
    prefix = "/api/data-platform/v1/"
    if not path.startswith(prefix):
        return _problem(404, "Fixture route not found", path, "fixture_route_not_found")
    route = path.removeprefix(prefix).strip("/")

    if route == "overview":
        return FixtureResponse(
            200,
            {
                "status": "ready",
                "summary": "Deterministic UI fixture overview",
                "generated_at": TIMESTAMP,
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
        return FixtureResponse(200, _property_response(route, prop, scenario), delay_seconds=delay)
    if route == "sources":
        return FixtureResponse(
            200, _mutation_or_collection(method, sources, scenario), delay_seconds=delay
        )
    if route.startswith("sources/"):
        source = _select(_expanded(sources, scenario), "id", route.split("/")[1])
        return FixtureResponse(200, {"source": source}, delay_seconds=delay)
    if route == "jobs":
        return FixtureResponse(
            200, _mutation_or_collection(method, jobs, scenario), delay_seconds=delay
        )
    if route.startswith("jobs/"):
        job = _select(_expanded(jobs, scenario), "id", route.split("/")[1])
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
        return FixtureResponse(200, _run_response(route, run, scenario), delay_seconds=delay)
    if route == "dataset-releases":
        return FixtureResponse(
            200 if method == "GET" else 201,
            _mutation_or_collection(method, releases, scenario, entity_key="release"),
            delay_seconds=delay,
        )
    if route.startswith("dataset-releases/"):
        release = _select(_expanded(releases, scenario), "id", route.split("/")[1])
        return FixtureResponse(
            200,
            _release_response(route, release, scenario),
            delay_seconds=delay,
        )
    if route == "data-products":
        return FixtureResponse(200, _collection(products, scenario), delay_seconds=delay)
    if route.startswith("data-products/"):
        product = _select(_expanded(products, scenario), "dataset_id", route.split("/")[1])
        return FixtureResponse(200, {"data_product": product}, delay_seconds=delay)
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


def _select(items: list[dict[str, Any]], key: str, value: str) -> dict[str, Any]:
    return next((item for item in items if item.get(key) == value), items[0])


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
            "dataset_id": "property-identities",
            "target_feature": "property-discovery",
            "dataset_release_id": "release-addresses-0001",
            "status": "accepted",
            "coverage_status": "accepted",
            "release_version": "2026.08.23-fixture",
            "schema_version": "1.0",
            "coverage_scope": {"state": "NSW", "locality": "Sydney"},
            "checked_at": TIMESTAMP,
            "accepted_at": TIMESTAMP,
            "limitation": "Synthetic UI fixture only.",
        }
    ]
    if route.endswith("/coverage"):
        items = [] if scenario == "empty" else coverage
        return {"items": items, "count": len(items)}
    if route.endswith("/report-section"):
        return {
            "schema_version": "1.0",
            "property_ref": prop["property_ref"],
            "address_display": prop["address_display"],
            "evidence_count": 1,
            "identity": {
                "gnaf_pid": "GNAF-FIXTURE-0001",
                "resolution_status": "verified",
                "locality": "Sydney",
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
                "scheme": "fixture",
                "identifier_value": "GNAF-FIXTURE-0001",
                "match_method": "deterministic",
                "match_confidence": 1,
                "is_current": True,
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
        "job_definition_id": "job-addresses",
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
            "id": "quality-0001",
            "run_id": "run-addresses-0001",
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
            "id": "artifact-addresses-0001",
            "run_id": "run-addresses-0001",
            "kind": "normalised-data",
            "filename": "property-identities.ndjson",
            "content_sha256": "a" * 64,
            "size_bytes": 2048,
            "created_at": TIMESTAMP,
            "lineage_json": {"fixture": True, "source": "source-addresses"},
        }
    ]


def _run_response(route: str, run: dict[str, Any], scenario: str) -> dict[str, Any]:
    if route.endswith("/tasks"):
        return {
            "items": [
                {
                    "id": "task-0001",
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
        return {"fixture": True, "schema_version": "1.0", "files": ["property-identities.ndjson"]}
    if route.endswith("/records"):
        items = [] if scenario == "empty" else _expanded(_records(scenario)["properties"], scenario)
        return {
            "release": {"id": release["id"], "status": release["status"]},
            "profile": "property-identity",
            "columns": ["property_ref", "address_display", "locality", "state", "postcode"],
            "items": items[:25],
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


def _agent_runs(scenario: str) -> list[dict[str, Any]]:
    result = LONG_TEXT if scenario == "long-content" else "Fixture review found no blocking issue."
    return [
        {
            "id": "agent-run-0001",
            "status": "succeeded",
            "objective": "Review release-addresses-0001",
            "result": result,
            "created_at": TIMESTAMP,
            "updated_at": TIMESTAMP,
        }
    ]


def _agent_events(scenario: str) -> list[dict[str, Any]]:
    return [
        {
            "id": "agent-event-0001",
            "sequence": 1,
            "kind": "status",
            "message": LONG_TEXT if scenario == "long-content" else "Review completed.",
            "created_at": TIMESTAMP,
        }
    ]
