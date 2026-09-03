# ADR-038: Resolve PSI against accepted G-NAF identities with bounded reference anchors

- Status: Accepted
- Date: 3 September 2026
- Owner: PropertyScope Feature 1

## Context

ADR-028 makes the accepted G-NAF warehouse generation authoritative for property identity;
most addresses therefore have a deterministic property reference without a global registry row.
The PSI matcher still joined that warehouse to `registry.property`, excluding those identities.
It also compared abbreviated PSI street types with full G-NAF types literally. A retained
2023–2025 candidate imported 638,125 sales but linked none, correctly blocking quality approval
and subsequent release finalisation. Copying every G-NAF address into the global registry or
removing the PSI property-reference foreign key would contradict existing boundaries.

## Decision

- Resolve each distinct eligible PSI address against published rows of the currently accepted
  G-NAF generation, using the same deterministic reference as property discovery. Preserve exact
  eight-component matching and explicit zero/one/many outcomes. Recognise only the existing PSI
  street-type vocabulary's full G-NAF equivalents; source values remain unchanged.
- Supplied property references retain precedence. Ambiguous G-NAF matches cannot fall back to
  the legacy registry, and registry identities carrying `gnaf_pid` provenance are excluded from
  that fallback so stale address snapshots cannot re-enter matching.
- During the existing atomic PSI materialisation statement, insert only missing registry rows
  needed for uniquely resolved references. These rows anchor the unchanged PSI foreign key.
  Insert their `gnaf_pid` identifier, accepted source release and
  `identity_anchor: psi-accepted-gnaf` provenance in the same transaction. Conflicts leave
  existing registry rows untouched; any materialisation failure rolls back anchors and facts.
- Extend PSI's existing measured failure-recovery scope to exactly `warehouse.psi_sale`,
  `registry.property`, and `registry.property_identifier`. A rollback can leave allocated pages in
  all three. Preserve bounded per-relation maintenance and durable pending-reindex retry evidence;
  do not maintain the accepted G-NAF source or unrelated relations.
- Property search, detail, coverage, SEIFA and sale-history existence checks continue to use
  the accepted G-NAF generation. Their legacy registry branches exclude G-NAF-backed rows,
  including anchors. An anchor cannot make a withdrawn address visible or supply obsolete
  canonical fields after a generation switch. Non-G-NAF legacy compatibility remains available.
- Candidate import and anchor creation do not change accepted pointers, quality thresholds,
  matching confidence policy or publication approval. Selected publisher-year candidates remain
  partial and non-publishable under ADR-035.

## Consequences

PSI can link to accepted virtual identities without a statewide registry copy or changing the
foreign key. There is bounded durable registry growth for newly referenced addresses. Migration
049 adds a partial property-reference index for all `gnaf_pid` provenance, including historical
identifiers; the existing current-only index cannot serve these compatibility guards. Anchors
are internal relational support, not a second canonical
address source. Activation remains the small pointer transaction specified by ADR-028; this
decision adds no activation-time registry writes.

Capacity estimates include registry rows, identifiers and WAL as well as sales. The PSI loader
floors are recalibrated from disposable one-million-row measurements with the existing 2.5 safety
factor. Operators must configure a measured deployment budget that covers those floors, temporary
files, reserve and existing database size; the physical data/WAL check remains independent. The
retained 638,125-row scope has a measured retry budget. These measurements do not establish a
safe execution budget for the complete 7.4-million-row history; the operations runbook records
that limitation.

Real PostgreSQL regressions enforce foreign keys, ambiguity refusal, source preservation,
transaction rollback, replay, and accepted-generation changes. Failed retained jobs can use the
supported cached reprocess action to create a new candidate with the original scope and lineage;
their original failure evidence remains intact.
