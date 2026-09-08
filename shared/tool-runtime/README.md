# Shared tool runtime

`shared-tool-runtime` owns domain-neutral catalogue parsing/composition, immutable HTTP
bindings, bounded HTTP dispatch and signed MCP invocation metadata. It imports shared
contracts and transport libraries; it never imports `agent_core`, AI-mode or a feature.
AI-mode retains `ToolRegistry` and policy composition in its compatibility facade.

`load_tool_catalogs(paths)` rejects duplicate service/tool identities. `build_http_executor`
allows only startup-defined origins and paths, rejects redirects, propagates run/request/trace
and idempotency headers, bounds request/response bytes and validates registered output schemas.
It does not discover model-supplied URLs or own feature persistence/business rules.
Redirect rejection is applied per invocation, including injected clients. Malformed compressed
responses return a safe typed encoding failure; they do not escape as upstream decoder exceptions.

`sign_invocation` is called only by the orchestrator adapter after deterministic authorization.
Its HMAC binds the feature, complete call identity, tool version, argument digest, approval,
idempotency key and deadline. Model arguments contain no authentication fields. The MCP server
verifies the signature and repeats schema/scope/approval validation before HTTP dispatch.

Run deterministic tests with `uv run pytest shared/tool-runtime/tests` and the existing
AI-mode catalogue/HTTP tests, which also verify the compatibility imports.
