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

The current accepted generation remains visible during every long-running step. A browser timeout
must not be treated as publication success; inspect the release activation instead.

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

The loader prioritizes a queued activation before claiming another bulk import. A lost live lease
is recovered up to three total attempts. Lease-heartbeat failure cancels the materialization
connection before another worker may recover it.

## Performance checks

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

Search intentionally returns a bounded result page plus `total_is_lower_bound`; it does not run an
exact count across every fuzzy match. On the retained 5,190,134-row G-NAF generation, the exact
multi-token `11 example street` plan used the trigram index and executed in about 3.5 ms after the
bounded-search change. Search also anti-joins legacy registry rows whose stable reference is owned
by the accepted warehouse generation, so a search result and subsequent detail lookup cannot
describe different addresses under the same reference.

## Capacity notes

Complete candidate generations intentionally consume source-scale storage. Publication no longer
duplicates every accepted G-NAF row into three serving/registry structures and never persists a
derivable property UUID back into the immutable warehouse table. Search indexes still require
bounded one-time build and per-import maintenance. Retention of old complete generations should be
decided explicitly before unattended repeated full refreshes are scheduled.
