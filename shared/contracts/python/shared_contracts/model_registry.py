"""Public, provider-neutral descriptions of supported model profiles."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from shared_contracts.agent import Identifier
from shared_contracts.base import ContractModel


class ModelProviderName(StrEnum):
    """Remote model providers supported by the current AI-mode composition."""

    OPENAI = "openai"


class ModelReasoningEffort(StrEnum):
    """Portable configured reasoning effort for reasoning-capable models."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"
    MAX = "max"


class ModelRoleName(StrEnum):
    """Agent roles for which a runtime profile is intended."""

    PLANNER = "planner"
    ADAPTER = "adapter"
    REVIEWER = "reviewer"


class SupportedModel(ContractModel):
    """One concrete API model with traceable capacity metadata."""

    key: Identifier
    provider: ModelProviderName
    model_id: str = Field(
        min_length=1,
        max_length=200,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$",
    )
    maximum_context_tokens: int = Field(ge=1_024, le=2_000_000)
    maximum_output_tokens: int = Field(ge=1, le=1_000_000)
    source_url: str = Field(pattern=r"^https://")
    description: str = Field(min_length=1, max_length=500)


class ModelProfile(ContractModel):
    """Stable logical name with role-routed models and bounded operational settings."""

    key: Identifier
    role_models: dict[ModelRoleName, Identifier] = Field(min_length=1, max_length=3)
    context_tokens: int = Field(ge=1_024, le=2_000_000)
    maximum_output_tokens: int = Field(ge=1, le=32_768)
    reasoning_effort: ModelReasoningEffort
    description: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def output_fits_context(self) -> ModelProfile:
        """Reserve at least one token of the configured context for input."""
        if self.maximum_output_tokens >= self.context_tokens:
            raise ValueError("maximum output tokens must be smaller than context tokens")
        return self

    def supports(self, *roles: ModelRoleName) -> bool:
        """Return whether every requested runtime role is declared by this profile."""
        return set(roles).issubset(self.role_models)


class ModelRegistry(ContractModel):
    """Versioned catalogue returned by AI-mode and loaded at composition time."""

    schema_version: Literal[2]
    default_profile: Identifier
    models: tuple[SupportedModel, ...] = Field(min_length=1, max_length=100)
    profiles: tuple[ModelProfile, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def references_are_consistent(self) -> ModelRegistry:
        """Reject duplicate keys, dangling references, and unsafe capacity budgets."""
        models = {model.key: model for model in self.models}
        profiles = {profile.key: profile for profile in self.profiles}
        if len(models) != len(self.models):
            raise ValueError("model keys must be unique")
        if len(profiles) != len(self.profiles):
            raise ValueError("model profile keys must be unique")
        if self.default_profile not in profiles:
            raise ValueError("default model profile is not defined")
        for profile in self.profiles:
            for role, model_key in profile.role_models.items():
                model = models.get(model_key)
                if model is None:
                    raise ValueError(
                        f"model profile {profile.key} role {role} references an unknown model"
                    )
                if profile.context_tokens > model.maximum_context_tokens:
                    raise ValueError(
                        f"model profile {profile.key} exceeds the model context window"
                    )
                if profile.maximum_output_tokens > model.maximum_output_tokens:
                    raise ValueError(
                        f"model profile {profile.key} exceeds the model output maximum"
                    )
        return self

    def profile(self, key: str) -> ModelProfile | None:
        """Look up a profile without exposing the document's storage shape."""
        return next((profile for profile in self.profiles if profile.key == key), None)

    def model(self, key: str) -> SupportedModel | None:
        """Look up a concrete model without exposing the document's storage shape."""
        return next((model for model in self.models if model.key == key), None)
