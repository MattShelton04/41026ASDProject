# ADR-041: Publish producer releases independently of downstream imports

- Status: Accepted
- Date: 5 September 2026
- Owner: Feature 1
- Supersedes: the consumer-acceptance publication gate in ADR-033 and ADR-040

## Context

The complete PSI release has 7,402,643 records. Feature 2 rejects its import because its current
synchronous importer permits at most 5,000 records. The prior contract made that downstream
capacity limit prevent Feature 1 publishing an otherwise valid, reviewed, complete artifact.
The user explicitly clarified that downstream imports must not gate data platform publication.
Feature 2's importer rewrite remains outside this change.

## Decision

Publication verifies Feature 1's registered immutable artifact/manifest binding, records a producer
verification receipt (`feature-1-local:` identity, owned by Feature 1), and queues the existing
fenced activation worker. The worker verifies artifact bytes and prepares any required local
indexes before atomically switching the accepted generation. This receipt attests producer
verification; it does not claim that any downstream service has imported or accepted the release.

For an external target, the same final PostgreSQL transaction inserts a durable delivery outbox
operation. A persistence failure rolls back both publication and outbox. Replaying a completed
activation cannot duplicate delivery. Existing nonfailed matching deliveries are retained.
The runner independently connects, polls and records the genuine downstream receipt. New outbox
operations carry `delivery_only=true`; acceptance finishes them as `delivered`, without requesting
another producer activation. Rejection or exhausted transport retries leave producer publication
and the accepted pointer unchanged. Existing legacy delivery/activation operations retain their
replay semantics so in-flight recovery evidence is not discarded.

The UI distinguishes Published/Publishing/Publication failed from downstream import progress or
failure. Current release state and local activation determine publication; downstream work cannot
remove publish actions or put a valid release into limbo. Separate polling continues while an
import remains active. Producer verification is explicitly labelled in receipt history.

## Consequences

Publishing does not truncate, sample or cap the complete dataset. A publish request returns quickly
with durable activation progress; full byte verification or local index preparation can still take
time. Consumers can lag or reject a generation while the data platform serves its complete artifact
and accepted data. No distributed atomicity across feature databases is implied. Each consumer
continues owning its validation and accepted generation. The Feature 2 streaming integration gap
remains visible as a downstream warning and must be addressed separately for full consumer import.

Migration 051 adds the delivery-only flag and delivered terminal state without rewriting existing
receipts, lifecycle rows or applied migrations. Tests force outbox persistence failure to verify
rollback, replay activation, and prove both consumer acceptance and failure leave publication intact.
