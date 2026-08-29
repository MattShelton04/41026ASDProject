# ADR-028: Activate source-scale releases asynchronously through immutable generations

- Status: Accepted
- Date: 26 August 2026
- Owner: PropertyScope Feature 1
- Extends: ADR-016 and ADR-021

## Context

A reviewed 5,190,134-row G-NAF candidate exposed a publication-path scaling failure. The
database API held one HTTP request and one PostgreSQL transaction while it copied the address
generation into global registry tables, populated per-property coverage and finally rewrote every
`warehouse.gnaf_address.property_ref`. Two publication requests then held or waited for the same
accepted-release lock for about fourteen minutes. Docker reported more than 80 GB of PostgreSQL
block writes, PostgreSQL generated roughly 0.54 GB of WAL between checkpoints every five to six
seconds, and the browser request timed out even though the server-side statements continued.

Moving the same multi-million-row statements to a background process alone would fix the HTTP
timeout but not visibility. Updating a global `registry.property` before the accepted pointer
changes can expose a candidate address or geometry through an already-accepted identifier.
Running those writes under the pointer lock would preserve visibility but recreate the long lock
and write-amplification failure.

## Decision

- Publication validates the consumer evidence and durably records its receipt first. For Feature
  1 self-publication, complete release construction has already schema-validated every streamed
  row and atomically hashed and fsynced the content-addressed artifact. The HTTP request therefore
  validates only the durable manifest/artifact/release binding; it does not reread, decompress and
  revalidate millions of records. Any later source-scale preparation remains in the loader before
  the accepted pointer changes.
- The database API creates an `ops.release_activation` operation and returns HTTP `202`. It never
  performs source-scale activation work in an HTTP request.
- The existing serial credential-owning database loader claims activations with a renewable lease.
  Lease loss cancels the PostgreSQL connection; an interrupted or expired operation can be claimed
  again, with a maximum of three attempts.
- A source-scale warehouse/index transaction never updates the leased activation row. It commits
  first, then a separate short transaction records `materialized_at`, allowing heartbeats to renew
  throughout the long statement. A crash between those commits is recovered by the idempotent
  `published = false` predicate before the marker is retried.
- Only one nonterminal activation may exist for a release/version. A browser retry with an unknown
  outcome reuses its request key, while a different key is coalesced onto the already queued work.
- Candidate address rows remain only in their immutable, release-scoped
  `warehouse.gnaf_address` generation. Activation preparation never copies or updates canonical
  fields in global registry tables.
- Property search, detail and coverage resolve the stable deterministic property reference from
  the warehouse generation selected by `serving.accepted_generation`. Candidate generations are
  therefore invisible until the pointer transaction commits.
- The final transaction takes one dataset-scoped advisory lock, supersedes the prior release,
  marks the reviewed release accepted, advances `serving.accepted_generation`, and completes the
  activation operation. It contains no warehouse, registry or per-property coverage DML.
- Expression indexes support normalized address search and deterministic property-reference
  lookup without rewriting warehouse tuples. Existing registry rows remain a compatibility path
  for retained non-warehouse identities and aliases.
- The release detail response exposes activation state. The browser disables duplicate publish or
  reject actions while activation is queued/running and explains that the prior version remains
  live.

## Consequences

Publication requests are bounded by artifact verification and queue persistence. Loader restart or
connection loss cannot expose a half-accepted generation. A successful pointer switch is small and
idempotent, while the accepted warehouse generation remains the single source of canonical address
fields.

The G-NAF search indexes add durable storage and index-maintenance cost to candidate imports. This
is bounded and observable, unlike repeated table rewrites, but retention/partitioning should be
revisited if many complete G-NAF generations are kept simultaneously. The registry tables remain
available for manual resolution and other identity sources; future reconciliation must use a
release-scoped staging model rather than mutating accepted-visible rows before activation.

## Validation record

Against the retained 5,190,134-row candidate, the one-time normalized-search index was 351 MB and
the deterministic-reference index was 156 MB. The cold representative `Parramatta` lookup used a
bitmap scan on the trigram index and returned its first 26 rows in 820 ms; deterministic detail
lookup used the expression index and completed in 0.7 ms. The index migration increased Docker's
cumulative PostgreSQL block-write counter by about 3 GB once. It did not rewrite warehouse tuples.

Deterministic tests assert that activation preparation issues no registry, warehouse-update or
coverage DML; accepted search joins the selected warehouse generation; expired leases are bounded;
loader shutdown leaves an explicitly recoverable operation; and the final pointer transaction
contains no source-scale statements.

## Alternatives considered

- **Keep synchronous publication and increase HTTP timeouts:** rejected because the request and
  accepted lock still own source-scale work.
- **Copy candidate rows into global registry tables before the pointer switch:** rejected because
  changed canonical fields can leak before acceptance.
- **Run registry copies inside the pointer transaction:** rejected because it recreates long locks,
  large WAL volume and timeout ambiguity.
- **Persist deterministic property references back into every warehouse row:** rejected because the
  value is derivable and the update rewrites millions of tuples and indexes.
