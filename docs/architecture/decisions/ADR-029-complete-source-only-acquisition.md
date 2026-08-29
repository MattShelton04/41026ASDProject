# ADR-029: Make complete-source acquisition the only Feature 1 update scope

- Status: Accepted
- Date: 28 August 2026
- Owner: PropertyScope Feature 1
- Supersedes: ADR-021 and ADR-022 acquisition-scope and job-capacity decisions

## Context

Feature 1 exposed `test`, `showcase`, and `full-data` acquisition profiles plus row, byte, object,
and deadline alarms. Those controls were originally added for deterministic CI, fast demonstrations,
and fail-closed handling of unexpectedly large publisher artifacts. They did not intentionally
truncate a successful `full-data` run, but operators still had to decide whether a requested update
was complete and whether a displayed alarm could prevent the load. That ambiguity worked against
the data-platform operator's normal intent: import the registered source in full.

Deterministic tests do not need a partial-production mode. They can consume every row in a finite,
checked-in synthetic source. Source validation, allowlisted transport, streaming, checksums,
transactional candidate isolation, cancellation, and human publication review provide the relevant
safety boundaries without making data volume an operator decision.

## Decision

- Every Feature 1 job has one immutable acquisition scope: `full-data` with `all_records: true`.
- PSI always resolves annual history from 1990 onward plus every current-year Monday partition.
  G-NAF, BOCSAR, schools, and the deterministic fixture consume their complete registered source.
- The browser and data CLI do not expose a profile selector, record-count field, year-range field,
  advanced acquisition JSON, or `--profile` option.
- Job and adapter definitions no longer contain row, byte, object, task-parallelism, or deadline
  limits. The runner does not stop a valid import because the source crossed one of those values.
- Official archive readers retain path, format, and integrity validation but have no default
  compressed-byte, expanded-byte, member-count, scanned-row, or canonical-output ceiling.
- Retry resolves the current registered complete scope. Resume and cached reprocessing reject
  historical partial runs because their already-acquired artifacts cannot prove completeness.
- Saved jobs do not persist an editable acquisition scope. The immutable registry supplies it, and
  validation rejects source-specific subset selectors before the service starts.
- Tests remain deterministic by using a finite fixture source, not by selecting a reduced import.
- HTTP pagination, property-search candidate bounds, AI/tool budgets, archive path validation and
  checksums do not reduce the Feature 1 warehouse generation. ADR-030 supersedes the earlier
  bounded release-product interpretation: completed releases now carry a complete streaming
  artifact, while the browser/API record view is explicitly a bounded preview.
- Stack startup still performs no acquisition. An operator or CLI action is required, and the
  accepted generation changes only after human review and atomic publication.

## Consequences

Operators can treat every started update as a complete-source request without comparing modes or
interpreting capacity alarms. Publisher growth may consume more network, disk, and processing time,
so monitoring, cancellation, streaming, and durable recovery remain important. A finite fixture is
the supported fast path for local UI and CI work.

Historical migrations and evidence records continue to mention the superseded limits because they
preserve point-in-time database evolution and assessment evidence. Migration 026 removes the
capacity columns and saved-job scope from current databases. It does not rewrite historical run
evidence: operators must start a fresh complete update instead of resuming or reprocessing a
partial historical artifact.

## Alternatives considered

- **Keep the alarms but hide them:** rejected because a hidden ceiling could still abort a valid
  source-growth import and would preserve the operator's underlying uncertainty.
- **Keep reduced profiles only in the CLI:** rejected because the CLI and browser should exercise
  the same public plan/run contract.
- **Use reduced production profiles for tests:** rejected because a finite synthetic source proves
  deterministic integration behavior without creating an incomplete-production mode.
