# ADR-034: Project enabled features and operational health from validated metadata

- Status: Accepted
- Date: 30 August 2026
- Owners: Shared platform and enabled feature owners
- Extends: ADR-016, ADR-033

## Context

Enabling a feature required matching edits to Shared routes, browser registries, static fragments,
AI catalogue mounts, frontend assets, quality inputs, UI fixtures, database ownership checks, and
Compose validation. Those lists could drift, and a disabled or incomplete feature could be exposed
accidentally. Docker builds also depended on every uv workspace manifest being copied before a
locked sync, but no check kept Docker inputs aligned with workspace and lock metadata.

Health responses had two competing interpretations: HTTP-only probes and typed-body consumers could
disagree about whether an optional model provider made the process unavailable. Feature frontend
Nginx also resolved its backend only at startup, so recreating the backend could leave port 5200
pointing at a stale container address.

## Decision

- `deployment/features.yaml` is the closed, explicit enablement selection. Each selected feature is
  joined to its owner-controlled `feature.yaml`; omitted or disabled features expose no generated
  route/registry entry, tool catalogue, feature quality input, database declaration, or UI fixture
  asset root.
- A domain-neutral onboarding section declares frontend assets and service, backend service, AI tool
  catalogue source and fixed runtime path, owned quality inputs and coverage policy, database service
  and volume ownership, and an optional shell evidence-adapter path. Shared validates and projects
  these mechanics but does not interpret feature records or business rules.
- Generated JSON and browser projections are checked in and drift-checked. The canonical gate
  discovers enabled feature-owned Python/Node checks and coverage declarations from the projection.
  Architecture validation checks enabled routes, catalogue mounts, assets, database/volume ownership,
  and Compose wiring. A separate workspace validator checks `uv.lock` membership and the manifests
  copied before Docker `uv sync` steps.
- Health endpoints use the versioned typed health projection. Required unhealthy checks produce an
  unhealthy body and HTTP 503. Optional unhealthy checks produce an explicit degraded body and HTTP
  200. Liveness reports process state without consulting dependencies. The body includes the expected
  HTTP status, and responses use JSON media type.
- Feature 1 Nginx resolves its variable backend upstream through Docker DNS with a bounded validity
  period. Only the two registered health paths are proxied; invented health paths return JSON 404
  rather than the SPA. A live gate recreates only the backend and proves the unchanged port-5200 edge
  recovers.
- `scripts/dev.py operator report` is read-only. It reports registered products, accepted releases,
  review/publication prerequisites, durable consumer imports, activation state, and degraded optional
  dependencies. It performs no review, publication, import, or activation transition.

## Consequences

Onboarding has one validated source for mechanical exposure and ownership, while planned feature
labels can remain honest product placeholders. Adding an enabled feature requires a complete owned
manifest and passing discovered checks; adding a workspace package requires aligned locked and Docker
inputs. Optional AI degradation no longer disables deterministic data workflows or creates an
ambiguous probe result.

Compose remains an explicit reviewed topology rather than generated hidden infrastructure. Validators
therefore prove it matches the projection. Feature-specific UI evidence and health-check names stay in
the owning feature even though their envelope and availability rules are Shared contracts.

## Alternatives considered

- **Keep synchronized hard-coded lists:** rejected because disabled-feature exposure and silent drift
  remain possible.
- **Generate the complete Compose topology:** rejected because it would hide consequential service,
  secret, resource, and persistence decisions from review.
- **Return 503 for any optional provider outage:** rejected because deterministic workflows remain
  usable offline and process/readiness state must distinguish optional degradation.
- **Let the operator report publish prerequisites automatically:** rejected because review and
  publication are explicit human safety boundaries.
