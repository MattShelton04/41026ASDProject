"""Strict internal models used at agent-core ports."""

from shared_contracts.base import StrictModel


class CoreModel(StrictModel):
    """Reject undocumented fields and preserve port values as snapshots."""
