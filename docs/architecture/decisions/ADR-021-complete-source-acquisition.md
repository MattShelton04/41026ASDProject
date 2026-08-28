# ADR-021: Separate complete source acquisition from bounded consumer products

- Status: Superseded by ADR-029 for acquisition scopes and ceilings; consumer-product separation retained
- Date: 25 August 2026
- Owner: PropertyScope Feature 1
- Extends: ADR-016

## Context

The full-data runtime was connected to official NSW sources, but G-NAF and BOCSAR reused
the row bound of their portable release product as an acquisition limit. Selecting
"full-data" therefore downloaded and verified a complete source archive while silently
retaining only a selected subset of its canonical records. This contradicted ADR-016's
decision that a live accepted generation is never truncated and made the operator label
misleading.

Source acquisition and cross-feature publication have different scale and licensing
constraints. Feature 1's PostgreSQL warehouse can own a complete source generation, while
consumer features must continue to receive explicitly scoped, versioned products rather
than unrestricted warehouse access.

## Decision

- A registered `full-data` scope means every available record or partition in the selected
  official source snapshot. It uses `all_records: true` and does not accept an operator row
  limit.
- Test and showcase scopes remain deliberately small and deterministic.
- Adapter byte, member, source-row, elapsed-time and canonical-row ceilings remain capacity
  and corruption safeguards. Crossing one fails the candidate atomically; it never returns
  a successful truncated generation.
- BOCSAR keeps its wide source-row ceiling separate from its sparse canonical-row ceiling.
  As of the August 2026 source snapshot, the two registered archives contain 318,122 wide
  rows and expand to 10,114,565 canonical observations and coverage records; the capacities
  include growth headroom without constraining the separately bounded consumer release.
- Source-scale G-NAF and BOCSAR canonical records use NDJSON between the runner and serial
  PostgreSQL loader. G-NAF spills its multi-file geocode join to runner-local temporary
  SQLite so millions of addresses are not accumulated in application memory. BOCSAR emits
  postcode and suburb sparse records incrementally.
- PSI complete history retains its existing annual/current-weekly streaming path. The
  schools master imports every published source row and fails if the registered capacity
  alarm is exceeded.
- `release_scope` remains a separate, explicit bound for portable consumer artifacts.
  It does not limit the Feature 1 warehouse generation. Dataset previews page over the
  complete immutable generation, and accepting a Feature 1 property release activates the
  complete address generation for property discovery.

## Consequences

Operators can request complete official data from the browser without choosing an arbitrary
record count. Long-running jobs consume more disk and time, so they remain explicit reviewed jobs
and preserve the previous accepted generation until review. ADR-022 connects those jobs in the
default runtime instead of a separate Compose project.

Release manifests and consumer receipts continue to describe the bounded product actually
sent across a feature boundary. Run/import evidence describes the complete source generation.
The UI must keep these counts and meanings distinct.

## Alternatives considered

- **Raise every visible row limit:** rejected because the next source growth would recreate
  the same truncation and the existing G-NAF implementation retained too much in memory.
- **Publish unrestricted multi-million-row JSON envelopes:** rejected because it couples
  consumer capacity to Feature 1's warehouse and conflicts with ADR-016.
- **Partition source acquisition into manual locality/year jobs:** retained for targeted
  reprocessing, but rejected as the only full-data path because it cannot prove a complete
  source snapshot was retrieved on demand.
