"""Structured errors that map one-to-one onto Problem Details responses."""

from __future__ import annotations

from shared_contracts import FieldIssue


class MultiAgentError(Exception):
    """Base error carrying a stable code, an HTTP status and safe detail text."""

    status = 500
    code = "internal_error"

    def __init__(self, detail: str, *, errors: tuple[FieldIssue, ...] = ()) -> None:
        super().__init__(detail)
        self.detail = detail
        self.errors = errors


class InvalidRequestError(MultiAgentError):
    """The request body or query violates the published contract."""

    status = 400
    code = "invalid_request"


class InvalidWorkflowInputError(MultiAgentError):
    """The run input does not satisfy the template's input schema."""

    status = 422
    code = "invalid_workflow_input"


class InvalidDecisionError(MultiAgentError):
    """A decision is well formed but inconsistent with the run (e.g. unknown step IDs)."""

    status = 422
    code = "invalid_decision"


class TemplateNotFoundError(MultiAgentError):
    """No registered template has the requested identifier."""

    status = 404
    code = "template_not_found"


class RunNotFoundError(MultiAgentError):
    """No persisted run has the requested identifier."""

    status = 404
    code = "run_not_found"


class InvalidTransitionError(MultiAgentError):
    """A state transition is not permitted from the run's current state."""

    status = 409
    code = "invalid_state_transition"

    def __init__(self, current: str, target: str, detail: str | None = None) -> None:
        super().__init__(detail or f"Workflow run cannot move from {current} to {target}")
        self.current = current
        self.target = target


class ConcurrentUpdateError(MultiAgentError):
    """The persisted run changed after it was read."""

    status = 409
    code = "run_concurrently_updated"


class CapacityExceededError(MultiAgentError):
    """The bounded background executor has no free capacity."""

    status = 503
    code = "workflow_capacity_exceeded"


class StoreUnavailableError(MultiAgentError):
    """The workflow state store could not be read or written."""

    status = 503
    code = "state_store_unavailable"


class TemplateValidationError(ValueError):
    """A workflow manifest is malformed or references unavailable tools."""

    def __init__(self, path: str, issues: list[str]) -> None:
        super().__init__(f"{path}: " + "; ".join(issues))
        self.path = path
        self.issues = issues


class AgentStageError(Exception):
    """An agent could not produce valid output and no fallback was allowed."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class RunCancelledSignal(Exception):  # noqa: N818 - control-flow signal, not a failure
    """Raised inside a background stage when the run was cancelled concurrently."""
