from __future__ import annotations

import httpx

from propertyscope_data_platform.app import create_app
from propertyscope_data_platform.clients import AiModeClient, DataStoreClient

EXPECTED_RELEASE_AND_PRODUCT_ROUTES: dict[str, tuple[str, frozenset[str]]] = {
    "/api/data-platform/v1/data-products": (
        "propertyscope-data-platform.data_products",
        frozenset({"GET"}),
    ),
    "/api/data-platform/v1/data-products/<dataset_id>": (
        "propertyscope-data-platform.data_product",
        frozenset({"GET"}),
    ),
    "/api/data-platform/v1/data-products/<dataset_id>/accepted": (
        "propertyscope-data-platform.accepted_data_product",
        frozenset({"GET"}),
    ),
    "/api/data-platform/v1/data-products/<dataset_id>/source-records": (
        "propertyscope-data-platform.data_product_source_records",
        frozenset({"GET"}),
    ),
    "/api/data-platform/v1/dataset-releases": (
        "propertyscope-data-platform.releases",
        frozenset({"GET", "POST"}),
    ),
    "/api/data-platform/v1/dataset-releases/<uuid:release_id>": (
        "propertyscope-data-platform.release",
        frozenset({"GET", "PUT", "DELETE"}),
    ),
    "/api/data-platform/v1/dataset-releases/<uuid:release_id>/manifest": (
        "propertyscope-data-platform.release_manifest",
        frozenset({"GET"}),
    ),
    "/api/data-platform/v1/dataset-releases/<uuid:release_id>/artifact": (
        "propertyscope-data-platform.release_artifact",
        frozenset({"GET"}),
    ),
    "/api/data-platform/v1/dataset-releases/<uuid:release_id>/records": (
        "propertyscope-data-platform.release_records",
        frozenset({"GET"}),
    ),
    "/api/data-platform/v1/dataset-releases/<uuid:release_id>/submit-review": (
        "propertyscope-data-platform.release_review",
        frozenset({"POST"}),
    ),
    "/api/data-platform/v1/dataset-releases/<uuid:release_id>/publish": (
        "propertyscope-data-platform.release_publish",
        frozenset({"POST"}),
    ),
    (
        "/api/data-platform/v1/dataset-releases/<uuid:release_id>"
        "/consumer-imports/<uuid:operation_id>"
    ): (
        "propertyscope-data-platform.release_consumer_import",
        frozenset({"GET"}),
    ),
    "/api/data-platform/v1/dataset-releases/<uuid:release_id>/reject": (
        "propertyscope-data-platform.release_reject",
        frozenset({"POST"}),
    ),
}


def test_release_and_data_product_registrars_preserve_public_endpoints() -> None:
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

    assert observed == EXPECTED_RELEASE_AND_PRODUCT_ROUTES


def _is_extracted_route(rule: str) -> bool:
    return "/data-products" in rule or ("/dataset-releases" in rule and "/agent-runs" not in rule)
