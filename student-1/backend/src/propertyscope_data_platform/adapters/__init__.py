"""Pure acquisition adapter contracts and bounded fixture implementations."""

from .base import ArtifactRef, SourceObject, SourceSnapshot
from .fixture import FixtureProperty, parse_property_fixture

__all__ = [
    "ArtifactRef",
    "FixtureProperty",
    "SourceObject",
    "SourceSnapshot",
    "parse_property_fixture",
]
