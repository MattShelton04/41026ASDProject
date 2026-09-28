"""Host AI service identities shared by the launcher and the managed host runtime.

AI-mode, MCP and RAG run only as host processes (ADR-043, ADR-046); Compose never defines
them. This module must remain independent of generated deployment files.
"""

AI_SERVICE_PORTS = {
    "ai-mode": ("AI_MODE_PORT", 5005),
    "mcp": ("MCP_PORT", 5011),
    "rag": ("RAG_PORT", 5012),
}
AI_CAPABILITY_MODES = ("direct", "mcp", "rag", "combined")


def validate_capability_mode(mode: str) -> None:
    """Reject unknown modes before creating files or changing service ownership."""
    if mode not in AI_CAPABILITY_MODES:
        raise RuntimeError("Invalid AI capability mode; use direct, mcp, rag or combined")
