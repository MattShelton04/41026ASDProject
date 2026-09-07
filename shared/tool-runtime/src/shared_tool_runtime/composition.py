"""Transport-only composition without an orchestration dependency."""

from .catalog import ToolCatalog, ToolCatalogError
from .http import (
    DEFAULT_MAX_TOOL_REQUEST_BYTES,
    DEFAULT_MAX_TOOL_RESPONSE_BYTES,
    HttpToolBinding,
    HttpToolExecutor,
)


def build_http_executor(
    catalog: ToolCatalog,
    *,
    max_request_bytes: int = DEFAULT_MAX_TOOL_REQUEST_BYTES,
    max_response_bytes: int = DEFAULT_MAX_TOOL_RESPONSE_BYTES,
) -> HttpToolExecutor:
    """Bind feature-owned metadata to a bounded HTTP executor at startup."""
    try:
        return HttpToolExecutor(
            service_base_urls={
                endpoint.service: str(endpoint.base_url).rstrip("/")
                for endpoint in catalog.services
            },
            bindings=(
                HttpToolBinding(
                    tool_name=registration.definition.name,
                    tool_version=registration.definition.version,
                    service=registration.service,
                    method=registration.method,
                    path=registration.path,
                )
                for registration in catalog.tools
            ),
            max_request_bytes=max_request_bytes,
            max_response_bytes=max_response_bytes,
        )
    except ValueError as exc:
        raise ToolCatalogError(f"tool runtime composition failed: {exc}") from exc
