# Feature 1 source-scale benchmark methodology

This document defines the disposable PSI/BOCSAR comparison gate. It is a methodology and result
template, not performance evidence. No benchmark results were executed or inferred when this file
was added.

## Safety and sequence

The harness in `scripts/source_scale_benchmark.py` generates deterministic real-shape synthetic
records. It never reads official artifacts or Feature 1 tables. Every repetition receives a fresh
`propertyscope_bench_*` schema and the harness attempts to drop that exact schema in `finally`.

Run order is mandatory:

1. plan and execute 100,000 input records;
2. complete at least three reset runs for every compared variant;
3. review successful cleanup, query plans, semantic fingerprints and resource counters;
4. supply that executed suite summary as the gate for 1,000,000 records;
5. run full/pinned data only through a separately approved acceptance workflow after the smaller
   gates pass.

One materialisation statement has both a PostgreSQL `statement_timeout` and client watchdog of 30
minutes. The watchdog reports backend wait state every five minutes and cancels the exact worker
connection at the deadline. Cancellation must roll back and cleanup must show the disposable schema
removed. A failed or cancelled run does not satisfy the next scale gate.

Use only a disposable PostgreSQL database. Execution requires both `--confirm-disposable` and the
exact connected database name via `--confirm-database`; a URL alone is insufficient.

## Commands

Planning is offline and deterministic:

```text
uv run python scripts/source_scale_benchmark.py plan --dataset psi --scale 100000 --repetitions 3
uv run python scripts/source_scale_benchmark.py plan --dataset bocsar --scale 100000 --repetitions 3
```

Execution example for a deliberately disposable database:

```text
uv run python scripts/source_scale_benchmark.py run --dataset psi --scale 100000 --repetitions 3 --database-url postgresql://USER:PASSWORD@HOST/propertyscope_benchmark --confirm-disposable --confirm-database propertyscope_benchmark
```

Before accepting cancellation evidence, run the explicit 100k cleanup drill. This substitutes a
bounded `pg_sleep` for target DML after building the selected real-shape preparation, cancels the
exact worker connection at the requested deadline, and succeeds only when every run is cancelled,
rolled back, and its schema is removed:

```text
uv run python scripts/source_scale_benchmark.py run --dataset psi --scale 100000 --variant typed-phases --repetitions 3 --force-cancel-after-seconds 2 --database-url postgresql://USER:PASSWORD@HOST/propertyscope_benchmark --confirm-disposable --confirm-database propertyscope_benchmark
```

After the 100k suite succeeds and is reviewed:

```text
uv run python scripts/source_scale_benchmark.py run --dataset psi --scale 1000000 --repetitions 3 --gate-evidence .propertyscope-runtime/source-scale-benchmarks/psi-100000-TIMESTAMP/suite-summary.json --database-url postgresql://USER:PASSWORD@HOST/propertyscope_benchmark --confirm-disposable --confirm-database propertyscope_benchmark
```

Outputs stay below `.propertyscope-runtime/source-scale-benchmarks/`, which is ignored by Git.
Do not copy credentials into summaries or command transcripts.

## Comparisons

PSI compares `jsonb-wide` with `typed-phases`. The generated shape includes exact retransmissions,
deterministic corrections, first-ordinal revision ordering, supplied property references, exact
eight-component address predicates and deliberately ambiguous registry addresses. The typed variant
separates staging, narrow identity, revisions and one-per-address resolution before the final fact
join. Its measured interval starts before identity derivation and ends after target insertion; the
wide JSONB interval performs those same identity, revision, address, and target responsibilities in
one statement. Setup-only staging is excluded from both elapsed figures.

BOCSAR compares `jsonb-ordered` with `typed-unordered`. Five percent of generated rows are distinct
coverage records with sorted observed-month arrays, first/last/count, explicit
`blank_means_observed_zero`, and completeness hashes. The remaining rows are sparse positive
observations with a distinct geography/category/month key. Missing observation rows therefore remain
different from observed zero coverage, and target cardinality grows with input scale. Both variants
insert the same observation and coverage targets; the comparison isolates typed staging and removal
of unproven ordinal ordering. It does not claim semantic equivalence with official data.

## Evidence captured

Each successful run retains the complete JSON `EXPLAIN (ANALYZE, BUFFERS, WAL, SETTINGS, SUMMARY)`
and a bounded flattened node list with per-node temp read/write blocks. Run summaries include:

- elapsed seconds and input rows/second;
- setup/materialisation/cleanup phase timings;
- PostgreSQL database temp-byte/file, block and transaction counter deltas;
- WAL record/byte/FPI/buffer-full deltas;
- checkpoint counter and timing deltas;
- before/after `pg_stat_io` snapshots plus bounded counter deltas grouped by backend type, object,
  and context;
- backend state, wait event and an explicit `active with no wait` CPU/running inference at start and
  each five-minute interval;
