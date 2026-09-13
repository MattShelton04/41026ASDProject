# Feature 1 PSI matching: complete-source validation, 13 September 2026

The unpublished review candidate links **5,422,398 of 7,402,643 accepted input source revisions**,
compared with **4,940,715** existing links. It recovers **481,683 revisions**: linkage rises
from **66.7426% to 73.2495%**, an increase of **6.5069 percentage points**. This accounts for
19.5653% of the previously unmatched revisions. **No existing link is lost or changed.**

These totals were first established by a complete-generation counterfactual inside Feature
1's owning PostgreSQL service, using transaction-local tables and a rollback. They are now
independently confirmed by the complete supported cached replay, persisted quality checks,
source-preservation comparison and byte-level export validation below. The candidate is
**awaiting review**; accepted pointers and downstream features remain unchanged.

## Sources and diagnosis

The comparison uses the accepted PSI generation `a7078066-1bde-4b31-8b4d-4acab03939e6`
and accepted G-NAF generation `291863ec-a12d-4a03-a80c-8f334feae2d0`, whose retained source
is February 2026. It does not claim that either source is the latest publisher edition.

The old matcher rejected **369,830 otherwise simply numbered addresses** because their
street type was outside a small vocabulary. Examples include `CCT`, `WAY`, `BVD` and `GR`.
It also rejected **418,490 complex house-number strings**. Many were harmless publisher
spacing (`158 A`, `81 - 83`), alongside genuinely unsupported forms such as `LOT 310`.

