"""Strict internal models used at agent-core ports."""

from pydantic import BaseModel, ConfigDict


class CoreModel(BaseModel):
    """Reject undocumented fields at adapter boundaries."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
