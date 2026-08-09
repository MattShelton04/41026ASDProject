# Architecture

Architecture sources, decisions, and exported diagrams belong here.

- `repository-architecture.md` is the historical initial-scaffold record. Its point-in-time
  status is evidence, not the current implementation summary.
- `shared-platform-design.md` is the living shared-service, agentic-harness, contract,
  testing, caching, portability, and deployment architecture for Releases 0-2.
- `propertyscope-product-and-feature-plan.md` is the proposed PropertyScope NSW product,
  five-feature, data, UI, API, AI, and delivery plan. It remains subject to team and tutor
  approval and does not supersede the domain-neutral shared-platform decisions.
- `agent-run-state-machine.md` is the implemented operational specification for run
  transitions, durable phase checkpoints, tool turns, idempotency, and restart recovery.
- `shared-run-observability-proposal.md` records the implemented local read-only baseline
  and the remaining remote observability proposal. Its concrete Release 0 delivery plan is
  [`../release-0/ai-mode-operations-interface-plan.md`](../release-0/ai-mode-operations-interface-plan.md).
- `decisions/ADR-014-append-only-safe-agent-run-events.md` records the resumable event
  persistence and cursor-polling decision.
- `decisions/ADR-015-validated-model-registry.md` records supported-model metadata,
  logical profiles, operational limits, and readiness selection.
- `decisions/ADR-016-propertyscope-feature-1-postgresql-postgis.md` proposes a
  Feature 1-only PostgreSQL/PostGIS exception for PropertyScope's verified statewide
  data scale. It does not change the shared SQLite baseline until tutor/team approval.
- `reviews/` retains external/adversarial review inputs. Findings are not
  authoritative until verified and dispositioned in the architecture record.
- Future artefacts should cover individual microservices, the integrated application,
  and Docker Compose.
- Release 1 should add MCP, RAG, retrieval, and grounded-response architecture.
- Release 2 should add multi-agent, DevOps pipeline, and cloud-deployment
  architecture.

Keep editable diagram sources alongside exported images or PDFs so the
architecture can be updated throughout the project.
