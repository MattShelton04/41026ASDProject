"""Deterministic model provider for unit and component tests."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable

from agent_core import (
    LLMProvider,
    ProviderHealth,
    StructuredModelRequest,
    StructuredModelResult,
)


class ScriptedLLMProvider(LLMProvider):
    """Return scripted responses or failures while recording every request."""

    def __init__(
        self,
        outcomes: Iterable[StructuredModelResult | Exception],
        *,
        health: ProviderHealth | None = None,
    ) -> None:
        self._outcomes = deque(outcomes)
        self._health = health or ProviderHealth(reachable=True, detail="scripted provider ready")
        self.requests: list[StructuredModelRequest] = []

    def generate_structured(self, request: StructuredModelRequest) -> StructuredModelResult:
        """Return the next scripted outcome and fail on unexpected extra calls."""
        self.requests.append(request)
        if not self._outcomes:
            raise AssertionError("scripted provider received an unexpected invocation")
        outcome = self._outcomes.popleft()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def health(self) -> ProviderHealth:
        """Return the configured deterministic health snapshot."""
        return self._health

    @property
    def remaining_outcomes(self) -> int:
        """Expose unused outcomes so tests can assert exact invocation counts."""
        return len(self._outcomes)
