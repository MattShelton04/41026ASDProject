# ADR-042: Import complete sales releases with durable streaming work

- Status: Accepted
- Date: 5 September 2026
- Owners: Feature 2, explicitly coordinated by the user, with Feature 1 delivery recovery
- Extends: ADR-033 and ADR-041

## Context

The existing Feature 2 importer rejected the full 7,402,643-record PSI release at 5,000 records.
It also imposed 25 MiB compressed and 75 MiB expanded limits, buffering both the complete artifact
and normalized records in one synchronous request. Raising a constant would leave that flow unable
to recover from HTTP timeouts or safely expose a partially imported generation. The user explicitly
requested support for the complete release after producer publication was decoupled in ADR-041.

## Decision

Feature 1 pushes metadata; Feature 2 pulls artifact bytes. The import POST records a durable
consumer-owned operation and returns 202. A fixed GET status resource supplies identity-bound
acknowledgements and terminal receipts. No data transfer runs inside the acknowledgement request.

A backend worker streams compressed bytes to temporary disk, checks the entire digest and declared
byte count, then reads gzip NDJSON with a 1 MiB per-record memory budget. Each v3 record and its
release/generation provenance are validated. No fixed total dataset-size limit is imposed. Database
batches are bounded to 1,000 records / roughly 1 MiB; every row remains included.

Only the Feature 2 database API opens its SQLite file. Migration 004 adds immutable generation
identity, operations, request aliases, invisible rows keyed by ordinal and business identity, and
an accepted-generation pointer. The API stages short transactions and verifies exact ordinal/hash
replay. Duplicate business identities fail instead of being silently ignored. Completion requires
both validated stream count and persisted count to match. It commits the receipt and pointer in one
short transaction. Sales reads select that generation; historical/synthetic storage remains intact.

Leases fence batches, heartbeats and completion. The database permits one live importer at a time
while WAL allows status and sales reads. A replacement worker reclaims an expired lease and replays
the artifact against retained invisible staging. Temporary network/storage failures retry with
backoff up to five attempts. Fresh delivery keys may create a new consumer operation after a closed
failure; old request keys retain their original identity and result. Active or accepted deliveries
coalesce only when their immutable evidence matches. An older queued operation cannot overwrite a
newer accepted consumer operation.

Feature 1 adds a separate version-checked Retry downstream import command for an already-published
release. This command creates/reconciles delivery work and never republishes or rolls back producer
data. Feature 2 joins Feature 3 in allowing a fresh delivery after a definitively failed receipt.

## Consequences and validation

Disk space and processing time scale with the full artifact; worker memory scales with one record
and one batch. Failed invisible staging remains available for replay and is not automatically
purged. Consumer imports can lag Feature 1 publication. Existing per-property query pagination is
separate from import capacity. No cross-feature database access or service imports are introduced.

Tests import 6,001 records, lose a committed batch response and recover without duplicates, fence
an expired worker, reject changed replay evidence, and prevent visibility after checksum, gzip,
count, provenance or duplicate-key failures. A source-scale envelope is accepted without downloading
inside the POST. Live validation uses the complete PSI artifact and records memory and row counts.
