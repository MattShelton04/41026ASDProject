# ADR-045: Producer-owned reference source facts

Status: Accepted for the user-authorised Feature 1 integration, 13 September 2026.

## Context

The existing address, sale, crime, school-point and SEIFA products do not contain the
parcel, planning, geographic, catchment, scheme, amenity or inflation evidence needed
by later features. Prototype extracts include pagination caps and cannot establish
complete source coverage. The requested increment supplies verified publisher facts;
downstream property joins and interpretation are deferred.

## Decision

Register ten complete, explicitly scoped acquisition profiles in Feature 1. Use the
existing durable discover/acquire/import/build/review/activate lifecycle and its
content-addressed artifacts. Each source discovery retains field schemas, native CRS,
coverage, publisher dates when available and a metadata fingerprint. A fingerprint
is not a publisher-issued edition. ArcGIS reads use deterministic OID pagination,
bounded responses/retries and count/metadata reconciliation. Cadastre uses four
disjoint OID ranges with supported standard-mode pages capped at 2,000; complex flood and
reserve geometries use smaller pages. The runner supports one to four independently leased
acquisition-task workers (default one); the single database loader serializes imports and
activations. This bounds concurrency without changing database ownership.

The database service owns `warehouse.reference_feature`. It stores stable source/layer
identifiers, publisher attributes and nulls, the projected EPSG:4326 GeoJSON and PostGIS
geometry, native source CRS, explicit dates and source/provenance hashes. Topologically
invalid source geometry remains visible with `geometry_status=invalid`; it is excluded
from the spatial index. No silent geometry repair, property match or missing-to-zero
conversion is permitted. Structurally malformed or non-finite data fails the import.
Metadata foreign keys are validated once in `warehouse.import_batch`, in the same
transaction as the facts, following migration 050's existing warehouse policy. This
avoids three redundant metadata checks for every cadastral feature.
The exact publisher year-3000 end-date sentinel becomes nullable canonical validity;
its raw attribute remains intact. The owning importer also recognizes that sentinel
when replaying early canonical artifacts, producing the same normalized hash as the
corrected adapter without redownloading unchanged source features.

The producer-owned `propertyscope.reference-feature.v1` record contract serves all ten
datasets. Complete gzip-NDJSON exports use an indexed `(release, layer, record_id)`
keyset. The contract package and catalogue expose the schema, licence and source-specific
limitations. All ten products target Feature 1; activation creates no new consumer
integration. Statistical SAL/LGA editions remain distinct from current gazetted suburbs;
catchment grades/future status remain explicit; CPI frequency/reference base is retained;
the flood source represents published planning controls only.

Authenticated artifact-registration routes allow at most 2 MiB of control metadata
because the five real EPI field schemas exceed 256 KiB. Other control requests retain
their existing limit. Large source facts remain in artifacts, not request bodies.

BFPL uses the current official NSW RFS hosted service because its legacy service cannot
serialize a verified million-position polygon. That real canonical feature exceeds 47 MB;
the BFPL importer allows at most 64 MiB per record, while other reference profiles retain
16 MiB. BFPL exports use ten-record pages and serial projection batches of one. Adaptive
publisher page recovery restores throughput after a large feature without dropping it;
byte-headroom checks, the original page ceiling and a failed-growth cooldown bound retries.
An empty projected BFPL polygon can be recovered from its validated native EPSG:3857
geometry after an identity/attribute recheck; both publisher representations remain in
record provenance. This addresses a verified server-projection collapse without inventing
missing geometry or repairing source topology.

## Consequences

No shared package, student ownership or database credential/mount boundary changes.
Backend and database independently validate their boundary contracts. Full source
acquisition can be expensive; deterministic CI uses small publisher fixtures while
separate real-source evidence records complete counts, elapsed time and local status.
An implemented adapter, successful publisher read and accepted local generation are
three distinct claims. Same-count publisher edits without a changed edition marker
cannot be fully detected without transactional publisher snapshots; acquired bytes
and record hashes remain the reproducible evidence.

See the [integration plan](../../release-1/reference-data-integration-plan.md),
[PSI matching evidence](../../reviews/feature-1-psi-matching-2026-09-13.md), and
[spatial source verification](../../reviews/feature-1-spatial-source-verification-2026-09-13.md).
