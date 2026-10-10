from __future__ import annotations

import httpx

from propertyscope_data_platform.app import create_app
from propertyscope_data_platform.clients import AiModeClient, DataStoreClient, MultiAgentClient

EXPECTED_ASSISTANT_TOOL_ROUTES: dict[str, tuple[str, frozenset[str]]] = {
    "/api/data-platform/v1/dataset-releases/<uuid:release_id>/agent-runs": (
        "propertyscope-data-platform.release_agent_run",
        frozenset({"POST"}),
    ),
    "/api/data-platform/v1/assistant/turns": (
        "propertyscope-data-platform.assistant_turn",
        frozenset({"POST"}),
    ),
    "/api/data-platform/v1/assistant/turns/<uuid:run_id>": (
        "propertyscope-data-platform.assistant_turn_detail",
        frozenset({"GET"}),
    ),
    "/api/data-platform/v1/assistant/turns/<uuid:run_id>/events": (
        "propertyscope-data-platform.assistant_turn_events",
        frozenset({"GET"}),
    ),
    "/api/data-platform/v1/assistant/turns/<uuid:run_id>/cancel": (
        "propertyscope-data-platform.assistant_turn_cancel",
        frozenset({"POST"}),
    ),
    "/api/data-platform/v1/agent-runs/<uuid:run_id>": (
        "propertyscope-data-platform.agent_run",
        frozenset({"GET"}),
    ),
    "/api/data-platform/v1/agent-runs": (
        "propertyscope-data-platform.agent_runs",
        frozenset({"GET"}),
    ),
    "/api/data-platform/v1/agent-runs/<uuid:run_id>/events": (
        "propertyscope-data-platform.agent_events",
        frozenset({"GET"}),
    ),
    "/api/data-platform/v1/tools/sources.list.v1": (
        "propertyscope-data-platform.tool_sources",
        frozenset({"POST"}),
    ),
    "/api/data-platform/v1/tools/releases.list.v1": (
        "propertyscope-data-platform.tool_releases",
        frozenset({"POST"}),
    ),
    "/api/data-platform/v1/tools/platform.capabilities.v1": (
        "propertyscope-data-platform.tool_platform_capabilities",
        frozenset({"POST"}),
    ),
    "/api/data-platform/v1/tools/runs.list.v1": (
        "propertyscope-data-platform.tool_runs",
        frozenset({"POST"}),
    ),
    "/api/data-platform/v1/tools/runs.inspect.v1": (
        "propertyscope-data-platform.tool_run",
        frozenset({"POST"}),
    ),
    "/api/data-platform/v1/tools/runs.explain.v1": (
        "propertyscope-data-platform.tool_run_explain",
        frozenset({"POST"}),
    ),
    "/api/data-platform/v1/tools/releases.inspect.v1": (
        "propertyscope-data-platform.tool_release",
        frozenset({"POST"}),
    ),
    "/api/data-platform/v1/tools/releases.compare.v1": (
        "propertyscope-data-platform.tool_release_compare",
        frozenset({"POST"}),
    ),
    "/api/data-platform/v1/tools/coverage.inspect.v1": (
        "propertyscope-data-platform.tool_coverage",
        frozenset({"POST"}),
    ),
    "/api/data-platform/v1/tools/properties.search.v1": (
        "propertyscope-data-platform.tool_property_search",
        frozenset({"POST"}),
    ),
    "/api/data-platform/v1/tools/properties.inspect.v1": (
        "propertyscope-data-platform.tool_property_inspect",
        frozenset({"POST"}),
    ),
    "/api/data-platform/v1/tools/properties.locality-summary.v1": (
        "propertyscope-data-platform.tool_property_locality_summary",
        frozenset({"POST"}),
    ),
    "/api/data-platform/v1/tools/runs.retry.v1": (
        "propertyscope-data-platform.tool_retry",
        frozenset({"POST"}),
    ),
    "/api/data-platform/v1/tools/releases.publish.v1": (
        "propertyscope-data-platform.tool_publish",
        frozenset({"POST"}),
    ),
}


def test_assistant_and_tool_route_registration_preserves_public_endpoints() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={}))
    app = create_app(
        store_client=DataStoreClient(
            "http://database",
            "secret",
            client=httpx.Client(transport=transport),
        ),
        ai_mode_client=AiModeClient(
            "http://ai",
            client=httpx.Client(transport=transport),
        ),
    )

    observed: dict[str, tuple[str, frozenset[str]]] = {}
    for rule in app.url_map.iter_rules():
        if not _is_extracted_route(rule.rule):
            continue
        methods = frozenset(set(rule.methods or ()) - {"HEAD", "OPTIONS"})
        observed[rule.rule] = (rule.endpoint, methods)

    assert observed == EXPECTED_ASSISTANT_TOOL_ROUTES


def _is_extracted_route(rule: str) -> bool:
    return any(
        marker in rule
        for marker in (
            "/assistant/turns",
            "/agent-runs",
            "/tools/",
        )
    )


EXPECTED_RELEASE_REVIEW_ROUTES = frozenset(
    {
        ("/api/data-platform/v1/release-reviews", "start_release_review", "POST"),
        ("/api/data-platform/v1/release-reviews", "list_release_reviews", "GET"),
        ("/api/data-platform/v1/release-reviews/template", "release_review_template", "GET"),
        ("/api/data-platform/v1/release-reviews/<uuid:run_id>", "release_review_detail", "GET"),
        (
            "/api/data-platform/v1/release-reviews/<uuid:run_id>/decision",
            "decide_release_review",
            "POST",
        ),
        (
            "/api/data-platform/v1/release-reviews/<uuid:run_id>/cancel",
            "cancel_release_review",
            "POST",
        ),
        (
            "/api/data-platform/v1/release-reviews/<uuid:run_id>/history",
            "release_review_history",
            "GET",
        ),
    }
)


def test_release_review_proxy_routes_are_registered_exactly() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={}))
    app = create_app(
        store_client=DataStoreClient(
            "http://database", "secret", client=httpx.Client(transport=transport)
        ),
        ai_mode_client=AiModeClient("http://ai", client=httpx.Client(transport=transport)),
        multi_agent_client=MultiAgentClient(
            "http://multi-agent", client=httpx.Client(transport=transport)
        ),
    )

    observed = frozenset(
        (rule.rule, rule.endpoint.removeprefix("propertyscope-data-platform."), method)
        for rule in app.url_map.iter_rules()
        if "/release-reviews" in rule.rule
        for method in set(rule.methods or ()) - {"HEAD", "OPTIONS"}
    )

    assert observed == EXPECTED_RELEASE_REVIEW_ROUTES
