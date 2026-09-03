# PSI accepted-identity materialisation evidence — 3 September 2026

This attests six disposable executions of the production PSI identity, address-resolution and
target-materialisation SQL after ADR-038 and migration 049. It supports recovery of the retained
638,125-row, 2023–2025 publisher-year candidate. It does not establish full-history performance.

## Environment and workload

Each repetition created a fresh database on an isolated `postgis/postgis:16-3.4` server with its own
disposable storage, applied the complete migrations through 049, and generated synthetic source
records. No retained application database, production volume or official artifact was used. All six
databases were dropped; a final database-catalogue query found no remaining benchmark databases.

The workload includes one unique sale per input row: 80% resolve to distinct accepted, published
G-NAF identities, 5% retain supplied references, 5% have ambiguous addresses, 5% are unmatched and
5% have unusable house-number text. G-NAF uses `STREET` and PSI retains `ST`. The complete migrated
schema exercises the actual spatial/search indexes, provenance inserts and foreign-key triggers.
Every 100k run retained 100,000 sales, linked 85,000, and created 80,000 anchors; every 1m run retained
1,000,000 sales, linked 850,000, and created 800,000 anchors. Every source street-type value remained
unchanged. Deterministic correctness tests separately cover retransmissions, revisions, replay,
transaction rollback, and accepted-generation changes.

The measured interval starts before production identity derivation and ends after target insertion
and its constraint triggers. It includes intermediate `ANALYZE` operations. Source generation,
migrations and canonical staging are excluded. Each statement had a 1,800-second PostgreSQL timeout;
all completed. Target statements retain `EXPLAIN (ANALYZE, BUFFERS, WAL, SETTINGS, SUMMARY)` plans.
The 1m suite ran only after three successful, cleaned 100k runs.

## Measured results

| Input rows | Run | Identity (s) | Address (s) | Target (s) | Total (s) | Relation growth (bytes) | WAL (bytes) |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 100,000 | 1 | 0.625 | 2.546 | 17.485 | 20.656 | 132,980,736 | 284,778,672 |
| 100,000 | 2 | 0.515 | 2.125 | 14.657 | 17.297 | 132,956,160 | 285,753,216 |
| 100,000 | 3 | 0.485 | 2.109 | 15.828 | 18.422 | 132,931,584 | 284,927,240 |
| 1,000,000 | 1 | 3.907 | 20.297 | 169.937 | 194.141 | 1,309,188,096 | 3,439,926,728 |
| 1,000,000 | 2 | 3.843 | 20.360 | 169.172 | 193.375 | 1,309,171,712 | 3,429,015,120 |
| 1,000,000 | 3 | 4.937 | 18.531 | 150.000 | 173.468 | 1,309,179,904 | 3,429,919,576 |

Relation growth sums `registry.property`, `registry.property_identifier`, and `warehouse.psi_sale`,
including their indexes. The largest 1m growth comprises 438,927,360, 359,587,840 and 510,672,896 bytes
respectively. WAL is the server insert-LSN delta across staging/materialisation on this isolated
server. Each 1m target plan recorded 462,741,504 temporary bytes written; that plan counter does not
include the earlier identity/address statements.

The separate provenance-guard probe populated 100,000 identifiers. The existing `is_current` index
could not serve the all-history `scheme='gnaf_pid'` guard: its negative lookup scanned 100,000 rows
in 5.602 ms. Migration 049's partial property-reference index used an index-only scan in 0.028 ms.

## Capacity and recovery budget

Using the largest 1m resource counters, the documented 7.4m source planning count and a 2.5 safety
factor projects **22.557 GiB** of relation growth and **59.268 GiB** of WAL. PSI preflight therefore
reserves **24 GiB growth and 64 GiB WAL**, alongside the unchanged 16 GiB temporary-file allowance
and 4 GiB reserve. The declared capacity must additionally cover the existing database. A 128 GiB
declaration fits a retained database of approximately 6 GiB; physical data/WAL capacity must pass
its independent observation. The default 64 GiB declaration fails this PSI preflight deliberately.

For the requested 638,125-row candidate, the largest measured elapsed time gives
`194.141 × 0.638125 × 2.5 = 309.716 seconds`. Use a **six-minute materialisation budget** for that
observed recovery, while retaining the hard 30-minute statement ceiling. This budget excludes
artifact verification, acquisition and release compression, and is not a browser ETA.

Applying the same timing margin to 7.4m records yields approximately **59.9 minutes**. These results
therefore do **not** validate an all-history run against the 30-minute ceiling. The earlier
registry-only four-minute full-history estimate is superseded for this path. Capacity floors do
not constitute performance approval; a full-history attempt needs further bounded performance
work and review.

## Retained evidence

Raw evidence remains under the ignored `.propertyscope-runtime/f1-ui-fix/` directory:

| Artifact | SHA-256 |
| --- | --- |
| `psi-benchmark-indexed-100000/summary.json` | `9d44bcd2e791a5342f723e1afff8de8eb6f21c9e8e1945eeb105a0b1199b7ba0` |
| `psi-benchmark-indexed-1000000/summary.json` | `e4af78bb87daa42f96bb9d1fbf78d6a6f837729bde91498167d4004e7532f6fe` |
| `psi_link_benchmark.py` | `f873780360a1ee51ba77f8cd87c50a3eecae41de1a04d0086ac04c94f2c66e2c` |
| Executed `source_materialisation.py` | `e544ad4d4c18593629b154161e66e41afb9d901e487802c42928098453ec006e` |

| Target plan | SHA-256 |
| --- | --- |
| 100k, run 1 | `bced5d49b6fdb78e3bc93b1643a998400263bc2648e52ae75fa31258d3e6b9a1` |
| 100k, run 2 | `3da6ae4134a17c308ec550f5a5e2b2de94220d5b855420bdeb9584e815c3dfc4` |
| 100k, run 3 | `7c80000f76a70ea9cf25d8db34dc5666e960dc38ee25a4425c7b97a6dbec9b0c` |
| 1m, run 1 | `a601402cfb8d2c0d4abf4bd192b6814d1d2cc564fdce7a399b700b1f3e45bf0b` |
| 1m, run 2 | `f2629f82f06f44af5633024421b1f50c532051593b0749783f23a30b16554f61` |
| 1m, run 3 | `0bc6a06ba67d7fc814508f2456742388154b9c95ee30a0fa80967b89111b7533` |
