"""Streaming dispatch for the closed producer-owned reference-source catalogue."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx

from .reference_catalog import REFERENCE_PROFILES, SPATIAL_PROFILES


def discover_reference_objects(profile: str, client: httpx.Client) -> list[dict[str, Any]]:
    if profile not in REFERENCE_PROFILES:
        raise ValueError("Reference source profile is not registered")
    if profile in SPATIAL_PROFILES:
        from .adapters.spatial import discover_spatial_sources

        return discover_spatial_sources(profile, client)
    from .adapters.reference import discover_reference_sources

    return discover_reference_sources(profile, client)


def iter_reference_records(
    profile: str, client: httpx.Client, objects: list[dict[str, Any]]
) -> Iterator[dict[str, Any]]:
    if profile not in REFERENCE_PROFILES:
        raise ValueError("Reference source profile is not registered")
    if profile in SPATIAL_PROFILES:
        from .adapters.spatial import iter_spatial_records

        yield from iter_spatial_records(profile, client, objects)
        return
    from .adapters.reference import iter_reference_records as reference_records

    yield from reference_records(profile, client, objects)
