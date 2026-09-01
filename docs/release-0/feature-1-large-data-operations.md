# Feature 1 large-data loading and publication operations

This runbook covers the complete G-NAF, PSI, BOCSAR and schools paths. It supplements the normal
commands in `student-1/README.md`; it does not bypass quality checks or human publication review.

## Expected lifecycle

Acquisition and canonical import are asynchronous already:

```text
runner artifact -> ops.import_operation (202) -> serial f1-db-loader -> candidate
human review -> consumer receipt -> ops.release_activation (202)
             -> serial f1-db-loader -> short accepted-generation pointer transaction
```

Feature 1's own complete artifact was schema-validated and content-hashed while it was built. The
publish request checks that immutable artifact's durable binding and queues the activation; it does
not rescan the complete gzip stream. Browser retries retain the same request key while the outcome
is unknown, and the database coalesces another request for the same nonterminal release/version.
The loader then streams the physical export to recheck its registered byte size and SHA-256 while
renewing the activation lease. Missing or corrupt bytes fail before warehouse materialisation or the
accepted-pointer transaction.

The current accepted generation remains visible during every long-running step. A browser timeout
must not be treated as publication success; inspect the release activation instead.
Activation submission returns `202` only for queued or recoverable work, `200` when a competing
activation already completed, and a structured `409 release_activation_failed` when the durable
winner failed. The browser clears the attempt key after that known failure so a fresh retry is safe.

## Safe service recovery

Preserve PostgreSQL and all named volumes. Restart only the database API after a source-only API or
migration change:

```text
uv run scripts/dev.py stack rebuild f1-db-api --offline
```

Restart the two code owners of the asynchronous activation path after loader changes:

```text
uv run scripts/dev.py stack rebuild f1-db-api f1-db-loader f1-backend --offline
```

Do not use `stack reset`, delete the PostgreSQL volume, or restart PostgreSQL to resolve a slow
publication. First identify the exact query and client.

## Triage sustained PostgreSQL writes

Check containers and cumulative block I/O:

```text
docker stats --no-stream ps-dev-f1-postgres-1 ps-dev-f1-db-api-1 ps-dev-f1-db-loader-1
```

Inspect active statements from inside the database container without printing credentials:

```text
docker exec ps-dev-f1-postgres-1 sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -P pager=off -c "SELECT pid,client_addr,backend_type,state,wait_event_type,wait_event,now()-query_start AS age,left(query,200) AS query FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid() ORDER BY query_start;"'
```

An active application statement is different from cleanup after a cancelled statement.
`autovacuum: VACUUM ...` and checkpoint activity may continue increasing the cumulative block-I/O
counter while PostgreSQL reclaims dead tuples. Let that cleanup finish unless disk capacity is at
immediate risk. Stop or terminate only an exact confirmed application culprit; never target all
database sessions.

Supported cancellation is idempotent. The first request durably sets `cancel_requested_at`; a
retry after a lost or dependency-failure response reads that durable run and returns the same
cancelled/requested outcome. The database loader watches that exact operation and calls PostgreSQL
cancellation on its own connection, so an operator must not find and cancel an unrelated backend.
Cancellation intent commits before child-task cleanup and does not take `FOR UPDATE` on the run:
source-scale inserts hold a foreign-key key-share lock on that row for their transaction, and a
strong parent-row lock would make cancellation wait behind the statement it must interrupt.
Worker acknowledgement abandons only draft/candidate releases in the same terminal transaction,
and a repeated cancellation request reruns that bounded cleanup even when the run is already
cancelled. A crash after the intent commit therefore cannot strand a manually actionable candidate.
If neither the cancellation response nor a reconciliation read proves persistence, the public API
returns `cancellation_unconfirmed` and the same request may be retried safely.

Import progress uses stable phase keys: `artifact_verification`, `typed_staging`,
`identity_revision_derivation`, `address_resolution`, `target_materialisation`, and
`verification`. Publication activation uses `artifact_verification`, `materialisation`, and
`commit_pointer`. Byte and row totals are shown only for phases that can be measured; a null total
means the remaining set operation is indeterminate, not complete.

## Inspect publication progress

Open the release under **Published data**. The **Background publication** panel shows queued,
claimed, running, interrupted, failed or succeeded activation evidence. The same evidence is in
the release detail response under `activations`.

- `queued`: durable and waiting for the serial loader;
- `claimed`/`running`: loader owns a renewable lease;
- `interrupted`: safe to reclaim; the accepted pointer did not move;
- `failed`: inspect the bounded error and start a new reviewed publication operation after fixing
  the cause;
- `succeeded`: release and accepted-generation pointer committed together.

