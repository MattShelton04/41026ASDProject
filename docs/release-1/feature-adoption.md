# Release 1 feature adoption

Shared supplies the host MCP/RAG runtime, typed evidence, bounded agent loop and source UI. Each
feature owner supplies its own approved tools, corpus content, backend boundary and evidence.
This recipe extends the [existing client adoption contract](../release-0/feature-client-adoption.md)
and [manifest onboarding](../release-0/feature-onboarding.md); it does not grant access to another
feature's code, database or unpublished material. Feature 1 is the integrated reference.

## 1. Retain the owning backend boundary

The frontend calls its feature backend. That backend creates and reads AI-mode runs over HTTP,
validates feature/context ownership and returns structured results. AI-mode calls only registered
owning tools, through MCP in combined mode. Backends never import AI-mode/agent-core or connect
directly to the RAG index. Use `shared_contracts` for wire types and test-only `shared_testkit`.
The managed host AI-mode listener requires `X-PropertyScope-AI-Token`; the feature's HTTP client
reads `AI_MODE_SERVICE_TOKEN` from its backend environment. The shared launcher injects that token
into enabled containers. Never pass it to frontend JavaScript or model requests. Keep `/health/live`
distinct from authenticated readiness/run/history routes; use the supported client for those reads.

Feature 1's concrete reference is `/api/data-platform/v1/assistant/turns` with read/events/cancel
subroutes. The shared and standalone assistants both use that backend. Inspect its route ownership
tests as well as its browser wrapper before copying a pattern. The shared status route's generic
capabilities endpoint is an operational observation, not a feature assistant request path.

## 2. Register a bounded tool catalogue

Keep tool name/version, JSON Schema inputs/outputs, side-effect class, timeout, service and path
in the feature's `tool-catalog.yaml`. Enablement and catalogue path come from its existing
`feature.yaml` and root deployment selection. The host launcher projects fixed service origins to
published loopback frontend/API ports; MCP preserves tool definitions and owning paths. Do not put
tokens or model-selected URLs in catalogues. New routes need owning feature tests and generated
deployment drift checks.

Use read-only tools initially. A tool returning no records should report valid empty evidence,
not invent records or conflate absence with a transport fault. Any future write needs atomic
idempotency and server-side approval where classified; MCP does not supply those business rules.
Feature 1's assistant remains read-only even though other explicitly approved workflows exist.

## 3. Own the guidance corpus

Start from agreed feature requirements and current implementation. Author a small reviewed set of
public guidance with stable document IDs, titles, source dates, licences, evidence kind and safe
HTTP(S) display references. The [Feature 1 manifest](../../student-1/config/rag/corpus.json) and
[source recipe](../../student-1/config/rag/README.md) are the concrete examples. Current database
facts belong in owning tools. Private case notes and official publisher ingestion need separate
scope/permission decisions and are not supported by this public-guidance adapter.

Register the exact `feature-key:corpus-id` pair in both `RAG_ALLOWED_CORPORA` and
`AI_MODE_RAG_CORPORA`, retaining existing approved pairs. Each is a comma-separated list. RAG
checks its allowlist before ingest/search. AI-mode chooses the registered corpus for each feature,
adds `context.retrieve.v1` to its run allowlist and uses `default.v8`. Supplying a different corpus
in a request fails closed. Shared does not infer a corpus from a browser label or retrieved text.

Run managed host services in combined mode, then explicitly ingest the complete owner manifest
with the managed `RAG_SERVICE_TOKEN` in the shell environment:

```text
uv run rag-server ingest student-N/config/rag/corpus.json
```

The `student-N` path above is a recipe placeholder to replace with the owning slice. Ingestion
does not fetch document URLs. Model preparation is explicit, reingestion is a complete replacement,
and omitted documents are withdrawn. Preserve failed-refresh evidence and version history.

## 4. Accept grounded runs without weakening ownership

Keep feature-key, run-purpose and context checks. If the backend validates an exact historical
tool-allowlist tuple before allowing a run to be read, add only its own approved tuple plus
`context.retrieve.v1` as the grounded variant. Do not replace exact ownership validation with
an unrestricted shared-run read. Feature 1's regression tests cover the legacy and grounded
variants and reject foreign/mutating variants.

Persisted old runs default to no grounding. New eligible runs retrieve in every plan and return
`GroundedAnswer` findings, confidence/reason, gaps, next step and safety boundary. The server adds
recorded `EvidenceCitation` objects, grounding status and corpus version. Guidance findings cite
retrieved IDs; tool facts cite successful call IDs. These references never authorize a mutation.

## 5. Adopt the shared presentation

Import `createFeatureAssistant`/`createAiChat` from the public `ai-chat/index.js` barrel with
feature-owned scope/context vocabulary and backend API root. Include documented shared styles.
The grounded renderer handles sources, safe links, confidence, empty/unavailable context, native
disclosures and legacy answers. Avoid rendering model HTML or treating a retrieved document as
an instruction. A healthy service does not prove that your feature has context for a question.

## 6. Supply owner evidence

| Check | Evidence to retain |
|---|---|
| Source ownership | Corpus manifest, licence scope, reviewed guidance and registered tool schemas |
| Deterministic contracts | Tool schema tests; corpus bounds/replay/withdrawal; feature run ownership; no credentials/internet |
| Grounding negatives | Forged/out-of-scope support rejection, absent facts, irrelevant/stale context, injection and outage |
| Browser | Actual owning UI → backend → local MCP/RAG answer, inspected citations/confidence, insufficient context and ordinary CRUD |
| Local integration | Protocol discovery/call, ingest/replay, restart/outage behavior and exact model/prompt/corpus identities |
| Workflow | Successful assigned workflow link/log with MCP/RAG explicitly disabled |
| Submission | Owner commits, contribution log, report/video segment and explanation of limitations |

Run the canonical `uv run python scripts/check.py` and the feature's existing required browser
tests. CI keeps `AI_MODE_MCP_ENABLED=false` and `AI_MODE_RAG_ENABLED=false`; do not launch local
servers or download embedding weights there. Local `ai validate mcp`/`rag` currently validate the
Feature 1 reference path with deterministic model decisions; they do not claim another feature's
integration. Add owner-specific live evidence and reuse the same public contracts without editing
another student's implementation. Release 2 roles should reuse these run/review/tool boundaries.
