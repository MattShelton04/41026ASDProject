# ADR-035: Allow explicitly bounded PSI publisher-year acquisition

- Status: Accepted
- Date: 1 September 2026
- Owner: PropertyScope Feature 1
- Supersedes: ADR-029 only for PSI acquisition-scope selection
- Preserves: ADR-030 complete-release and accepted-generation semantics

## Context

ADR-029 removed ambiguous test/showcase limits and made every operator update consume the complete
registered source. That remains the safest default, but PSI sales history is partitioned into
annual publisher archives plus current weekly packages. Requiring the complete history for every
targeted investigation creates avoidable network, storage and processing work.

An archive year is a source partition, not an exact contract-date interval. Some source facts have
missing or anomalous dates, and weekly retransmissions may overlap annual material. A bounded run
therefore must not claim to be a complete sales-history generation or silently replace the accepted
complete generation used by consumers.

## Decision

- `full-data` remains the default for every Feature 1 job. For PSI it continues to mean annual
  archives from 1990 onward plus current weekly packages.
- PSI alone also supports `psi-year-range`, expressed as inclusive `start_year` and `end_year`.
  Only completed annual archive years from 1990 through the previous calendar year are selectable.
- The backend is the acquisition-scope authority. It expands the requested endpoints into the exact
  contiguous `years` partition list and adds immutable evidence: `all_records: true` means every
  record in those selected archives, while `complete: false`, `coverage_status: partial`, and a
  limitation distinguish the result from complete history.
- Preview and run creation use the same validation and canonical scope. The canonical object is
  persisted on the run, copied to every task and source snapshot, and retained as candidate release
  coverage. Retry, resume and cached reprocessing preserve that exact object. Unsupported historical
  subset shapes remain blocked.
- Source-year selection is not described as an exact contract-date range. The exported manifest
  reports observed temporal coverage separately from the requested publisher archive years.
- Scoped runs may produce isolated candidates for inspection and deterministic downstream testing,
  but they cannot enter publication delivery or activation. The control API and database activation
  boundary both reject them, so they cannot replace the accepted complete generation.
- G-NAF, schools and BOCSAR remain complete-source-only. Their current adapters do not expose an
  equally clear partition contract that can be selected without ambiguous omission semantics.
- The data CLI retains complete-source behavior. The browser and public plan/run HTTP API expose the
  bounded PSI option; full remains selected by default.

## Consequences

Operators can reduce a PSI update to the publisher archive years relevant to their work without
creating a row ceiling or pretending the result is complete. Exact contract-date filtering remains
a consumer/query concern unless a later source contract can define how undated and retransmitted
facts are treated.

Scoped candidates consume warehouse and artifact storage and still pass the normal acquisition,
import, quality and release-build pipeline. They do not change buyer-facing or consumer-facing
accepted data. Publishing selected years would require a separate merge/replacement decision and
consumer contract; this ADR does not invent one.

The database repeats structural checks for defence in depth but does not independently calculate
the moving latest-completed-year boundary. Only the credential-free backend can create a run through
the public API, and the runner revalidates the canonical scope before source access.

## Alternatives considered

- **Exact start/end sale dates:** deferred because publisher partitions are annual/weekly and some
  retained source facts have no usable date. Calling a partition scan an exact date slice would be
  misleading without an explicit undated-record policy.
- **Publish the selected years as the current dataset:** rejected because the single accepted pointer
  represents the complete generation; replacing it would make older history disappear.
- **Add similar selectors to all sources:** rejected for this increment because their source and
  completeness semantics differ and were not proven by existing adapters.
