"""Typed failures raised by deterministic agent-core policies."""


class AgentCoreError(Exception):
    """Base class for expected orchestration failures."""


class InvalidStateTransitionError(AgentCoreError):
    """A requested run transition is not in the explicit transition graph."""


class RunLimitExceededError(AgentCoreError):
    """A deterministic run limit has been reached."""


class RunStalledError(AgentCoreError):
    """A run attempted to repeat a completed plan without new evidence."""


class ToolRegistrationError(AgentCoreError):
    """A tool definition is duplicate or contains an invalid schema."""


class UnknownToolError(AgentCoreError):
    """A plan references a tool that is not allowlisted."""


class ToolSchemaValidationError(AgentCoreError):
    """Tool input or output does not satisfy its declared JSON Schema."""


class ToolPolicyError(AgentCoreError):
    """A tool call violates a deterministic authorization policy."""


class ConcurrentRunUpdateError(AgentCoreError):
    """Persisted run state changed since it was loaded."""


class ModelProviderError(AgentCoreError):
    """A model provider failed without exposing implementation details."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        retryable: bool,
        provider_request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.provider_request_id = provider_request_id


class ModelOutputValidationError(AgentCoreError):
    """A provider response did not match its requested structured schema."""
