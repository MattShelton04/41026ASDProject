# Architecture

Architecture sources, decisions, and exported diagrams belong here.

- `repository-architecture.md` records the initial scaffold plan, repository
  architecture, AI-assisted engineering process, decisions, and validation.
- `shared-platform-design.md` defines the proposed shared-service, agentic-harness,
  contract, testing, caching, portability, and Azure architecture for Releases 0-2.
- `agent-run-state-machine.md` is the implemented operational specification for run
  transitions, durable phase checkpoints, tool turns, idempotency, and restart recovery.
- `decisions/ADR-014-append-only-safe-agent-run-events.md` records the resumable event
  persistence and cursor-polling decision.
- `reviews/` retains external/adversarial review inputs. Findings are not
  authoritative until verified and dispositioned in the architecture record.
- Future artefacts should cover individual microservices, the integrated application,
  and Docker Compose.
- Release 1 should add MCP, RAG, retrieval, and grounded-response architecture.
- Release 2 should add multi-agent, DevOps pipeline, and cloud-deployment
  architecture.

Keep editable diagram sources alongside exported images or PDFs so the
architecture can be updated throughout the project.
