"""AI-mode registry composition over neutral feature tool catalogues."""

from shared_tool_runtime import (
    HttpToolExecutor,
    build_http_executor,
)
from shared_tool_runtime import (
    ServiceEndpoint as ServiceEndpoint,
)
from shared_tool_runtime import (
    ToolCatalog as ToolCatalog,
)
from shared_tool_runtime import (
    ToolCatalogError as ToolCatalogError,
)
from shared_tool_runtime import (
    ToolRegistration as ToolRegistration,
)
from shared_tool_runtime import (
    compose_tool_catalogs as compose_tool_catalogs,
)
from shared_tool_runtime import (
    load_tool_catalog as load_tool_catalog,
)
from shared_tool_runtime import (
    load_tool_catalogs as load_tool_catalogs,
)

from agent_core import ToolRegistrationError, ToolRegistry


def build_tool_runtime(
    catalog: ToolCatalog,
    *,
    max_request_bytes: int,
    max_response_bytes: int,
) -> tuple[ToolRegistry, HttpToolExecutor]:
    """Compose the registry and transport adapter from one validated source."""
    try:
        registry = ToolRegistry(
            (registration.definition for registration in catalog.tools),
            shared_tools=catalog.shared_tools,
        )
        executor = build_http_executor(
            catalog,
            max_request_bytes=max_request_bytes,
            max_response_bytes=max_response_bytes,
        )
    except (ToolRegistrationError, ValueError) as exc:
        raise ToolCatalogError(f"tool runtime composition failed: {exc}") from exc
    return registry, executor
