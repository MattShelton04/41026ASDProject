# Feature 1 reference-data operations

This is the reproducible application workflow for the September reference-data increment.
The [initial audit](../reviews/feature-1-dataset-audit-2026-09-13.md) is a historical local
snapshot. Implemented source profiles, current publisher data and accepted local releases
are three separate states; starting the stack does not download or accept datasets.

## Setup without clickops

Follow the root development prerequisites, then use the versioned dependency lock and stack:

```text
uv sync --locked --all-packages --all-groups
uv run scripts/dev.py stack up
```

For an existing running checkout after this dependency change:

```text
uv run scripts/dev.py stack rebuild f1-backend f1-db-api f1-runner f1-db-loader
```

Wait for active imports/acquisitions before rebuilding their workers. Web services reload
source changes in development and apply new migrations on initialization; assume a migration
is immutable as soon as it appears in a running development checkout. Long-lived runner/loader
processes need a restart to load changed modules. PostgreSQL migrations create the reference warehouse and register sources,
adapters and jobs on a fresh or existing database. YAML profiles, catalogue names/groups,
contracts, dependencies and worker defaults are all checked in. No administrator UI edits,
manual SQL inserts, prototype paths or copied local data are required for these ten sources.
Existing G-NAF cache/access configuration is independent of this new reference-source setup.

The local verification used supported job APIs/CLI, container lifecycle commands and read-only
diagnostic SQL. Temporary additional runners allowed the existing PSI worker to finish while
new reference code was tested; they are not deployment prerequisites. Disposable PostgreSQL
databases were used for destructive integration fixtures, separate from retained local data.

Queue any registered job; omit `--no-wait` to follow its run:

```text
uv run scripts/dev.py data collect nsw-cadastre --no-wait
uv run scripts/dev.py data collect nsw-planning-controls --no-wait
uv run scripts/dev.py data collect abs-geography-2021 --no-wait
uv run scripts/dev.py data collect nsw-suburb-boundaries --no-wait
uv run scripts/dev.py data collect nsw-school-catchments --no-wait
uv run scripts/dev.py data collect nsw-strata-schemes --no-wait
uv run scripts/dev.py data collect nsw-amenities --no-wait
uv run scripts/dev.py data collect abs-cpi --no-wait
uv run scripts/dev.py data collect nsw-bushfire-prone-land --no-wait
uv run scripts/dev.py data collect nsw-flood-planning --no-wait
```

Jobs finish as reviewable candidates. Review quality results and source limitations before
publishing through the existing workflow. Publication accepts the complete producer generation;
these ten profiles target Feature 1 and create no new downstream delivery. Source registration
and acquisition do not imply that a consuming feature can already use the facts.

## Scope and useful distinctions

| Job | Complete registered scope | Important handling |
|---|---|---|
| `nsw-cadastre` | Current NSW Lot layer | Lot/plan facts; no invented address, ownership or sale crosswalk |
| `nsw-planning-controls` | Zoning, height, FSR, minimum lot size, heritage | Preserve instrument, units and effective/source dates |
| `abs-geography-2021` | NSW SAL and LGA, ASGS Edition 3 / 2021 | Retain edition and nonspatial category codes |
| `nsw-suburb-boundaries` | Current gazetted suburbs/localities | Distinct from ABS statistical boundaries and postcodes |
| `nsw-school-catchments` | Primary, secondary and future government-school zones | Retain school code, grade and priority; added date is not commencement |
| `nsw-strata-schemes` | Published StrataHub scheme geometry/register records | Publisher record ID is identity; duplicate plan numbers can be valid records |
| `nsw-amenities` | 17 selected official facility/reserve layers | Includes libraries, education, emergency, health, transport and NPWS estates; not all council parks/businesses |
| `abs-cpi` | Sydney and Australia, all groups original, monthly and quarterly | Preserve frequency, period and published index reference base |
| `nsw-bushfire-prone-land` | Published BFPL layer | Planning designation, category and guideline; not event prediction |
| `nsw-flood-planning` | Published EPI flood-planning controls | Potentially stale coverage; AEP/scenario/study extent unknown; absence means unknown |

The [spatial](../reviews/feature-1-spatial-source-verification-2026-09-13.md) and
[other reference-source](../reviews/feature-1-reference-source-validation-2026-09-13.md)
reports link exact official endpoints and real schema/count observations. Publisher values,
including nulls and raw year-3000 end-date sentinels, remain in source attributes. The canonical
expiry is null for that sentinel. Invalid topology is flagged and excluded from the spatial
index; source geometry is not silently repaired. Structural/non-finite geometry fails import.

## Concurrent jobs and runtime

`PROPERTYSCOPE_ACQUISITION_WORKERS` is an integer from 1 to 4, default 1. Set it in local
`.env` or the shell used by the stack command, then recreate an idle runner:

```powershell
$env:PROPERTYSCOPE_ACQUISITION_WORKERS = '2'
uv run scripts/dev.py stack restart f1-runner
```

Each worker claims independently leased durable tasks. Different jobs can acquire/build in
parallel, while prerequisites keep one run's stages ordered. The publication delivery loop
remains separate. There is still one database loader, so imports and activations queue instead
of competing for PostgreSQL memory, temporary space, indexes and WAL. An acquisition worker
waiting on its import still occupies its slot; this is bounded pipeline concurrency, not a
promise that every queued download starts immediately.

