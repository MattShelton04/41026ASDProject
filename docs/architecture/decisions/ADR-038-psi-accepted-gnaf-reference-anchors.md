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

### Full-history matching implementation (5 September 2026)

The complete 7.4-million-row sales load exposed an expensive correlated lookup plan:
address resolution alone ran for over 18 minutes before operator-authorised cancellation.
The typed loader now aggregates accepted G-NAF and eligible legacy registry identities into
transaction-local, materialized address dictionaries, then joins the distinct sales addresses
against those dictionaries. Reference tables are read in batches rather than searched separately
for every address. Existing loader temporary-file and statement limits still apply.

G-NAF full street-type names contribute their existing abbreviated lookup spelling as well;
an abbreviation stored by G-NAF does not acquire a reverse full-name equivalence. Distinct
property-reference counts preserve ambiguity across both spellings. Legacy fallback is allowed
only when G-NAF has no candidate, and only a unique reference is returned. No matching confidence,
source facts, identity anchors, quality policy or activation behavior changes.

### Conservative matching and coverage review (13 September 2026)

`psi-exact-address.v2` extends exact equivalences using the explicit NSW SIX
[Road Name Types catalogue](https://maps.six.nsw.gov.au/sws/AddressLocation.html).
Previously unparsed street text such as `EXAMPLE CCT` can resolve to `EXAMPLE CIRCUIT`.
No spelling similarity, locality-only fallback, missing-unit inference, range containment,
or unverified PSI-to-G-NAF property identifier propagation is permitted.

House-number matching accepts spaces around a single suffix or a range separator (`10 A`,
`20 - 24`). It does not join separated digits, strip LOT labels, interpret slash units or
discard a range's last-number suffix. Parsed first and last numbers must agree with the
existing typed components. The raw house number participates in the resolution key, preventing
an old missing derived suffix from leaking the `10 A` result into a `10` sale. Full postcode,
locality, street, first number, last number, suffix and unit equality, accepted-generation
fencing, and distinct-property ambiguity checks remain required.

Derivation occurs in transaction-local matching dictionaries so cached canonical artifacts
benefit without rewriting source facts, source hashes, revision identity, or immutable accepted
releases. Only streets represented in eligible sales contribute G-NAF dictionary entries;
type equivalences use a single catalogue join rather than repeated catalogue scans per address.
Eligible addresses are materialized and analyzed before dictionary joins. Without this boundary,
the correlated raw/typed-number equality predicates caused PostgreSQL to estimate one eligible
address and choose an unboundedly expensive nested-loop plan on real source data.

Quality evidence identifies the matching policy and reports linked and unmatched counts and
fraction. Any unmatched coverage is an explicit review warning. Zero linkage, or a lost or
changed property link for an identical accepted `(business key, revision, source hash)`, is a
blocking quality result. This is a regression comparison, not a completeness assertion:
new/changed revisions and old unresolved sales are not independently verified by that check.
Exact address equivalence alone does not prove parcel continuity over historical decades.

`scripts/audit_feature1_psi_matching.py` compares the matcher with accepted links, weighted by
all retained source revisions and split by era and original address shape. It operates inside
the owning database using temporary tables and rollback, without publication or downstream
effects. Its optional repeatable block sample is explicitly labelled; only an unsampled run
establishes full-generation recovery counts. The PostgreSQL integration suite separately tests
false-match defenses and the same-revision regression comparison in disposable databases.
