# ADR-030: Publish complete generations as streaming release artifacts

- Status: Accepted
- Date: 29 August 2026
- Owner: PropertyScope Feature 1
- Extends: ADR-029; preserved for complete generations by ADR-035

## Context

ADR-029 made complete acquisition and an immutable complete warehouse generation mandatory, while
allowing a separately bounded downstream product. The first implementation called that bounded
product the release and silently retained `release_scope.maximum_records` values (50,000 for
G-NAF). Release construction also accumulated every projected row and the complete JSON envelope
in Python memory, counted the candidate on every `OFFSET` page, and could not complete when the
warehouse generation exceeded the old projection bound. That did not meet the product meaning of
"full data available through the completed release".

## Decision

- A completed, publishable `full-data` Feature 1 release consists of the complete immutable warehouse generation and one
  complete, deterministic exported artifact. No `release_scope.maximum_records` or year subset is
  permitted in a complete-release job.
- ADR-035 scoped PSI runs can build explicitly partial candidate artifacts for inspection, but those
  candidates are not publishable and never replace the accepted complete-generation pointer.
- Export artifacts use gzip-compressed NDJSON. Each line is one record conforming to the existing
  product record schema; the manifest declares `application/x-ndjson`, `content_encoding: gzip`,
  exact rows, compressed bytes, content SHA-256, ordering, lineage, licence and redistribution
  decision. Builder versions are incremented because the artifact container changed.
- Construction keyset-pages the immutable candidate using its registered stable key. Candidate
  total is calculated on the first page only. Projection, validation, compression, hashing, byte
  counting and summary construction are streaming and keep only one page plus bounded summary
  state in memory.
- `/dataset-releases/{id}/records` is a bounded browser/API **preview**. It is never described as
  the complete release artifact and does not change release completeness.
- Licence-controlled complete artifacts are retained and evidenced by the release but are not
  made anonymously downloadable. Public/approved redistribution policies continue to govern the
  artifact download endpoint.
- Feature 1 self-publication trusts the durable construction evidence for its own immutable
  content-addressed export. The interactive request checks the registered manifest, checksum,
  byte count, schema, release identity and storage key, then returns after queueing; it does not
  repeat the complete stream validation synchronously.
- Before materialisation, the artifact-volume-owning loader streams the queued export to recheck
  physical existence, exact bytes and SHA-256 against that durable ledger evidence. The activation
  lease heartbeat remains active during the scan; failure leaves the accepted pointer unchanged.
- The durable timeline is simplified to Discover, Acquire, Import, and Build release. Canonical
  verification, COPY, candidate insertion and import quality are observable subphases of Import;
  they are not instant placeholder stages.

## Cancellation and storage consequences

Import verifies the canonical checksum while the same byte stream is parsed and copied. A
watcher cancels an active PostgreSQL statement when the run is cancelled, and checksum failure
still occurs before transaction commit. Progress rows, bytes, totals, phase and timestamps are
durable.

G-NAF candidates maintain their generation key but not the expensive serving search, geometry,
postcode, street-number or stable-reference indexes. Those indexes contain accepted rows only and
are populated during reviewed activation before the accepted pointer changes. A cancelled import
therefore cannot repeat the historical 1.088 GB global serving-index growth pattern.
The source-scale `published` update commits independently of the activation-row marker so loader
heartbeats cannot wait behind their own long transaction. Recovery after a crash between commits
replays only rows still marked unpublished before the accepted pointer transaction is considered.

Cancelled or failed ingestion-owned draft/candidate releases become immutable `abandoned` records
linked to the run and bounded terminal error. They remain audit evidence but are excluded from the
normal Published data list and cannot be edited, reviewed, published, or deleted through release
workflow actions.

Physical content is content-addressed. Multiple lineage records may reference one storage key;
this reuses bytes without conflating run evidence. Cleanup removes only old physical objects that
have no artifact-ledger reference, honours an explicit grace period, and defaults to dry-run.

## Alternatives considered

- **Treat the warehouse generation alone as the release:** rejected because downstream users need
  a versioned, integrity-verifiable transfer path without database access.
- **Increase 50,000 to another integer:** rejected because publisher growth would recreate hidden
  truncation and monolithic memory use.
- **Keep the v1 JSON envelope for source scale:** rejected because it encourages whole-document
  materialisation and does not provide a practical restart/cursor boundary.
