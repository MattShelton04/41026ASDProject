"""AI runtime identities shared by launchers and packaged container entrypoints.

Host ports are configurable; container listeners use these fixed defaults. This module
must remain independent of generated deployment files and host-only dependencies.
"""

AI_SERVICE_PORTS = {
    "ai-mode": ("AI_MODE_PORT", 5005),
    "mcp": ("MCP_PORT", 5011),
    "rag": ("RAG_PORT", 5012),
}
AI_CONTAINER_SERVICES = {
    "ai-mode": "shared-ai-mode",
    "mcp": "mcp-server",
    "rag": "rag-server",
}
AI_PLACEMENTS = ("host", "docker")
AI_CAPABILITY_MODES = ("direct", "mcp", "rag", "combined")
# Default subject of the named loop validations; any enabled feature key is accepted.
RELEASE_1_REFERENCE_FEATURE = "student-1-propertyscope-data-platform"


def validate_capability_mode(mode: str) -> None:
    """Reject unknown modes before creating files or changing service ownership."""
    if mode not in AI_CAPABILITY_MODES:
        raise RuntimeError("Invalid AI capability mode; use direct, mcp, rag or combined")
