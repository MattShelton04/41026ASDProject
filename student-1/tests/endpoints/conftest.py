"""Fixtures for Feature 1 endpoint tests against the running Compose service.

The shared plugin skips every ``endpoint`` test unless ``PROPERTYSCOPE_ENDPOINT_BASE_URL``
is set, so the default quality gate never needs Docker. See ``student-1/README.md``.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import jsonschema
import pytest
import yaml

from shared_testkit.endpoints import EndpointClient
from shared_testkit.pytest_endpoints import (
    endpoint_client,
    endpoint_ready_path,
    pytest_collection_modifyitems,
)

__all__ = [
    "endpoint_client",
    "endpoint_ready_path",
    "pytest_collection_modifyitems",
]

API = "/api/data-platform/v1"
OPENAPI_PATH = Path(__file__).resolve().parents[2] / "contracts/data-platform-api.v1.openapi.yaml"
SEARCH_QUERY_ENV = "PROPERTYSCOPE_F1_ENDPOINT_SEARCH_QUERY"
# Present in every fresh database through the showcase seed and the fixture-property job.
DEFAULT_SEARCH_QUERY = "11 Example Street"

ContractValidator = Callable[[object, dict[str, Any]], None]


@pytest.fixture(scope="session")
def validate_contract() -> ContractValidator:
    """Validate a live payload against a schema that may ``$ref`` the committed OpenAPI.

    References such as ``#/components/schemas/PropertySearchPage`` resolve inside the
    Feature 1 OpenAPI document, using its 3.1 (JSON Schema 2020-12) semantics with format
    checks, so these tests fail when the running service drifts from its contract.
    """
    components = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))["components"]

    def validate(payload: object, schema: dict[str, Any]) -> None:
        validator = jsonschema.Draft202012Validator(
            {**schema, "components": components},
            format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER,
        )
        validator.validate(payload)

    return validate


@pytest.fixture(scope="session")
def search_query() -> str:
    """A seeded address; override for a stack whose accepted data replaced the seed."""
    return os.environ.get(SEARCH_QUERY_ENV, "").strip() or DEFAULT_SEARCH_QUERY


@pytest.fixture
def created_sources(endpoint_client: EndpointClient) -> Iterator[list[str]]:
    """Track source definitions a test creates and delete any it leaves behind."""
    created: list[str] = []
    yield created
    for source_id in created:
        response = endpoint_client.delete(f"{API}/sources/{source_id}")
        if response.status_code not in {204, 404}:
            raise AssertionError(
                f"could not clean up source definition {source_id}: "
                f"HTTP {response.status_code} {response.text[:300]}"
            )
