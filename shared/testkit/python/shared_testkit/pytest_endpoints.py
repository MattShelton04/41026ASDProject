"""Pytest fixtures and the skip hook for opt-in ``endpoint`` tests.

Re-export these names from the ``conftest.py`` of a feature's ``tests/endpoints``
directory::

    from shared_testkit.pytest_endpoints import (
        endpoint_client,
        endpoint_ready_path,
        pytest_collection_modifyitems,
    )

    __all__ = ["endpoint_client", "endpoint_ready_path", "pytest_collection_modifyitems"]

Mark each test (or module, via ``pytestmark``) with ``@pytest.mark.endpoint``. Without
``PROPERTYSCOPE_ENDPOINT_BASE_URL`` every marked test is reported as skipped, so a default
``pytest`` or ``check.py`` run never needs Docker or the network. Override the
``endpoint_ready_path`` fixture when a service exposes readiness somewhere other than
``/health/ready`` (or set ``PROPERTYSCOPE_ENDPOINT_READY_PATH``).
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping

import pytest

from shared_testkit.endpoints import (
    ENDPOINT_BASE_URL_ENV,
    ENDPOINT_MARKER,
    EndpointClient,
    endpoint_base_url,
    open_endpoint_client,
)
from shared_testkit.endpoints import (
    endpoint_ready_path as configured_ready_path,
)

SKIP_REASON = f"endpoint test: set {ENDPOINT_BASE_URL_ENV} to the running service origin"


def skip_unconfigured_endpoint_items(items: list[pytest.Item], environ: Mapping[str, str]) -> int:
    """Mark ``endpoint`` items as skipped when no base URL is configured.

    Returns the number of items that were marked.
    """
    if endpoint_base_url(environ) is not None:
        return 0
    marked = 0
    skip = pytest.mark.skip(reason=SKIP_REASON)
    for item in items:
        if item.get_closest_marker(ENDPOINT_MARKER) is not None:
            item.add_marker(skip)
            marked += 1
    return marked


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip opt-in endpoint tests unless the run targets a live service."""
    del config
    skip_unconfigured_endpoint_items(items, os.environ)


@pytest.fixture(scope="session")
def endpoint_ready_path() -> str:
    """Readiness route polled once before the first endpoint test in a session."""
    return configured_ready_path(os.environ)


@pytest.fixture(scope="session")
def endpoint_client(endpoint_ready_path: str) -> Iterator[EndpointClient]:
    """A ready client for the configured service, or a skip when none is configured."""
    client = open_endpoint_client(os.environ, ready_path=endpoint_ready_path)
    if client is None:
        pytest.skip(SKIP_REASON)
    with client:
        yield client
