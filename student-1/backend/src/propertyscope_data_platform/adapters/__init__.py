"""Pure acquisition adapter contracts and bounded fixture implementations."""

from .base import ArtifactRef, SourceObject, SourceSnapshot
from .fixture import FixtureProperty, parse_property_fixture
from .reference import REFERENCE_PROFILES, discover_reference_sources, iter_reference_records

__all__ = [
    "REFERENCE_PROFILES",
    "ArtifactRef",
    "FixtureProperty",
    "SourceObject",
    "SourceSnapshot",
    "discover_reference_sources",
    "iter_reference_records",
    "parse_property_fixture",
]
