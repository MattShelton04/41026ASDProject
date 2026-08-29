# Release 0

Features 2–5 should start with the independent data-client and Shared assistant recipe in
[`feature-client-adoption.md`](feature-client-adoption.md).

Release 0 establishes the integrated frontend, backend/API, and database
microservices; AI mode with a remote OpenAI model; the shared
Plan -> Act -> Observe -> Adapt loop; Docker Compose; student CI; local testing;
and the first report and showcase evidence.

The currently integrated shared/Feature 1 baseline includes:

- the product-facing shared home, mobile navigation and address hand-off;
- live shared system status with separate API, store and remote-provider readiness;
- bounded accepted-data and durable agent-run evidence references;
- an explicit implemented/enabled/planned capability roadmap;
- complete Property records exploration and data-operations routes; and
- durable failed-candidate diagnosis, human review and accepted-predecessor preservation.

These shared views consume only public HTTP projections. Features 2–5 remain honest planned
capabilities until their independently owned frontends, backends and stores are integrated.

See [`openai-api-operations.md`](openai-api-operations.md) for remote-provider configuration,
secret handling, the live smoke test, and troubleshooting.
See [`readiness-assessment-2026-08-27.md`](readiness-assessment-2026-08-27.md) for the current
criterion-by-criterion Shared/Feature 1 readiness verdict and the remaining group submission gates.
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

Before capturing submission evidence, run:

```text
uv run python scripts/check.py
node --test student-1/tests/frontend/*.test.mjs shared/frontend/*.test.mjs shared/frontend/operations/ai-mode/*.test.mjs
docker compose --file docker-compose.yml --file docker-compose.dev.yml --profile release-0 config --quiet
```
