# Feature data and Shared adoption plan

Status: implementation in progress  
Updated: 28 August 2026

## Decision

Features 2–5 remain independently deployable slices. Each feature backend owns its HTTP clients,
validation, timeouts and fallback behaviour; it must not import Feature 1 production code or another
feature's package. Feature backends may import the domain-neutral `shared_contracts` package, tests
may import `shared_testkit`, and feature frontends may consume documented Shared JavaScript/CSS
barrels.

Feature 1 is the governed source-data provider. It must preserve source facts before publishing a
bounded, immutable product to a consumer-owned import endpoint. A consumer database remains that
feature's runtime source of truth after acceptance. AI-mode remains a shared HTTP service; each
feature backend constructs its own bounded objective and tool allowlist, while the shared AI-chat
package owns only transport-neutral browser state and presentation.

## Verified gaps

The running development stack was inspected through its public HTTP edge and its owning database
service. The source loaders have populated property, sales, crime and school generations, but the
following gaps block dependable downstream use:

1. The current PSI adapter discards published address, zoning, nature-of-property, primary-purpose,
   component, sale-code and interest fields. It also reads the wrong property identifier position in
   the historical wire layout.
2. Consequently almost every loaded sale is marked `MISS`; only 10 of about 7.3 million retained
   PSI rows currently have a `property_ref`.
3. The closed `propertyscope.property-sales.v1` product cannot gain those fields additively. A v2
   contract and builder are required; v1 remains readable for retained releases.
4. Sales, crime and school candidates exist, but no Feature 2/3 consumer callback has accepted them.
   Feature 1 must not invent acceptance or write a consumer database directly.
5. Shared AI chat is implemented and used by Feature 1, but a new feature still has to infer the
   exact frontend/backend adoption steps from several documents.

Feature 4 has no approved source registration and Feature 5 is a composition feature rather than a
Feature 1 dataset consumer. Those are product/allocation inputs, not defects that Feature 1 can fill
with invented data.

## Implementation slices

### 1. Preserve and match PSI source facts

- Parse both historical and current official B-record layouts without losing address or
  classification fields.
- Add nullable warehouse columns and selective indexes through an immutable migration.
- Derive only conservative structured address components. Exact matching must require one unique
  registry candidate; ambiguous or incomplete rows remain explicitly unmatched.
- Include every preserved fact in row hashing so corrected retransmissions become revisions.
- Cover historical/current layouts, malformed values, matching SQL and migration drift in tests.

### 2. Publish a versioned sales product

- Add `propertyscope.property-sales.v2`, a checked-in JSON Schema and valid/invalid fixtures.
- Register builder `property-sales 2.0.0` and update the PSI job target without mutating v1.
- Project the richer fields in release preview and immutable artifacts.
- Keep bounded release scope, deterministic ordering, checksums, licence policy and consumer receipt
  flow unchanged.

### 3. Make consumer startup explicit

- Update the Feature 1 consumer guide with the v2 migration, release discovery and independent-client
  rules.
- Provide a short client adoption checklist covering catalogue discovery, accepted reconciliation,
  artifact verification, idempotent import and typed receipts.
- Document that candidate preview is operator evidence, not a substitute for acceptance.

### 4. Reduce Shared AI/chat adoption work

- Add a domain-neutral frontend route factory on the public `ai-chat/index.js` barrel. Features inject
  their own API root, feature identity, scopes, wording, context and activity link.
- Add executable tests and a copyable feature wrapper example.
- Document the independent backend adapter: validate with `shared_contracts`, call AI-mode over HTTP,
  expose a same-origin feature turn API, and keep deterministic feature reads available when the
  model provider is unavailable.

## Completion evidence

- Focused adapter, import, builder, contract, component and Shared frontend tests pass.
- The canonical `uv run python scripts/check.py` quality gate passes.
- A rebuilt local stack reports healthy service boundaries and the public release projection exposes
  the v2 source fields.
- A separate review agent audits the completed diff; every finding is verified and either fixed or
  explicitly rejected with evidence before pull-request creation.

## Remaining owner actions

- Feature 2 must implement and register its v2 consumer import endpoint before a sales candidate can
  become accepted.
- Feature 3 must implement its consumer endpoint and approve its crime/school semantics before those
  candidates can become accepted.
- Feature 4's source/data contract and Feature 5's provider-section clients require team/tutor-approved
  product decisions.
