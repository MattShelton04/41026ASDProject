# Architecture

This directory contains living architecture, durable decisions, proposals, and dated review
evidence. Use the document status and date: a historical plan can explain why a decision was made,
but it is not automatically the current implementation contract.

## Current authorities

- [`registered-feature-scope.md`](registered-feature-scope.md): approved team ownership, feature
  purposes, and minimum frontend/backend/database boundaries
- [`shared-platform-design.md`](shared-platform-design.md): living Shared services, AI-mode,
  contracts, persistence, testing, and deployment design
- [`feature-integration-and-experience-contract.md`](feature-integration-and-experience-contract.md):
  canonical routes, cross-feature HTTP/publication flows, shared UI behavior, onboarding, and
  integration tests
- [`agent-run-state-machine.md`](agent-run-state-machine.md): normative run transitions, durable
  checkpoints, tool turns, idempotency, cancellation, review, and recovery
- [`feature-1-schema-fingerprint-policy.md`](feature-1-schema-fingerprint-policy.md): reproducible
  Feature 1 PostgreSQL/PostGIS schema-drift evidence

## Detailed plans and proposals

- [`propertyscope-product-and-feature-plan.md`](propertyscope-product-and-feature-plan.md) is the
  detailed product/data/UI/API proposal. It is subordinate to the approved scope and does not turn
  optional concepts into commitments.
- [`feature-data-and-shared-adoption-plan.md`](feature-data-and-shared-adoption-plan.md) records the
  independent consumer-client and Shared assistant adoption path for Features 2–5.
- [`shared-run-observability-proposal.md`](shared-run-observability-proposal.md) separates the
  implemented local read-only baseline from proposed remote observability.
- [`repository-architecture.md`](repository-architecture.md) preserves the initial scaffold and its
  point-in-time validation; it is not the current implementation summary.

## Decisions and evidence

`decisions/` contains architecture decision records. Important current boundaries include the
Feature 1-only PostgreSQL/PostGIS exception (ADR-016), OpenAI Responses provider (ADR-017), shared
mapping seam (ADR-020), typed source materialisation (ADR-032), supported consumer publication
(ADR-033), and manifest-driven onboarding/health (ADR-034).

`reviews/` retains external or adversarial review inputs. Findings become authoritative only after
they are verified and incorporated into a living design or ADR.

Keep editable Mermaid or other diagram sources beside exported images/PDFs. Release-specific
architecture and evidence belong under `../release-0/`, `../release-1/`, or `../release-2/`.
