# Feature 1 reference-data integration plan

The approved scope is stronger PSI property matching and producer-side acquisition, validation,
storage, release construction and inspection for NSW cadastre, planning controls, geographic
boundaries, school catchments, strata schemes, amenities, CPI and valid scoped hazard evidence.
Downstream feature integration is deferred. Application capabilities and local accepted-release
state must be reported separately.

1. Diagnose the real unmatched PSI population, recover defensible address forms, retain ambiguous
   matches as unknown, and measure changes against the same accepted source facts.
2. Verify current official endpoints, schema, geography, date/edition, licensing and counts. Use
   complete declared publisher layers; never treat page limits or a research sample as coverage.
3. Add a Feature 1 reference-feature contract and owning spatial warehouse. Source records retain
   publisher attributes, source URL/CRS/dates and immutable provenance. Geometry is preserved and
   its validity exposed; interpretations and property joins remain explicit future consumer work.
4. Integrate registered jobs with existing discover/acquire/import/build/review/activate lifecycle,
   artifact verification, keyset preview/export, quality evidence and operator runtime reporting.
5. Test malformed, truncated, ambiguous, changed-source and replay cases offline. Run isolated
   PostgreSQL/HTTP integration tests and complete real local acquisitions where publisher access
   allows, then record counts, timings, bytes, limitations and local candidate/release state.
6. Have independent agents review matching and source/platform work. Address findings, rerun the
   relevant checks, run the canonical quality gate, and update living references and runtime advice.

NSW cadastre initially means the complete Lot layer, avoiding a second large copy of property
polygons without a demonstrated need. Planning covers zoning, height, floor-space ratio, minimum lot
size and heritage. The initial flood source is explicitly published flood-planning controls, not a
statewide inundation model; scenario layers require valid scenario metadata and source access.

Runtime principles: stream acquisition and canonical records; bound network pages and retries;
use deterministic pagination and count reconciliation; COPY into an isolated generation; build
immutable gzip-NDJSON exports with keyset pages; avoid whole-source Python lists. Measure actual
stages before adding concurrency or changing storage. Keep accepted provenance and source hashes.

Implementation references: [operations and concurrency](reference-data-operations.md),
[contract/persistence decision](../architecture/decisions/ADR-045-reference-source-facts.md),
[PSI matching](../reviews/feature-1-psi-matching-2026-09-13.md),
[spatial sources](../reviews/feature-1-spatial-source-verification-2026-09-13.md), and
[other reference sources](../reviews/feature-1-reference-source-validation-2026-09-13.md).

The [complete local validation report](../reviews/feature-1-reference-live-e2e-2026-09-13.md)
records application-run and artifact evidence separately from publisher discovery.
