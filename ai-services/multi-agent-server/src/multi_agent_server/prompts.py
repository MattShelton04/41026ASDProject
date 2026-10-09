"""Versioned Planner, Worker and Reviewer prompts with reproducible content hashes."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

PROMPT_ROOT = Path(__file__).resolve().parent / "prompt_assets"
AgentPromptRole = Literal["planner", "worker", "reviewer"]
CURRENT_PROMPT_VERSIONS: dict[AgentPromptRole, str] = {
    "planner": "v1",
    "worker": "v1",
    "reviewer": "v1",
}


class PromptError(ValueError):
    """A prompt asset is missing, malformed or inconsistent with its key."""


class _PromptMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    version: str = Field(pattern=r"^v[0-9]+$")
    role: AgentPromptRole
    template: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    description: str = Field(min_length=1, max_length=500)


@dataclass(frozen=True, slots=True)
class AgentPrompt:
    """One loaded prompt: identity, system text and content hash."""

    prompt_id: str
    version: str
    role: AgentPromptRole
    content: str
    content_hash: str


class PromptRegistry:
    """Load only the fixed prompt identities this package ships."""

    def __init__(self, root: Path = PROMPT_ROOT) -> None:
        self._root = root.resolve()
        self._cache: dict[tuple[str, str], AgentPrompt] = {}

    def current(self, role: AgentPromptRole) -> AgentPrompt:
        """Load the current version of a role's prompt."""
        return self.load(role, CURRENT_PROMPT_VERSIONS[role])

    def load(self, role: AgentPromptRole, version: str) -> AgentPrompt:
        """Load and validate one prompt asset pair (``<version>.meta.yaml`` + template)."""
        key = (role, version)
        if key in self._cache:
            return self._cache[key]
        directory = self._root / role
        meta_path = directory / f"{version}.meta.yaml"
        try:
            metadata = _PromptMetadata.model_validate(
                yaml.safe_load(meta_path.read_text(encoding="utf-8"))
            )
        except (OSError, yaml.YAMLError, ValueError) as exc:
            raise PromptError(f"could not load prompt {role}/{version}") from exc
        if metadata.prompt_id != role or metadata.version != version or metadata.role != role:
            raise PromptError("prompt metadata does not match its registry key")
        template_path = (directory / metadata.template).resolve()
        if template_path.parent != directory.resolve():
            raise PromptError("prompt template escapes its directory")
        try:
            content = template_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise PromptError(f"could not load prompt template {role}/{version}") from exc
        if not content:
            raise PromptError("prompt template cannot be empty")
        content_hash = hashlib.sha256(
            meta_path.read_bytes() + b"\0" + template_path.read_bytes()
        ).hexdigest()
        prompt = AgentPrompt(role, version, role, content, content_hash)
        self._cache[key] = prompt
        return prompt
