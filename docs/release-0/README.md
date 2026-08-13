# Release 0

Release 0 establishes the integrated frontend, backend/API, and database
microservices; AI mode with Ollama and an approved LLM; the shared
Plan -> Act -> Observe -> Adapt loop; Docker Compose; student CI; local testing;
and the first report and showcase evidence.

See [`ollama-operations.md`](ollama-operations.md) for the canonical Docker Desktop /
Compose runtime, native developer alternative, routing, smoke test, and troubleshooting.
Student owners should use [`feature-onboarding.md`](feature-onboarding.md) after their
topic and feature allocation are approved; it records integration and testing
obligations without inventing domain behavior.

The PropertyScope data-platform/property-discovery slice is chunked into
schemas, APIs, ingestion/release contracts, AI tools, tests, milestones, and evidence in
[`propertyscope-feature-1-implementation-plan.md`](propertyscope-feature-1-implementation-plan.md).
Implementation is authorised on this branch; the formal tutor/team approval evidence for its
Feature 1-only PostgreSQL/PostGIS exception remains a release gate.

The implemented, opt-in local showcase/debug interface and its remaining remote-access
decisions are specified in
[`ai-mode-operations-interface-plan.md`](ai-mode-operations-interface-plan.md). It turns
AI-mode's persisted run snapshots and cursor events into a bounded live operations view
without introducing a second workflow store or a mandatory monitoring stack.
