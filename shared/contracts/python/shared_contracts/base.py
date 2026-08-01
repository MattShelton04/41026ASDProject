"""Base types used by domain-neutral cross-service contracts."""

from pydantic import BaseModel, ConfigDict


class ContractModel(BaseModel):
    """Strict, immutable-by-convention JSON contract base.

    Assignment validation is enabled so an already validated contract cannot later be
    mutated into an invalid value by application code.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