Start with two workers when queuing mixed small sources. Four may help network-bound batches,
but can contend on publisher limits, CPU, compression, disk and the serial loader. Cadastre
itself uses four disjoint OID-range readers, each with one page in flight; extra job workers
add to that network concurrency. No linear throughput gain or universal completion time is
assumed. The retained verification environment exposes about 7.7 GiB of Docker memory;
its complete PSI replay also competes with other source work and is not a controlled
speed comparison with the older accepted import. Preserve one loader until separately measured database concurrency is designed.

Cadastre selects the publisher's supported `resultType=standard`, at most 2,000 records per
page and never above its advertised standard limit. A same-record 8,000-row benchmark reduced
transport wall time from 14.177 seconds (80 default-mode requests) to 3.415 seconds (four
standard-mode requests), with identical feature hashes. This is a bounded transport result,
not a whole-source estimate. Other profiles use their ordinary advertised caps; flood uses
100 and NPWS reserves 25 because of complex geometries.

Recognizable HTTP-200 HTML size errors and responses above 64 MiB halve a page at the same
OID cursor, down to one record. BFPL also returned the specific ArcGIS HTML query-operation
error with HTTP 500 for a 1,000-record page; after three ordinary retries, that exact error
on a feature query permits the same bounded resizing. A verified retry returned all 500
IDs 96001–96500 at the unchanged cursor. After eight full pages below 4 MiB, a reduced
page can double toward its original cap. Repeated unsuccessful growth probes introduce
a 64-page cooldown, avoiding repeated expensive failures. Unrelated HTTP and malformed-data errors retain
their failure behavior. Count/metadata
reconciliation, immutable artifacts and complete export validation prevent silent truncation.
Same-count edits without updated publisher metadata cannot be detected as a transactional
snapshot; the recorded artifact is the reproducible observation.

The current official NSW RFS hosted BFPL service replaces the legacy MapServer through
versioned migration 063. The legacy service could not serialize one polygon even when queried
alone; the current service returned its 739 rings and 1,176,284 coordinate positions. Its
canonical record is 47,393,221 bytes. BFPL therefore has a profile-specific 64 MiB canonical
record limit; other reference profiles retain 16 MiB. No geometry simplification or omission
is used to fit these bounds. The checked-in source URL and adapter handle the hosted service's
`fid` identity, lower-case attributes and EPSG:3857 native CRS.

The hosted service also collapses one verified tiny native polygon to an empty shape during
server projection. For this source only, an empty projected polygon triggers a bounded native
re-fetch. Identical identity/attributes and EPSG:3857 are required before local conversion;
both original geometries are retained in `_propertyscope_geometry_provenance`. Empty or
malformed native shapes still fail. In a paired 1,000-feature comparison, only this known
record differed in ring/position counts. This is bounded evidence, not a claim that every
native vertex in the complete source equals the publisher's projected representation.

Reference ingestion streams canonical rows into COPY and performs provenance checks once per
import batch. Exports use indexed `(release, layer, record_id)` keyset pages of 100, reduced
to ten for BFPL, and serial projection. BFPL projection handles one row at a time; the page
reader can prefetch one additional page. These are finite record bounds, not a universal
memory guarantee for arbitrarily complex publisher geometries. A real ten-record BFPL
neighborhood containing the large polygon returned 47,493,075 response bytes. The public `/records`
view is only a preview; the gzip-NDJSON artifact contains the complete generation.

Use run task start/finish/progress and import phase timings to distinguish acquisition, COPY,
materialisation, export and queue time. Failed attempts and service-reload interruptions are
not clean throughput benchmarks. The
[live verification report](../reviews/feature-1-reference-live-e2e-2026-09-13.md)
records actual completed runs.

## Catalogue names and groups

Sources, Jobs and Data Products use the same six groups: Foundational property data,
Geography and boundaries, Planning and hazards, Community and amenities, Economic context,
and Development fixtures. G-NAF addresses and NSW property sale history (PSI) appear first
as the foundational records. Short display names and purpose descriptions improve scanning;
machine identifiers and operator-customized names remain stable. Grouping describes each
dataset's role, not whether the current machine has downloaded or accepted it.

## Capacity and recovery

The checked-in PostgreSQL capacity budget is 192 GiB (`206158430208` bytes). It is a declared
ceiling, not reserved disk. Physical data/WAL free space, the 16 GiB temporary-file bound,
4 GiB reserve and source-specific growth/WAL estimates are independently checked. An existing
explicit `.env` value overrides the new default; compare it before a full PSI replay. The
retained local 27 GB database plus PSI headroom exceeded the earlier 128 GiB budget.

After an idle worker's budget change, use `stack restart f1-db-api f1-db-loader`.
See the [large-data runbook](../release-0/feature-1-large-data-operations.md) for exact-operation
cancellation, storage recovery and retained-generation costs. Do not remove volumes to recover
a run. Explicit resume can requeue a retryable failed import after its cause is fixed, preserving
attempt evidence. A non-retryable quality failure requires a corrected new run. Original terminal errors and
later storage-recovery observations remain separate, append-only evidence. Historical upgrade
events whose attempt ownership cannot be proved are exposed as unattributed, rather than
attached to a guessed attempt.

## Validation

Run the canonical `uv run python scripts/check.py`. Deterministic tests require no publisher
access. The reference component suite exercises all ten profiles through HTTP, the runner,
PostgreSQL COPY, release construction, download verification and activation in a disposable
database, including a blocked publisher with another worker making progress. Real-source
validation is separate and compares complete record counts, geometry flags, bytes and SHA-256.