For G-NAF, accepted-only index population can remain source-scale. Its warehouse transaction is
separate from the short activation marker transaction, so the renewable lease heartbeat continues
during the update. If the loader stops after the warehouse commit but before `materialized_at`, the
next attempt safely updates only rows still marked unpublished and then records the marker.

The loader prioritizes a queued activation before claiming another bulk import. A lost live lease
is recovered up to three total attempts. Lease-heartbeat failure cancels the materialization
connection before another worker may recover it.

## Performance checks

PSI and BOCSAR use typed temporary staging and transaction-local source phases. The loader casts
canonical values once before COPY, ANALYZEs planner-sensitive staging and narrow PSI identity and
address tables, and enforces a loader-only `temp_file_limit`. Before COPY it observes the immutable
artifact filesystem separately, then asks PostgreSQL for both
`pg_database_size(current_database())` and physical free bytes on its data and WAL filesystems. The
physical observation is one fixed server-side command containing no request or configured path
interpolation; the loader never mounts the database volume. An unavailable observation fails closed.
Artifact free space is never treated as database capacity because materialisation only reads the
already-complete artifact.

The loader database role must be a PostgreSQL superuser or hold the predefined
`pg_execute_server_program` role required by `COPY FROM PROGRAM`. Provision that capability only
through reviewed database-role configuration; it is not granted by the application. If the role
lacks it, the command fails, preflight reports
`loader_database_filesystem_capacity_unavailable`, and no source COPY or materialisation begins.
Operators must correct the role or server observation rather than substituting artifact-filesystem
free space or a declared-capacity estimate.

The local Compose default declares a conservative 64 GiB Feature 1 PostgreSQL capacity budget,
16 GiB of transaction-local temporary files and a 4 GiB reserve. PSI additionally reserves 6 GiB
for relation/index growth and 16 GiB for WAL; BOCSAR reserves 8 GiB and 20 GiB respectively. These
floors project the largest observed one-million-row counters to the known source counts with a 2.5
safety factor and round upward. The 3x artifact growth allowance remains for other profiles and wins
for PSI/BOCSAR only when it is larger than the measured floor. Preflight requires both the physical
server observation and current database size against the declared ceiling to cover every applicable
allowance. Override the corresponding `PROPERTYSCOPE_LOADER_*` or
`PROPERTYSCOPE_POSTGRES_CAPACITY_BYTES` variables only from measured evidence. The disposable
benchmark sequence and evidence fields are specified in
[`source-scale-benchmark-methodology.md`](source-scale-benchmark-methodology.md).

With complete source generations retained, verify the public path rather than counting entire
tables manually:

```text
curl --silent --output /dev/null --write-out "%{http_code} %{time_total}s\n" http://localhost:5200/api/data-platform/v1/overview
curl --silent --output /dev/null --write-out "%{http_code} %{time_total}s\n" "http://localhost:5200/api/data-platform/v1/properties/search?q=Parramatta&limit=25"
```

Release previews remain bounded to 100 rows. Overview derives its property count from accepted
release evidence rather than scanning the multi-million-row registry. Search and detail use the
accepted warehouse generation's expression indexes. If a query regresses, capture
`EXPLAIN (ANALYZE, BUFFERS)` on a representative retained generation and verify it uses
`gnaf_address_search_document_trgm_idx` or `gnaf_address_stable_property_ref_idx`.

Numeric-only searches do not use trigram matching: short values such as `11` use the structured
`street_number_first` column and four-digit values use `postcode`. The accepted-generation indexes
`gnaf_address_release_street_number_idx` and `gnaf_address_release_postcode_idx` keep those lookups
bounded. On the accepted 5,190,134-row generation, the public `11` search fell from about 29 seconds
to about 29 ms and returned a bounded first page of real NSW addresses.

PSI address resolution deduplicates eligible address components directly from its typed import
stage. It does not join the multi-million-row identity ledger back to the same stage before exact
matching. Final materialisation uses the generated first-row ordinal as its single join key; the
business key and row hash remain immutable evidence in the selected row rather than duplicate join
work. Keep the accepted-generation exact-address index from migration 044 in place when measuring
this phase.

Search intentionally returns a bounded result page plus `total_is_lower_bound`; it does not run an
exact count across every fuzzy match. On the retained 5,190,134-row G-NAF generation, the exact
multi-token `11 example street` plan used the trigram index and executed in about 3.5 ms after the
bounded-search change. Search also anti-joins legacy registry rows whose stable reference is owned
by the accepted warehouse generation, so a search result and subsequent detail lookup cannot
describe different addresses under the same reference.

## Capacity notes

