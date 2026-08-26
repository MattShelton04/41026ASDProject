"""Validated assistant-turn context and bounded product guidance."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ASSISTANT_FEATURE_KEY = "student-1-propertyscope-data-platform"
AssistantScope = Literal["application", "feature"]


class AssistantContext(BaseModel):
    """Explicit page evidence copied into one independent assistant turn."""

    model_config = ConfigDict(extra="forbid")

    route: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"^[a-z0-9/_-]+$")
    release_id: UUID | None = None
    ingestion_run_id: UUID | None = None
    property_ref: UUID | None = None


class AssistantTurnRequest(BaseModel):
    """Public chat request; conversation history is deliberately not implicit."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=2, max_length=2_000)
    scope: AssistantScope = "feature"
    context: AssistantContext = Field(default_factory=AssistantContext)


def capability_guide() -> dict[str, object]:
    """Return the small, versioned source of truth used by UI and model tooling."""
    return {
        "revision": "2026-08-26.v1",
        "application": {
            "name": "PropertyScope NSW",
            "summary": (
                "A property research workspace that keeps source coverage, uncertainty, "
                "dataset operations and recorded AI activity visible."
            ),
            "routes": [
                {"label": "Home", "href": "/#home"},
                {"label": "Research areas", "href": "/#features"},
                {"label": "Data status", "href": "/#system-status"},
                {"label": "Sources and history", "href": "/#evidence"},
                {"label": "AI activity", "href": "/operations/ai-mode/"},
            ],
        },
        "assistant": {
            "turn_model": "Each submitted message creates one durable AI-mode AgentRun.",
            "memory": "The visible transcript is local to this browser view; follow-up context must be explicit.",
            "evidence": "Answers can use only recorded allowlisted HTTP tool results and this guide.",
            "limitations": [
                "It is research support, not professional advice.",
                "It does not have arbitrary repository, filesystem, database or shell access.",
                "Protected data actions remain separate human-reviewed operations.",
                "Only Property data is implemented; other research areas are visibly planned.",
            ],
        },
        "features": [
            {
                "feature_key": ASSISTANT_FEATURE_KEY,
                "label": "Property data",
                "status": "available",
                "href": "/features/data-platform/#properties",
                "capabilities": [
                    "Explain PropertyScope and the website",
                    "Describe registered datasets and sources",
                    "Search accepted NSW property address evidence",
                    "Inspect an exact property, update run or dataset release",
                    "Compare candidate and accepted dataset releases",
                    "Explain coverage and quality evidence",
                ],
            },
            {"feature_key": "feature-2", "label": "Market intelligence", "status": "planned"},
            {"feature_key": "feature-3", "label": "Suburb context", "status": "planned"},
            {"feature_key": "feature-4", "label": "Due diligence", "status": "planned"},
            {"feature_key": "feature-5", "label": "Buyer workspace", "status": "planned"},
        ],
        "suggested_questions": [
            "What can PropertyScope help me research?",
            "Which datasets and sources are available?",
            "How does AI activity stay reviewable?",
            "Find an accepted property record in Parramatta.",
        ],
    }


def build_assistant_objective(command: AssistantTurnRequest) -> str:
    """Project validated user intent and exact identifiers into a bounded objective."""
    context = command.context.model_dump(mode="json", exclude_none=True)
    context_lines = "\n".join(f"- {name}: {value}" for name, value in context.items())
    if not context_lines:
        context_lines = "- No page entity was supplied. Ask for clarification rather than guessing an ID."
    scope_text = (
        "the PropertyScope application and its currently implemented Property data area"
        if command.scope == "application"
        else "the Property data research area"
    )
    return (
        "Conversational assistant turn. This is separate from the fixed-objective Data review flow.\n"
        f"Scope: {scope_text}.\n"
        f"User question: {command.message.strip()}\n"
        "Validated page context (copy identifiers exactly; never invent or substitute one):\n"
        f"{context_lines}\n"
        "Answer the user directly in plain Australian English. Use the minimum read-only tools needed. "
        "For questions about capabilities, the website or limitations, call platform.capabilities.v1. "
        "Distinguish accepted data from candidates and missing evidence from a passing result. "
        "Return a concise summary, findings, evidence references and a useful next step. "
        "Do not propose or call a write tool in this conversational turn."
    )
