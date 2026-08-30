"""Typed failures translated to HTTP Problem Details by the private API."""

from __future__ import annotations


class StoreError(Exception):
    """Base class for expected store failures."""


class ValidationError(StoreError):
    """The caller supplied invalid POC domain data."""


class NotFoundError(StoreError):
    """The requested aggregate does not exist."""


class ConflictError(StoreError):
    """The requested write conflicts with retained state."""