Complete candidate generations intentionally consume source-scale storage. Publication no longer
duplicates every accepted G-NAF row into three serving/registry structures and never persists a
derivable property UUID back into the immutable warehouse table. Search indexes require a bounded
one-time build only during reviewed activation; candidate imports do not maintain them. Retention of
old complete generations should be decided explicitly before unattended repeated full refreshes are
scheduled.

## Complete artifact and preview semantics

The release artifact is the complete deterministic generation export in gzip NDJSON. The record
view in the browser and `/records` API is a bounded preview (maximum 100 rows per page), not an
export and not a statement that the release is truncated. Licence-controlled artifacts retain
their full hash/count/size evidence but remain unavailable to anonymous download.

## Cancelled candidates and artifact retention

Failed or cancelled ingestion-owned candidates are migrated and reconciled to `abandoned`. They
remain linked from the run for audit but do not appear in the normal Published data workflow.

When a database import fails or is cancelled after opening its transaction, its operation is also
marked `space_recovery_status=needed` with an exact, profile-derived relation list and the
`measure_then_target_exact_relations` policy. This is an operator-visible recovery obligation, not
an automatic `VACUUM FULL` or broad reindex. Measure dead tuples and allocated bytes first; PR2's
source-scale benchmark evidence determines whether an exact relation needs bounded vacuum/reindex.
Typed temporary PSI/BOCSAR work drops automatically at transaction end. After the failure outcome
is durable, the serial loader measures only the import profile's registered destination relations,
runs `VACUUM (ANALYZE, INDEX_CLEANUP ON)` outside a transaction with a ten-minute per-statement
ceiling only when durable phase evidence shows target materialisation or verification began,
measures again, and records `completed`. A preflight or typed-stage failure skips VACUUM. Measured
source-scale rollback bloat (at least 100,000 dead tuples, at least 25% as many dead as live tuples,
and at least 64 MiB of retained indexes) additionally triggers bounded exact-table
`REINDEX TABLE`. This atomic form may briefly block queries but cannot strand invalid concurrent
reindex artifacts on timeout; it is restricted to measured rollback bloat. The pre-VACUUM
measurement durably records pending exact relations before VACUUM changes tuple statistics, and
bounded failure evidence remains durable so the operator endpoint can safely retry after the
lock/space condition is resolved. This makes aborted pages reusable without a
blocking `VACUUM FULL`, table rewrite or broad-schema maintenance. Timeout or unavailable relation
leaves the durable marker at `needed` for a later safe retry.

The PR1 disposable PostgreSQL cancellation test proves transaction rollback and transaction-local
table cleanup at every PSI materialisation boundary. Executor spill-file size and `pgsql_tmp`
cleanup require a forced-spill workload and are therefore a tracked PR2 benchmark measurement, not
claimed by the small reliability fixture.

`GET /api/data-platform/v1/artifact-retention` reports each referenced physical object, retained
bytes, reference count, run states and retention reason. Cleanup is explicit and dry-run by
default:

```text
POST /api/data-platform/v1/artifact-retention
{"grace_days": 7, "dry_run": true}
```

Set `dry_run` to `false` only after reviewing the returned keys. Cleanup considers an object only
when no artifact ledger record references its content-addressed storage key and its modification
time is older than the grace period. Source-cache, candidate, cancelled/failed-run, accepted and
superseded evidence therefore remains protected while referenced. Incomplete `artifact-*` files
are removed immediately by the atomic writer on cancellation or failure.

## Targeted remediation for pre-031 development volumes

Migrations 031 and 032 terminalize empty cancelled/failed candidates, separate physical artifact
deduplication from lineage, add durable progress, and replace G-NAF's global serving indexes with
accepted-row partial indexes. This targeted index replacement is the approved remediation for the
historical development volume; do not run `VACUUM FULL`, reset the volume, or reindex unrelated
schemas. After migration, inspect exact sizes with:

```text
docker exec ps-dev-f1-postgres-1 sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -P pager=off -c "SELECT indexrelid::regclass AS index,pg_size_pretty(pg_relation_size(indexrelid)) AS size FROM pg_stat_user_indexes WHERE schemaname=\$\$warehouse\$\$ AND relname=\$\$gnaf_address\$\$ ORDER BY pg_relation_size(indexrelid) DESC;"'
```

Autovacuum removes aborted heap tuples and checkpoints make committed pages durable; neither is
expected to shrink an already enlarged index file. The accepted-only index migration is what
reclaims that persistent index allocation. Candidate imports still maintain the compact generation
primary key required for deterministic keyset export; PostgreSQL can reuse its aborted B-tree pages,
while the historically dominant GIN/GiST/lookup indexes receive no candidate entries.
