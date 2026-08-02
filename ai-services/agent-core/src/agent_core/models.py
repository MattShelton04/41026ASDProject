"""Strict internal models used at agent-core ports."""

from pydantic import BaseModel, ConfigDict


class CoreModel(BaseModel):
    """Reject undocumented fields and preserve port values as snapshots."""

    model_config = ConfigDict(extra="forbid", frozen=True)
