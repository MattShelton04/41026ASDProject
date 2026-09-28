# Local MCP server

This shared local service exposes enabled feature catalogues through the official
Python MCP SDK (`mcp>=1.28,<2`, exact resolution in `uv.lock`). The upstream v1 line continues
to receive security fixes: [official SDK compatibility policy](https://github.com/modelcontextprotocol/python-sdk).
Its stateless Streamable HTTP endpoint is `/mcp`; all requests, including `/health`, require
`Authorization: Bearer <MCP_SERVICE_TOKEN>`. The configured secret must contain at least 32
characters and must never appear in a catalogue, prompt, generated evidence or Git.

The supported lifecycle is the shared `scripts/dev.py` local stack workflow. For foreground
diagnosis, configure `MCP_SERVICE_TOKEN`, `MCP_TOOL_CATALOG_PATHS` (comma-separated validated
host catalogue paths), optional `MCP_PORT` (5011), then run `uv run python -m mcp_server`.
`MCP_HOST` defaults to `127.0.0.1` and only accepts loopback addresses. Host projections map
feature service origins to published loopback API routes. MCP runs only as a host process and
never in a container ([ADR-046](../../docs/architecture/decisions/ADR-046-non-containerised-ai-tier.md)).
CI and cloud runtime keep MCP disabled. `uv run scripts/dev.py ai probe` checks the running server
from a terminal; see the [runtime guide](../../docs/release-1/host-runtime.md).

Protocol discovery exposes original input/output schemas and side-effect annotations.
The `propertyscope://tools/catalog` resource exposes public tool definitions only, without
service origins or feature records. A call requires a short-lived HMAC capability in MCP
`_meta["propertyscope/invocation"]`; the capability binds feature/run/step/call identity, exact
arguments, tool/version, approval, idempotency and deadline. Missing, modified, expired or
wrong-feature context is rejected before dispatch. Authentication is service-to-service;
an external MCP client cannot mint approved actions independently of the trusted orchestrator.

The server reapplies input schema and approval policy. External effects remain disabled;
writes require idempotency and destructive/protected actions require approval. Accepted
mutations consume the call identity before dispatch, preventing concurrent/repeated dispatch
within the signed deadline. A restart clears the transient replay cache; the owning backend's
durable idempotency/review checks remain authoritative across restart and lost responses.
Neither MCP nor its client automatically retries mutations or falls back to direct HTTP.

Successful `structuredContent` matches the original registered output schema. Protocol
`_meta["propertyscope/tool-result"]` carries the original call ID, outcome, errors, timing and
evidence references. AI-mode reconstructs and validates the complete `ToolResult`; mismatched
correlation or malformed output fails safely. Tool calls never access student databases.

`uv run pytest ai-services/mcp-server/tests shared/tool-runtime/tests` exercises real SDK
negotiation, discovery, resources and calls through in-process memory/ASGI transports, without
network, credentials, Docker or a live MCP service. Explicit local release validation exercises
the host HTTP transport and integrated feature environment separately.
