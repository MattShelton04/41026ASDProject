# ADR-033: Distribute producer contracts and publish through durable consumer operations

- Status: Accepted
- Date: 30 August 2026
- Owners: Shared platform and PropertyScope Feature 1
- Extends: ADR-016, ADR-021, ADR-028, and ADR-030

## Context

Feature 1 builds immutable, content-addressed consumer releases, but the documented reference path
had drifted from the runner: the runner emits gzip-compressed NDJSON while examples and tests used a
JSON envelope with different version evidence. Consumers also had to find schemas in producer source
paths and reimplement redirect, size, checksum, decompression, manifest, receipt, and retry rules.

The external publication request performed consumer import work synchronously. A browser or edge
request could therefore require a multi-hour deadline, and a timeout left the delivery outcome
ambiguous. The idempotency key used for the delivery attempt was also liable to be mistaken for a
consumer-issued operation identity. Pull reconciliation could discover a receipt eventually, but it
was not a durable, observable publication workflow.

## Decision

- Feature 1 publishes a versioned product-contract set as a deterministic ZIP discovered through a
  fixed API route and downloaded only through its SHA-256-bound immutable path. It maps each runtime
  registry entry to its producer-owned record schema and declares its compatibility policy. The
  registry, generated JSON Schemas, manifests, guide examples, and reference-consumer tests must
  agree. Consumers depend on the contract artifact, not arbitrary producer implementation paths.
- Portable releases use the runner's real representation: `application/x-ndjson` records compressed
  with gzip. The manifest records the media type, content encoding, immutable release identity,
  dataset and target, product-schema version, byte count, record count, and SHA-256 digest.
- Shared provides a domain-neutral consumer protocol helper for fixed or path-bound artifact access,
  redirect rejection, byte ceilings, streaming digest and gzip-NDJSON processing, manifest
  validation, producer-supplied record-schema hooks, atomic-import handoff, closed receipts, and
  correlation/idempotency conventions. Domain schemas and import rules remain producer or consumer
  owned; Shared contains no sale, crime, school, planning, or buyer semantics.
- A release identity is immutable evidence and is distinct from a delivery operation. The producer
  creates a durable local consumer-import operation before contacting an external consumer. A short,
  bounded connect request may return a genuine consumer operation and status reference or a final
  receipt. The producer never fabricates a consumer operation identifier from its own operation or
  idempotency key.
- Accepted acknowledgements, polling progress, terminal receipts, and safe retry evidence are stored
  durably. Leased workers reconcile nonterminal operations. Retries coalesce by immutable release,
  dataset, target, schema, checksum, and record count; evidence that differs in any of those fields is
  rejected. An artifact already durably imported with matching evidence is not downloaded again.
- A final receipt is retained before Feature 1 queues activation. The accepted pointer changes only
  after consumer acceptance and the existing release-activation transaction succeeds. A failure,
  cancellation, timeout, or crash cannot expose a partial candidate or replace the accepted
  predecessor.
- The publication endpoint queues or resumes durable work and returns a status resource without
  waiting for source-scale import. Existing consumers that return an immediate final receipt remain a
  bounded, tested compatibility path. Published size and timeout budgets are contract limits rather
  than browser deadline recommendations.

## Consequences

Consumer onboarding has one supported schema source and one reusable transport implementation while
domain ownership remains intact. Real HTTP tests can consume exactly what the production runner emits.
Publication becomes observable and safely retryable across browser timeouts and process crashes, and
operation identity no longer weakens release evidence.

The producer now owns durable operation state and a reconciliation worker. Consumers must expose a
fixed import endpoint and, for asynchronous acceptance, a bounded status resource. Schema evolution
requires a new compatible contract version or an explicitly coordinated breaking version; changing a
generated schema without updating the registry, manifests, guide, and drift tests fails the quality
gate.

## Alternatives considered

- **Keep schemas only beside producer source:** rejected because consumers would depend on repository
  layout rather than a supported contract boundary.
- **Document transport checks for every consumer to reimplement:** rejected because subtle redirect,
  byte-limit, digest, decompression, and replay differences create inconsistent trust boundaries.
- **Increase publication HTTP timeouts:** rejected because request lifetime is not durable workflow
  state and does not resolve crash windows or ambiguous retries.
- **Reuse the delivery idempotency key as the consumer operation ID:** rejected because only the
  consumer can issue its operation identity and fabricated evidence cannot be reconciled safely.
