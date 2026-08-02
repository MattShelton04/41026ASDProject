"""Base types used by domain-neutral cross-service contracts."""

from pydantic import BaseModel, ConfigDict


class ContractModel(BaseModel):
    """Strict immutable JSON contract base.

    State changes use explicit ``model_copy`` operations so persisted snapshots cannot be
    mutated accidentally outside their optimistic-concurrency boundary.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
