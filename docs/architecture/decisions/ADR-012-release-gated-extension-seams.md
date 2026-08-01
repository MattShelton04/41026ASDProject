# ADR-012: Build later-release seams early and gate runtime capabilities

- Status: Proposed for team approval; implemented as interface-only seams
- Date: 1 August 2026
- Owner: Shared platform team
- Supersedes: None

## Context

Release 1 requires local MCP/RAG, and Release 2 requires local Planner/Worker/Reviewer
roles while excluding all three advanced services from the cloud. Building a second run
model later would create migration and integration risk, but claiming later-release
behavior early would weaken assessment traceability.

## Decision

The Release 0 contracts include role, review, prompt-version, provider, and typed tool
seams needed by later releases. Citation and artifact contracts remain to be added with
Release 1's concrete evidence requirements. MCP/RAG must become adapters over existing
feature tools and evidence. Multi-agent roles must share the same run, step, limit, and
review model.

Do not start services, expose enabled routes, or claim evidence for a capability before
its release. Cloud configuration must omit MCP, RAG, and multi-agent services rather
than merely hiding their UI.

## Alternatives considered

- Deferring every interface was rejected because it would encourage incompatible
  Release 1/2 rewrites.
- Implementing all services now was rejected because the domain, corpus, feature tools,
  and assessment evidence are undecided.
- A separate multi-agent workflow database was rejected because it would create a
  second source of run truth.

## Consequences

Release 0 code carries a few deliberately unused types and ports, but later releases can
extend without breaking feature APIs. Tests and documentation must continue to
distinguish implemented foundations from enabled release behavior.
