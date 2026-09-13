"""Typed database boundary failures."""

from __future__ import annotations


class StoreError(RuntimeError):
    """Base class for safe persistence errors."""


class NotFoundError(StoreError):
    """Requested aggregate does not exist."""


class ConflictError(StoreError):
    """Optimistic version, lifecycle, or uniqueness conflict."""


class ValidationError(StoreError):
    """Request violates the registered persistence policy."""


class LeaseConflictError(ConflictError):
    """Worker does not own the current live lease."""


class ReadBudgetExceededError(StoreError):
    """An interactive read was cancelled before its HTTP caller gives up."""
