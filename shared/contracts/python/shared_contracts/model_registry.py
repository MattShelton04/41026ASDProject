"""Public, provider-neutral descriptions of supported local model profiles."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from shared_contracts.agent import Identifier
from shared_contracts.base import ContractModel


class ApprovedModelFamily(StrEnum):
    """Open model families permitted by the assignment specification."""

    QWEN = "qwen"
    LLAMA = "llama"
    DEEPSEEK = "deepseek"


class ModelRoleName(StrEnum):
    """Agent roles for which a runtime profile is intended."""

    PLANNER = "planner"
    ADAPTER = "adapter"
    REVIEWER = "reviewer"


class SupportedModel(ContractModel):
    """One concrete Ollama model with traceable capacity metadata."""

    key: Identifier
    family: ApprovedModelFamily
    provider: Literal["ollama"] = "ollama"
    ollama_tag: str = Field(min_length=1, max_length=200)
    parameters_billion: float = Field(gt=0, le=1_000)
    download_size_gb: float = Field(gt=0, le=1_000)
    maximum_context_tokens: int = Field(ge=1_024, le=2_000_000)
    source_url: str = Field(pattern=r"^https://(www\.)?(registry\.)?ollama\.com/")
    description: str = Field(min_length=1, max_length=500)


class ModelProfile(ContractModel):
    """Stable logical name and bounded operational settings for one model."""

    key: Identifier
    model_key: Identifier
    context_tokens: int = Field(ge=1_024, le=2_000_000)
    maximum_output_tokens: int = Field(ge=1, le=32_768)
    keep_alive: str = Field(min_length=1, max_length=50)
    intended_roles: tuple[ModelRoleName, ...] = Field(min_length=1, max_length=3)
    description: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def output_fits_context(self) -> ModelProfile:
        """Reserve at least one token of the configured context for input."""
        if self.maximum_output_tokens >= self.context_tokens:
            raise ValueError("maximum output tokens must be smaller than context tokens")
        if len(set(self.intended_roles)) != len(self.intended_roles):
            raise ValueError("intended roles must be unique")
        return self


class ModelRegistry(ContractModel):
    """Versioned catalogue returned by AI-mode and loaded at composition time."""

    schema_version: Literal[1]
    default_profile: Identifier
    models: tuple[SupportedModel, ...] = Field(min_length=1, max_length=100)
    profiles: tuple[ModelProfile, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def references_are_consistent(self) -> ModelRegistry:
        """Reject duplicate keys, dangling references, and unsafe context budgets."""
        models = {model.key: model for model in self.models}
        profiles = {profile.key: profile for profile in self.profiles}
        if len(models) != len(self.models):
            raise ValueError("model keys must be unique")
        if len(profiles) != len(self.profiles):
            raise ValueError("model profile keys must be unique")
        if self.default_profile not in profiles:
            raise ValueError("default model profile is not defined")
        for profile in self.profiles:
            model = models.get(profile.model_key)
            if model is None:
                raise ValueError(f"model profile {profile.key} references an unknown model")
            if profile.context_tokens > model.maximum_context_tokens:
                raise ValueError(f"model profile {profile.key} exceeds the model context window")
        return self

    def profile(self, key: str) -> ModelProfile | None:
        """Look up a profile without exposing the document's storage shape."""
        return next((profile for profile in self.profiles if profile.key == key), None)

    def model(self, key: str) -> SupportedModel | None:
        """Look up a concrete model without exposing the document's storage shape."""
        return next((model for model in self.models if model.key == key), None)