The expanded vocabulary is explicit and checked against the NSW SIX
[Road Name Types catalogue](https://maps.six.nsw.gov.au/sws/AddressLocation.html).
Unknown abbreviations are not guessed. The original PSI street text, house text, derived
source components, source-row hashes and revision identity remain unchanged: matching derives
its additional comparison components inside temporary SQL tables. Existing verified canonical
Parquet/NDJSON artifacts therefore benefit through supported cached replay.

| Source era / original address kind | All revisions | Previously linked | Linked by improved matcher | Recovered | Ambiguous, still unresolved |
| --- | ---: | ---: | ---: | ---: | ---: |
| Post-2001, complex house | 239,743 | 0 | 197,574 | 197,574 | 1,047 |
| Post-2001, no house | 318,083 | 0 | 0 | 0 | 0 |
| Post-2001, other | 4,582,411 | 3,917,457 | 3,917,457 | 0 | 18,803 |
| Post-2001, unrecognised type | 273,389 | 0 | 187,292 | 187,292 | 549 |
| Pre-2001, complex house | 178,747 | 0 | 80,696 | 80,696 | 863 |
| Pre-2001, no house | 374,994 | 0 | 0 | 0 | 0 |
| Pre-2001, other | 1,338,835 | 1,023,258 | 1,023,258 | 0 | 2,545 |
| Pre-2001, unrecognised type | 96,441 | 0 | 16,121 | 16,121 | 1 |
| **Total** | **7,402,643** | **4,940,715** | **5,422,398** | **481,683** | **23,808** |

"Other" includes missing postcode/locality and addresses that already met the old simple
house/street-type grammar. These categories describe the original input shape; they do not
independently diagnose every remaining mismatch. The remaining **1,980,245 unmatched revisions**
are preserved. Historical address changes, missing or ambiguous identity, and fields absent
from the current G-NAF projection remain limitations requiring separate evidence.

## False-match defenses and quality review

- Full postcode, locality, street, first number, last number, suffix and unit equality remain
  required. Only accepted, published G-NAF addresses can contribute its identity candidates.
- A match must identify exactly one property. Ambiguous G-NAF candidates cannot fall back
  to legacy registry anchors; stale G-NAF anchors remain excluded.
- House grammar permits spaces around a single suffix or range separator. It rejects LOT
  text, separated digits, slash units, extra ranges and last-number suffixes that the current
  typed model cannot represent. Typed first/last numbers must agree with raw house text.
- Raw house text is included in the resolution key. A recovered `10 A` cannot leak into an
  unsuffixed `10` row whose legacy derived components happen to look the same.
- No locality-only/fuzzy matching, unit inference, range containment, or unverified
  PSI-property-ID propagation is introduced. Preserved G-NAF parcel/property identifiers
  would need their own validated correspondence before use.
- Quality evidence now reports the matching version, linked/unmatched counts and fraction.
  Any unmatched coverage produces an explicit review warning. Zero links, or lost/changed
  links for an identical accepted business key/revision/source hash, produce a blocking
  result. Changed source revisions are not claimed to be covered by that regression check.

The full comparison verifies consistency with existing links and the deterministic matching
rules. It is not an independently labelled accuracy study, and exact modern address equality
does not prove historical parcel continuity.

## Runtime and reproducibility

Run from the repository root while the owning database is available:

```text
uv run python scripts/audit_feature1_psi_matching.py
uv run python scripts/audit_feature1_psi_matching.py --sample-percent 1
uv run python scripts/audit_feature1_psi_matching.py --sample-percent 1 --explain
```

The optional repeatable block sample is explicitly labelled and is not used to extrapolate
the complete counts above. `--sql-only` exposes the complete temporary-table diagnostic for
review. Each statement has a 300-second limit; only application SELECTs and temporary-table
work are performed, followed by rollback. PostgreSQL does not permit TEMP CTAS within a
READ ONLY transaction, so the enclosing transaction must allow temporary staging.

The complete diagnostic took approximately **241 seconds** on the retained local database
with its existing **4 MB work_mem** setting:

| Phase | Elapsed |
| --- | ---: |
| Group 7,402,643 revisions into 3,877,552 weighted address/era/baseline-link rows | 38.3 s |
| Derive 3,142,558 distinct eligible address keys | 44.5 s |
| Build and join exact address dictionaries | 105.7 s |
| Compare and aggregate all weighted source revisions | 49.7 s |

Minor identity staging and ANALYZE statements account for the remainder. These times measure
the diagnostic, not a complete 7.4-million-row candidate load/export or downstream import.

Real-source testing found a planner hazard before replay: raw/typed-number consistency
predicates made PostgreSQL estimate one eligible address, choosing a very expensive nested
loop. That prototype was cancelled after 261 seconds on the sample, without a result. The
final matcher materializes and analyzes eligible keys before dictionary joins. It uses a
hashable street-token catalogue and a generated constant CASE for G-NAF type equivalences,
and limits G-NAF dictionary construction to streets present in eligible PSI addresses.
The resulting full-generation plan completes and retains identical match semantics.

A later attempt to benchmark the actual pre-change matcher from commit
`aabbac0b793587fb71b493d7e8bb3b45f608b628` was stopped to free the database for concurrent
source imports. Its weighted staging took 73.7 seconds and its resolution statement had run
for 182.8 seconds when cancelled. No result or complete old-versus-new speedup is claimed;
background acquisition and different elapsed staging also prevent treating these as a
controlled performance comparison.

The retained accepted-parent operation records 26m10.458s for the full prior import and its
build task records 7m18.503s for export on 5 September. These provide an operational reference,
not a controlled matcher benchmark: database state and simultaneous work differ on replay.

## Validation status

The supported cached replay was subsequently started as run
`e7ad832c-8d76-4fdd-8c3e-83a8d0358df1`, using accepted parent run
`68a9c397-95fa-423c-863e-159dd1c04a3d`. Its draft candidate is
`04314255-53e4-4afa-abab-19069d77579a`. The first loader attempt stopped before copying
any rows because the configured 128 GiB database budget was below the conservative projected
143,207,920,099 bytes. Physical filesystem availability was 836,900,184,064 bytes, so the
physical-space check passed. This is an operational budget correction, not a reason to remove
the 24 GiB growth, 16 GiB temporary-file, 64 GiB WAL and 4 GiB reserve allowances. The draft
remained empty and the accepted PSI pointer remained unchanged after that failed preflight.

After raising the declared local budget to 192 GiB while retaining every physical-space and
growth reserve, explicit resume exposed an existing lifecycle defect: the run task was
requeued but its idempotent import operation stayed terminally failed, so the loader never
performed a new capacity check. Migration 060 now preserves terminal import attempt evidence;
explicit resume resets only a retryable failed operation to the existing interrupted/enqueue
path. Enqueue advances its attempt number. Non-retryable failures and active or locked loader
operations are refused, and the original error, timestamps and progress remain available in
the bounded `failure_attempts` projection after subsequent success. A still-leased run task
also prevents retry even when its import has already failed. Review identified that recovery
can add measurements after the initial terminal failure: separate append-only recovery events
in migration 061 now retain those policy changes and completed VACUUM/REINDEX evidence after a
later successful attempt clears its live recovery display. This fix has ten real PostgreSQL tests, including
actual bounded VACUUM/REINDEX and failure-to-success recovery history, alongside 125 passing
orchestration unit tests. Independent review also covers the migration split.
The final independent re-review resolved both recovery-history findings and independently
passed the upgrade regression, with no remaining recovery findings.

Migration 062 addresses the upgrade case where 061 observes a resumed operation carrying an
earlier recovery policy. It appends attribution metadata without rewriting the original
event. Ambiguous legacy events remain visible as bounded `unattributed_recovery_events`, with
their recorded attempt number and an explicit explanation, rather than being silently lost
or assigned to a guessed attempt. The upgrade regression reproduces failure/recovery/resume
before 061 and verifies this evidence remains visible after the retry succeeds.

The development database API automatically applied the original migration 060 during source
reload. Extending that already-applied file then caused a checksum mismatch and interrupted
the API. The original bytes were restored by matching the recorded SHA-256, and the recovery
extension was moved into migration 061. Only the database API was restarted; it became healthy
and the PSI loader retained its active lease. Its orchestration task had expired during the
outage, requiring an explicit resume after the loader completes. Neither migration history
nor accepted source pointers were rewritten.

A fresh supported cached replay from the same accepted parent started at 09:55:28 UTC as run
`29b1ae13-9c23-4cab-a566-9113b96e45c6`, import
`758ec4da-1235-4f87-b887-636dc9fa5ece`, candidate
`1d8fca70-33f6-47e3-91fd-994c4d07c06e`. It passed the revised declared-budget check and
**succeeded at 10:40:28 UTC, taking 45m00.086s**, with all 7,402,643 rows accepted. This is
slower than the retained prior import's 26m10.458s; concurrent acquisition, current database
state and the API interruption prevent interpreting this as a controlled matcher benchmark.
The matcher optimization does not establish an end-to-end replay speedup. At one observation,
PostgreSQL used 3.9 GiB within the Docker host's 7.7 GiB memory limit.

The actual persisted candidate quality results exactly confirm the counterfactual:
5,422,398 linked (73.2494867%), 1,980,245 unmatched, and **zero lost or changed links** among
the 4,940,715 previously linked identical source revisions. The blocking schema and candidate
row-count rules passed. Linkage remains a review warning, and four source rows with
out-of-range address numbers remain retained under an anomaly warning. Explicit orchestration
resume reused the successful import without copying again and started the full release
export. The accepted PSI pointer is unchanged.

A separate bounded, read-only comparison of every candidate row also passed: all 7,402,643
source keys/revisions matched the accepted baseline, with zero changed source-row hashes and
zero differences in source era, unit/house/street components, locality, postcode, price,
contract date or settlement date. It independently counted exactly 481,683 gained links.
Its initial parallel plan exceeded Docker's shared-memory allocation; the successful retry
used a serial plan and transaction-local 64 MiB `work_mem` with a 120-second statement limit.

The export completed at **10:57:30 UTC**, taking **15m46.388s**, compared with the retained
prior export's 7m18.503s. The resulting run succeeded and the fully verified candidate was
submitted for review through the supported API; it is `awaiting_review`, version 4.

The gzip artifact contains **1,170,111,004 compressed bytes** and **9,690,725,243 uncompressed
bytes**, with SHA-256
`7ab24a1b8343a244e6b2d4beac5dcd8c4dc1e25d543c5bd88fe79a9c3407fb38`.
A bounded-memory stream independently verified the complete compressed checksum and gzip
integrity, all 7,402,643 NDJSON rows, 5,422,398 linked/A/exact-address records, 1,980,245 unmatched
records, and source-hash plus candidate-generation provenance on every record. Verification
took 76.359 seconds. The public manifest reports `propertyscope.property-sales.v3`, builder
4.0.0, and the retained 71-object source release through 31 August 2026. The supported artifact
range endpoint returned HTTP 206, correct gzip bytes, full length, Digest and ETag, and
`private, no-store` review caching.

Final owning-database verification confirms all run counts are 7,402,643 and accepted pointers
remain PSI `a7078066-1bde-4b31-8b4d-4acab03939e6` and G-NAF
`291863ec-a12d-4a03-a80c-8f334feae2d0`. No acceptance or downstream publication was performed.

- **115 passed:** complete import-profile, source-adapter and PSI-Parquet unit suites.
- **15 passed:** opt-in PostgreSQL PSI/address tests in separately created disposable databases,
  including actual SQL recovery, ambiguous candidates, stale generations, source preservation,
  false-match defenses, rollback, and same-revision regression counts.
- Ruff and `git diff --check` passed for the matching-owned changes.
- **10 passed:** real PostgreSQL retry, recovery-evidence and immutable-upgrade regressions;
  **125 passed:** orchestration unit tests; **46 passed:** migration unit tests.
- The enclosing implementation task records the full repository quality gate. This report
  records the matching and retry checks plus the completed retained replay and artifact checks.

Existing accepted source hashes/releases and the user's earlier dataset audit are preserved.
