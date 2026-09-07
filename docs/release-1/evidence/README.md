# Release 1 captured public outputs

Captured on 7 September 2026 from the local Shared/Feature 1 implementation. The surrounding
[handoff](../shared-feature-1-handoff.md) owns rubric traceability and limitations.

- `validation-mcp.json` and `validation-rag.json`: production four-phase runner with real local
  transport, temporary validation run store and deterministic `extractive-validation.v1` model
  decisions. These are protocol/orchestration evidence, not actual model answers.
- `live-feature1-provider-summary.json`: actual OpenAI-backed Feature 1 assistant result for
  partial PSI publication guidance, with public citation metadata and model/prompt/token metrics.
- `live-feature1-insufficient-summary.json`: actual unrelated-recipe refusal; the user's probe
  explicitly requested insufficient context when project sources could not support the topic.
- `live-feature1-rag-outage-summary.json`: actual stopped-RAG insufficiency with a retained owning
  tool fact, MCP readiness and ordinary source-read HTTP 200; captured before final auth hardening.
- `local-integration-checks.json`: actual host restart persistence, expected MCP outage failure
  and synthetic source CRUD with cleanup. An expected `passed=false` outage is labelled explicitly.

Live summaries are allowlisted projections of the original public run records; they exclude full
objectives, rendered prompts and step payloads. Token counts, hashes and provider request IDs are
diagnostic metadata, not private reasoning traces. Source excerpts are the repository-authored
CC0 guidance with its original attribution, identity and version. No secrets, database files,
weights or raw logs belong here.

The local file called `validation-rag-insufficient.json` returned ready/moderate because the
extractive provider copied unrelated ranked guidance. It is deliberately not included as a
successful insufficient-context artifact. See the retrieval evaluation's negative findings.

To regenerate the two named transport artifacts, use `ai validate mcp --output <path>` and
`ai validate rag --output <path>` after explicit model preparation/corpus ingestion. Regenerated
identities and timings will differ. Retain model-based evidence separately and never relabel
fixture or deterministic validation as an actual provider interaction.

- [Final authenticated integration](final-authenticated-integration.json) records the secured host boundary and two fresh actual provider runs. [Live screenshot](live-grounded-answer.png) is a real provider answer, with its fixed composer visible in the full-page capture.
