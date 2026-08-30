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
join.

BOCSAR compares `jsonb-ordered` with `typed-unordered`. The shape retains explicit zero counts,
coverage presence, geography/category/month keys and a wide payload. The comparison isolates typed
staging and removal of ordinal ordering; it does not claim semantic equivalence with official data.

## Evidence captured

Each successful run retains the complete JSON `EXPLAIN (ANALYZE, BUFFERS, WAL, SETTINGS, SUMMARY)`
and a bounded flattened node list with per-node temp read/write blocks. Run summaries include:

- elapsed seconds and input rows/second;
- setup/materialisation/cleanup phase timings;
- PostgreSQL database temp-byte/file, block and transaction counter deltas;
- WAL record/byte/FPI/buffer-full deltas;
- checkpoint counter and timing deltas;
- before/after `pg_stat_io` snapshots;
- backend state, wait event and an explicit `active with no wait` CPU/running inference at start and
  each five-minute interval;
- relation/index bytes before and after materialisation;
- result row count and deterministic identity fingerprint;
- cancellation, rollback, temporary-file observations, schema drop and remaining-schema evidence.

Statistics are cluster-wide or database-wide where PostgreSQL exposes them that way. Run this in an
otherwise idle disposable database and do not over-attribute concurrent activity. `cpu_or_running`
is not CPU utilisation; it only records an active backend with no reported wait event.

## Disposable validation result — 30 August 2026

These medians are from three reset runs per variant in the isolated
`postgis/postgis:16-3.4` container `propertyscope_benchmark`; no retained Feature 1 database or
official artifact was used. `Temp bytes` is the database counter delta for the complete run,
including setup and materialisation. WAL and other counters are cluster-wide, but the disposable
database was otherwise idle. Raw bounded plans and summaries remain in the ignored local
`.propertyscope-runtime/source-scale-benchmarks/` evidence directory.

| Dataset | Scale | Variant | Reset runs | Median elapsed | Rows/s | Temp bytes | WAL bytes | Relation growth | Result fingerprint | Cleanup | Verdict |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |
| PSI | 100k | jsonb-wide | 3 | 1.59 s | 62,735 | 232,081,325 | 99,712,023 | 23,986,176 | `6dca21a3...` | 3/3 schemas dropped | Baseline |
| PSI | 100k | typed-phases | 3 | 0.52 s | 193,798 | 3,218,624 | 53,559,217 | 25,485,312 | `6dca21a3...` | 3/3 schemas dropped | Accept |
| BOCSAR | 100k | jsonb-ordered | 3 | 0.61 s | 164,204 | 1,400,000 | 50,818,844 | 1,548,288 | `5099acee...` | 3/3 schemas dropped | Baseline |
| BOCSAR | 100k | typed-unordered | 3 | 0.48 s | 206,186 | 1,400,000 | 32,005,316 | 1,548,288 | `5099acee...` | 3/3 schemas dropped | Accept |
| PSI | 1m | jsonb-wide | 3 | 18.17 s | 55,030 | 2,329,852,851 | 995,888,894 | 239,632,384 | `66b76e83...` | 3/3 schemas dropped | Baseline |
| PSI | 1m | typed-phases | 3 | 6.09 s | 164,123 | 560,647,656 | 970,741,313 | 245,784,576 | `66b76e83...` | 3/3 schemas dropped | Accept |
| BOCSAR | 1m | jsonb-ordered | 3 | 6.11 s | 163,693 | 14,000,000 | 488,720,595 | 1,548,288 | `5099acee...` | 3/3 schemas dropped | Baseline |
| BOCSAR | 1m | typed-unordered | 3 | 4.72 s | 211,909 | 14,000,000 | 300,445,982 | 1,548,288 | `5099acee...` | 3/3 schemas dropped | Accept |

At one million inputs the PSI typed variant retained the same 666,667-row identity fingerprint,
reduced median materialisation from 18.17 to 6.09 seconds and reduced complete-run database temp
bytes by about 76%. Its measured flattened plan wrote 145,415 temporary blocks versus 2,893,319
for the baseline; flattened node totals may double-count parent and child reporting, so the database
counter is the capacity measure. BOCSAR retained the same 5,400-key result at both scales because
the generator intentionally repeats a bounded geography/category/month key space; it still scans
all inputs but does not model growth in distinct destination keys. Its typed variant reduced the 1m
median from 6.11 to 4.72 seconds and WAL from about 489 MB to 300 MB.

Linear extrapolation from the accepted 1m variants predicts about 45 seconds for 7.4m PSI inputs
and 48 seconds for 10.1m BOCSAR inputs on this disposable host. This clears the 30-minute
materialisation budget for a separately observed pinned-source run, but it is not an end-to-end
official-source duration claim. A faster plan with changed semantics, incomplete cleanup or a
timeout remains rejected.
