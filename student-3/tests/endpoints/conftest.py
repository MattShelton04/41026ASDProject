"""Fixtures for Feature 3 endpoint tests against the running Compose service."""

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