- per-relation heap, index and total bytes before and after the complete measured interval, with
  separate growth deltas;
- result row count and deterministic identity fingerprint;
- cancellation, rollback, temporary-file observations, schema drop and remaining-schema evidence.

Statistics are cluster-wide or database-wide where PostgreSQL exposes them that way. Run this in an
otherwise idle disposable database and do not over-attribute concurrent activity. `cpu_or_running`
is not CPU utilisation; it only records an active backend with no reported wait event.

## Disposable validation result — 30 August 2026

The corrected suite ran in an otherwise idle `postgis/postgis:16-3.4` disposable database. Every
variant used three fresh schemas at each scale; all 24 successful-run schemas were dropped. Both
100k forced-cancellation suites also completed three exact-backend cancellations, observed rollback
and removed every schema. The raw summaries and plans remain in the ignored local evidence folders:

- `psi-100000-20260830T094159Z` and `bocsar-100000-20260830T094305Z` (cancellation);
- `psi-100000-20260830T094349Z` and `bocsar-100000-20260830T094421Z` (100k);
- `psi-1000000-20260830T094455Z` and `bocsar-1000000-20260830T094758Z` (1m).

Elapsed time is the complete measured identity/address/target interval described above, not only
the final insert. Temp and WAL values are database/cluster counter deltas and should be treated as
capacity evidence from the isolated host. Heap and index growth are reported separately.

| Dataset | Scale | Variant | Median elapsed | Temp bytes | WAL bytes | Heap growth | Index growth | Result rows | Verdict |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| PSI | 100k | jsonb-wide | 2.156 s | 240,774,701 | 102,092,098 | 21,848,064 | 2,113,536 | 66,667 | Baseline |
| PSI | 100k | typed-phases | 1.250 s | 8,027,328 | 80,475,018 | 28,663,808 | 3,612,672 | 66,667 | Accept |
| PSI | 1m | jsonb-wide | 22.968 s | 2,417,381,779 | 1,019,876,561 | 218,439,680 | 21,118,976 | 666,667 | Baseline |
| PSI | 1m | typed-phases | 12.157 s | 434,842,343 | 804,974,872 | 285,040,640 | 27,254,784 | 666,667 | Accept |
| BOCSAR | 100k | jsonb-ordered | 1.578 s | 23,119,888 | 113,021,262 | 22,986,752 | 8,347,648 | 100,000 | Baseline |
| BOCSAR | 100k | typed-unordered | 1.579 s | 6,424,592 | 77,669,023 | 22,986,752 | 8,347,648 | 100,000 | Accept |
| BOCSAR | 1m | jsonb-ordered | 17.719 s | 244,355,232 | 1,140,327,606 | 229,834,752 | 76,619,776 | 1,000,000 | Baseline |
| BOCSAR | 1m | typed-unordered | 18.563 s | 145,076,384 | 773,393,528 | 229,834,752 | 76,619,776 | 1,000,000 | Accept with trade-off |

All repetitions at a dataset/scale produced identical target fingerprints across variants. PSI
retained the required retransmission, revision and address-resolution shape. BOCSAR retained
950,000 sparse observations plus 50,000 coverage rows at 1m, including missing-versus-zero evidence.
The typed BOCSAR plan is about 4.8% slower at 1m, but removes plan-dependent duplicate retention and
reduces median temp bytes by about 40.6% and WAL by about 32.2%; it is accepted for those bounded
resource and determinism gains, not as an elapsed-time improvement.

The 100k-to-1m scaling factor is about 9.7 for typed PSI and 11.8 for typed BOCSAR. Applying the 1m
median to the official input count and then a 2.5 safety factor gives a conservative materialisation
gate of 4 minutes for 7.4m PSI and 10 minutes for 10.1m BOCSAR. The same conservative calculation
keeps projected temp use below 8 GiB for PSI and 4 GiB for BOCSAR. These are watchdog budgets for a
separately observed official run, not end-to-end duration or official semantic-equivalence claims;
the absolute 30-minute ceiling still applies.

Migration 039 currently builds the exact-address expression index over 30 retained registry rows;
the measured index is 16 KiB and migrations 038/039 completed within the same one-second timestamp.
This does not establish source-scale online-build behaviour. Before `registry.property` is allowed
to grow to source scale, the migration runner needs a concurrent index-build/swap policy and a
capacity/read-availability benchmark. That P2 follow-up is tracked here rather than overstated as
current 5.19m-row evidence.

Two proposed alternatives are deliberately deferred rather than implied by these results. A PSI
prepared-order index would add write amplification solely to reproduce a final order that the
destination contract does not require; it needs a consumer query demonstrating that order before a
benchmark variant is warranted. BOCSAR bulk index construction would require disposable
release-scoped destination tables or partitions, which the current one-transaction shared tables do
not provide. Benchmark that alternative only together with an approved release-storage design; do
not disable or defer maintenance of current production indexes to manufacture a favourable result.
