"""Fixtures for Feature 4 endpoint tests against the running Compose service.

The shared plugin skips every ``endpoint`` test unless ``PROPERTYSCOPE_ENDPOINT_BASE_URL``
is set, so the default quality gate never needs Docker. See ``student-4/README.md``.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from shared_testkit.endpoints import EndpointClient
from shared_testkit.pytest_endpoints import (
    endpoint_client,
    endpoint_ready_path,
    pytest_collection_modifyitems,
)

from .site_reviews import SITE_REVIEWS

__all__ = [
    "endpoint_client",
    "endpoint_ready_path",
    "pytest_collection_modifyitems",
]


@pytest.fixture
def created_reviews(endpoint_client: EndpointClient) -> Iterator[list[str]]:
    """Track site reviews a test creates and delete any it leaves behind."""
    created: list[str] = []
    yield created
    for review_id in created:
        response = endpoint_client.delete(f"{SITE_REVIEWS}/{review_id}")
        if response.status_code not in {200, 404}:
            raise AssertionError(
                f"could not clean up site review {review_id}: "
                f"HTTP {response.status_code} {response.text[:300]}"
            )
