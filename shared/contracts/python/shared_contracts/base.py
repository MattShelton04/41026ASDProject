"""Base types used by strict immutable project models."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Self

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    """Strict immutable model with validated copy-on-write evolution.

    Pydantic's default ``model_copy(update=...)`` trusts update values. These models are
    state and boundary snapshots, so updates are rebuilt through normal validation instead.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    def evolve(self, **changes: object) -> Self:
        """Return a fully revalidated snapshot containing the requested changes."""
        payload = self.model_dump(mode="python", round_trip=True)
        payload.update(changes)
        return type(self).model_validate(payload)

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        """Preserve Pydantic's API while validating any supplied updates."""
        copied = super().model_copy(deep=deep)
        if update is None:
            return copied
        return copied.evolve(**update)


class ContractModel(StrictModel):
    """Base for domain-neutral cross-service JSON contracts."""
