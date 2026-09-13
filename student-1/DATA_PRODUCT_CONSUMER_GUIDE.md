# PropertyScope Release 0 data-product consumer guide

This guide is the implemented provider contract for Feature 1. The normative API definition is
`contracts/data-platform-api.v1.openapi.yaml`. Consumers discover the supported producer-owned
contract package at `GET /api/data-platform/v1/product-contracts/v1`, then download the immutable
digest-bound archive from the returned
`GET /api/data-platform/v1/product-contracts/v1/sha256/{digest}.zip` path. The packaged
`product-contract-set.v1.json` index binds each runtime builder version to a fixed relative
record-schema path and transport. The archive also contains both immutable manifest revisions:
`release-manifest.v1` for historical accepted evidence and `release-manifest.v2` for current
gzip-NDJSON releases. Consumers do not reach into backend source paths, import Feature 1 Python, or
connect to its PostgreSQL/PostGIS database.

## Registered catalogue and readiness

| Dataset | Builder | Contract | Target | Fixture proof | Redistribution |
| --- | --- | --- | --- | --- | --- |
| `fixture-property` | `property-snapshot 3.0.0` | `propertyscope.property-snapshot.v2` | Feature 1 | Executable offline | Download permitted, synthetic fixture |
| `gnaf-nsw` | `property-snapshot 3.0.0` | `propertyscope.property-snapshot.v2` | Feature 1 | Executable fixture and optional official archive | Licence-controlled; public artifact returns 403 |
| `abs-seifa-2021` | `seifa-area 1.0.0` | `propertyscope.seifa-area.v1` | Feature 1 | Complete live transport | CC BY 4.0 attributed derived release |
| `nsw-psi-sales` | `property-sales 4.0.0` | `propertyscope.property-sales.v3` | Feature 2 | Complete cached/live transport | Bounded derived artifact |
| `bocsar-crime` | `crime-series 3.0.0` | `propertyscope.crime-series.v2` | Feature 3 | Complete live transport | Approved bounded extract |
| `nsw-government-schools` | `school-points 3.0.0` | `propertyscope.school-points.v2` | Feature 3 | Complete live transport | Approved bounded extract |
| `nsw-cadastre` | `reference-feature 1.0.0` | `propertyscope.reference-feature.v1` | Feature 1 | Registered complete Lot layer | CC BY 4.0; attributed derived release with extraction date |
| `nsw-planning-controls` | `reference-feature 1.0.0` | `propertyscope.reference-feature.v1` | Feature 1 | Five complete EPI layers | Attributed derived release |
| `nsw-bushfire-prone-land` | `reference-feature 1.0.0` | `propertyscope.reference-feature.v1` | Feature 1 | Complete published BFPL layer | Attributed derived release |
| `nsw-flood-planning` | `reference-feature 1.0.0` | `propertyscope.reference-feature.v1` | Feature 1 | Published flood-planning controls only | Attributed derived release |
| `abs-geography-2021` | `reference-feature 1.0.0` | `propertyscope.reference-feature.v1` | Feature 1 | NSW 2021 SAL/LGA boundaries | Attributed derived release |
| `nsw-suburb-boundaries` | `reference-feature 1.0.0` | `propertyscope.reference-feature.v1` | Feature 1 | NSW gazetted suburb boundaries | Attributed derived release |
| `nsw-school-catchments` | `reference-feature 1.0.0` | `propertyscope.reference-feature.v1` | Feature 1 | Published primary, secondary and future zones | Attributed derived release |
| `nsw-strata-schemes` | `reference-feature 1.0.0` | `propertyscope.reference-feature.v1` | Feature 1 | Published StrataHub scheme polygons and facts | Attributed derived release |
| `nsw-amenities` | `reference-feature 1.0.0` | `propertyscope.reference-feature.v1` | Feature 1 | Declared official facility layers | Attributed derived release |
| `abs-cpi` | `reference-feature 1.0.0` | `propertyscope.reference-feature.v1` | Feature 1 | All groups Sydney/Australia, monthly and quarterly | Attributed derived release |

The reference products are owned and activated within Feature 1. No new downstream consumer is
wired: Features 2–5 retain their independent contracts and stores. Source features do not establish
property matches, legal applicability, school eligibility, building condition or hazard absence.
See the [reference integration plan](../docs/release-1/reference-data-integration-plan.md) and source verification
records for exact scope. Catalogue capability is separate from local readiness: inspect accepted
releases and consumer-operation evidence to determine which data is active on a particular setup.

## Five-minute consumer quickstart

A consuming feature first fetches and verifies the advertised digest-bound contract archive, then
implements one import route and one operation-status route:

```text
POST /api/data-import/v1/propertyscope-releases
GET  /api/data-import/v1/propertyscope-releases/{operation_id}
```

Feature 1 calls that route on the consumer backend origin configured by
`PROPERTYSCOPE_FEATURE_2_URL`, `PROPERTYSCOPE_FEATURE_3_URL`, or
`PROPERTYSCOPE_FEATURE_4_URL`. In Compose, set the value to the consumer's internal service origin,
for example `http://feature-3-backend:5000`; do not publish a database-service address. The callback
must:

1. Validate the JSON body with the package's
   `consumer-publication-request.v1.schema.json`, which also
   validates the complete nested release manifest.
2. Treat the `Idempotency-Key` header and body `idempotency_key` as one delivery key while issuing
   and durably persisting a distinct consumer operation ID. Replays return that same operation.
3. Return a queued/running or terminal body matching
   `consumer-import-acknowledgement.v1.schema.json` within the five-second connect budget. The fixed
   status route returns the same identity and evidence; it never redirects.
4. Use `shared-consumer-protocol` to resolve `artifact_path` only against the configured Feature 1
   origin, enforce explicit byte/record budgets, and stream-validate gzip-NDJSON, SHA-256, schema,
   release identity and count.
5. Import through the consumer's own database API in one atomic operation. The consumer owns its
   domain validation and keeps normal reads independent of Feature 1. Terminal evidence is closed
   and retained before the operation reports `accepted`, `rejected`, or `failed`.

Minimal queued response:

```json
{
  "consumer_operation_id": "consumer-issued-operation-17",
  "status": "queued",
  "release_id": "60000000-0000-0000-0000-000000000099",
  "dataset_id": "bocsar-crime",
  "target": "feature-3",
  "schema_version": "propertyscope.crime-series.v2",
  "content_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "record_count": 125
}
```

Minimal accepted terminal response:

```json
{
  "consumer_operation_id": "consumer-issued-operation-17",
  "status": "accepted",
  "release_id": "60000000-0000-0000-0000-000000000099",
  "dataset_id": "bocsar-crime",
  "target": "feature-3",
  "schema_version": "propertyscope.crime-series.v2",
  "content_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "record_count": 125,
  "rows_received": 125,
  "rows_accepted": 125,
  "rows_rejected": 0,
  "error": null
}
```

Copy-pasteable complete request and legacy immediate-receipt examples live in
`contracts/fixtures/consumer-publication-request.valid.json` and
`contracts/fixtures/consumer-publication-receipt.valid.json`. The independent real-HTTP reference
consumer is exercised by `uv run pytest student-1/tests/component/test_real_http_publication.py`.
It consumes runner-produced bytes through the Shared helper and producer-owned schema package; it
does not import Feature 1 implementation modules in the consumer boundary.

## Stable consumer API

All routes below are relative to `/api/data-platform/v1` and are described in OpenAPI 3.1.

- `GET /data-products` lists every registration, builder/schema version, supported acquisition
  scope, downstream product projection, redistribution decision, limitations, and latest accepted
  release.
- `GET /data-products/{dataset_id}` returns one definition.
- `GET /data-products/{dataset_id}/accepted?target_feature=feature-N` reconciles the current
  accepted release after downtime or a missed push.
- `GET /dataset-releases` supports `dataset_id`, `target_feature`, `status`, `schema_version`,
  `limit` (1–100), and bounded `offset` filters.
- `GET /dataset-releases/{release_id}` composes immutable release state, receipts, quality results,
  quality summary, and accepted predecessor evidence.
- `GET /dataset-releases/{release_id}/manifest` returns the manifest for exactly that release.
- `GET /dataset-releases/{release_id}/artifact` returns the exact verified `release_export`
  permitted by the source policy. Its bytes must equal the manifest `byte_count`; consumers enforce
  their separately signed-off compressed and expanded byte budgets. Accepted artifacts include
  `Digest`, `ETag`, `Content-Type`, `Content-Disposition`, and immutable cache headers.
- `GET /dataset-releases/{release_id}/records` is a bounded operator preview. It is not the
  consumer product or an export mechanism.
- `POST /dataset-releases/{release_id}/submit-review`, `/publish`, and `/reject` implement the
  version-checked review lifecycle. Publish also requires an `Idempotency-Key` and explicit human
  approval. A valid publish returns `202` with durable accepted-version activation; the prior
  accepted version remains live until local activation succeeds. Downstream imports run separately.
- Property identity consumers use `GET /properties/search`, `/properties/{property_ref}`,
  `/properties/{property_ref}/map-context`, `/properties/{property_ref}/coverage`,
  `/properties/{property_ref}/seifa`, and `/properties/{property_ref}/report-section`. The SEIFA
  projection resolves only the accepted `propertyscope.seifa-area.v1` generation and reports a
  typed unavailable or ambiguous state instead of falling back to another generation.

### ABS SEIFA 2021 area semantics

`propertyscope.seifa-area.v1` contains the complete NSW Suburbs and Localities (SAL) subset of the
official 2021 workbook. It preserves the five-digit SAL code, ABS name, normalised locality key,
usual resident population, and the score/Australian-decile pair for IRSD, IRSAD, IER and IEO. A
publisher `-` is retained as a null pair; it is never converted to zero. The property projection
uses an exact whitespace-normalised locality plus NSW-state match and refuses ambiguous matches.

SEIFA measures relative socio-economic conditions for an area. It must not be represented as a
measure of a particular property, household, or person. Decile 1 is the lowest-scoring 10% of areas
for that index and decile 10 is the highest-scoring 10%; each index has distinct meaning. Derived
outputs and UI views carry “Based on Australian Bureau of Statistics data” attribution and the ABS
copyright/licensing link registered with the source.

Unknown dangerous query fields are rejected. Errors use RFC 9457-style Problem Details and carry
request correlation. Consumer destinations are code-owned origins plus fixed `/api/` paths;
release data cannot select a URL. Redirects are not followed.

## Publication and recovery lifecycle

The implemented lifecycle is:

```text
discover → acquire → source verification → canonical import artifact
→ isolated candidate import → deterministic quality checks
→ registered builder → schema-valid bounded release_export
→ atomic schema/hash/count/manifest/artifact binding → candidate
→ awaiting_review → producer verification receipt
→ queued loader activation → atomic accepted pointer + downstream delivery outbox
  (prior accepted release becomes superseded)
→ independent downstream delivery → consumer validation → genuine consumer receipt
```

The runner pages a private release projection over HTTP. Every response declares the same release
and candidate-generation ID, and a count or generation change aborts construction. The runner has
no database credentials. Candidate data does not enter accepted property search. The public API
does not advertise a draft as current.

Publication verifies Feature 1's immutable artifact/manifest binding and records a labelled
`feature-1-local:` producer verification receipt before queueing activation. This receipt attests
producer verification; it does not claim downstream acceptance. For an external target, the atomic
accepted-pointer transaction creates a durable delivery outbox. Outbox persistence failure rolls
back that transaction. Successful producer publication does not wait for consumer import.

The independent delivery operation contains the immutable release
and dataset IDs, target, schema, exact byte SHA-256, record count, manifest, provider-relative
artifact path, and delivery idempotency key. The HTTP connect and status exchanges each have a
five-second timeout, reject redirects, and accept at most 64 KiB of response JSON. They return a
genuine consumer-issued operation ID and closed evidence; Feature 1 never relabels its delivery key
as that ID. The browser receives `202` plus a fixed same-origin status resource and never waits for
the artifact import.

The consumer resolves the artifact path against its configured Feature 1 origin and applies explicit
compressed-byte, expanded-byte, line, and record budgets before and during streaming. Complete
products are not truncated to a producer row/byte ceiling: the signed-off consumer capacity must be
at least the exact manifest `byte_count` and `record_count`, with its own expansion limit. The Shared
consumer protocol rejects a declaration over those configured limits before download and then
checks the compressed bytes, SHA-256, gzip framing, NDJSON records, product schema, and count before
an atomic import handoff. A leased Feature 1 worker polls durable progress and makes at most five
delivery attempts; an expired lease resumes the recorded phase rather than restarting accepted work.

New outbox operations have `delivery_only=true`; consumer acceptance finishes them as `delivered`
without requesting another producer activation. Rejected, malformed, mismatched, unavailable,
timed-out or exhausted downstream operations leave producer publication and its accepted pointer
unchanged. The UI reports downstream progress/failure separately. Accepted property
reads resolve the immutable warehouse generation selected by the accepted pointer, so candidate
address fields cannot leak through a global registry update. The loader's final pointer transaction
contains no source-scale DML.

For Feature 1's own property products there is no separate downstream service. The short
self-publication path verifies the durable manifest, artifact ledger, content-addressed storage key,
exact registered bytes, product schema/release ID, and record count established during construction.
The activation loader later streams the physical artifact and rechecks its exact bytes and SHA-256
before materialisation. Self-publication persists its own operation identity; it does not fabricate
one from the browser idempotency key or synthesize acceptance from release metadata alone.

Legacy delivery/activation operations retain their recorded replay semantics, including activation
reconciliation after their accepted receipt; ADR-041 does not rewrite historical operations.
Replaying a completed new delivery returns its retained receipt without republishing or performing
a duplicate import. A new delivery key for the same
release, dataset, target, schema, checksum and record count resumes the original durable operation;
mismatched evidence conflicts. A rejected, failed, or unavailable operation remains inspectable and
can retry only through its bounded durable lifecycle. **Retry publication** addresses failed local
activation and retains prior receipts with a fresh attempt key. **Retry downstream import** on a
published release addresses independent failed delivery; it cannot undo producer publication.
A consumer that missed the push calls the
accepted-product endpoint repeatedly; lookups are stable and do not mutate state.

Accepted artifacts and manifests are immutable. Corrections are new releases with a supersession
reference. Cached reprocessing creates a new candidate from retained verified evidence and cannot
replace an accepted artifact in place.

This current lifecycle supersedes the consumer-acceptance publication gate in ADR-033/ADR-040.
See [ADR-041](../docs/architecture/decisions/ADR-041-producer-owned-publication.md). Each consumer
still owns its accepted generation; there is no distributed atomicity across feature databases.

## Gzip-NDJSON framing, hashing, and downstream product projections

Every artifact emitted by the current v2/v3 builders uses media type `application/x-ndjson` with
content encoding `gzip`. Retained accepted legacy releases can remain downloadable as the immutable
`application/json` evidence described in the compatibility section below.
After decompression it is UTF-8 NDJSON with no byte-order mark: each non-empty line is exactly one
record matching the schema selected from `product-contract-set.v1.json`, and the final record has a
newline. There is no outer product envelope. Within each record, object keys are lexicographically
sorted, separators are `,` and `:`, non-ASCII text is retained as UTF-8, and NaN/infinity are
forbidden. Builders make record ordering explicit. Null source values remain JSON `null`; dates are
ISO `YYYY-MM-DD`; decimals that require source fidelity are canonical strings. SHA-256 and
`byte_count` cover the exact compressed downloadable bytes. `record_count` is the number of
decompressed non-empty NDJSON records.

Release 0 uses one immutable gzip-NDJSON artifact per downstream consumer release. Builder row and
byte projections describe that separately published artifact; they do not limit the complete
generation imported into the Feature 1 warehouse. PSI retains explicit downstream years and its
partition year even when business dates are null. Exceeding a consumer projection fails release
construction and does not alter or truncate the imported candidate generation. There is no silent
truncation or multipart fallback.

Record schemas are closed (`additionalProperties: false`). The v1 contract-set compatibility
policy is `closed-record-schemas-require-new-version-for-shape-changes`: additive, removed, renamed,
or type-changed record fields require a new declared schema revision and builder registration;
silently changing v1 is not compatible. A consumer pins a schema version from the package index and
may support old and new versions concurrently during its own migration.
The package index lists current gzip-NDJSON record contracts separately from legacy envelope
contracts. Legacy `property-snapshot.v1`, `property-sales.v2`, `crime-series.v1`, and
`school-points.v1` schemas remain unchanged for accepted-release evidence and read compatibility;
new builders emit only v2/v3 record contracts. Legacy entries are not registrations for producing
new releases.
Likewise, `propertyscope.release-manifest.v1` remains unchanged and may describe accepted legacy
`application/json` evidence with no content encoding. Current builders emit only
`propertyscope.release-manifest.v2`, whose closed schema requires `application/x-ndjson` and
`gzip`. Release-detail and publication-request contracts accept either immutable manifest revision
so a retained accepted release remains inspectable and replayable without weakening new output.
Existing routes may receive additive response-envelope fields, which consumers must ignore unless
their selected JSON Schema says otherwise. Enum meaning is never changed in place. A breaking
endpoint change requires a new API version and a documented migration period.

## Dataset semantics and limitations

### Property snapshot

`property_ref` is an opaque stable PropertyScope identity. G-NAF PID or fixture PID remains a
source address identifier—not title, parcel, ownership, boundary, valuation, occupancy, or a
person. Structured address components, postcode text, WGS84 coordinates, source status,
geocoding/CRS evidence, source hash, and release provenance are preserved. Fixture and G-NAF rows
share one contract. G-NAF manifests and catalogue entries declare `download_permitted: false`, and
the public artifact route returns a safe 403 while accepted property identity APIs remain the
integration surface allowed by policy.

### Property sales

The product preserves source business key and revision, source era, district/property/dealing IDs,
nullable contract/settlement dates, nullable AUD price, original and square-metre area strings,
nullable `property_ref`, match tier/confidence/geographic precision, hashes, and provenance.
Version 3 retains the Version 2 fields that preserve official source/download identifiers,
historical valuation number, property name, unit/house/street/locality/postcode fields, land description/dimensions,
zoning, nature, primary purpose, strata lot, component, sale code and interest-of-sale fields.
Feature 1 derives conservative street components and assigns an exact-address `property_ref` only
when those components resolve to one unique accepted registry property; ambiguous rows remain
`MISS`. The pre-deployment v1 draft was removed rather than retained as a second supported contract;
the accepted v2 envelope remains available as legacy evidence rather than being rewritten in place.
Ordering is business key then revision, and a duplicate key/revision fails construction. Unmatched,
nominal, unusual, part-sale, bulk, and future-dated source records are not silently converted into
analytics. Feature 2 owns exclusions, comparable semantics, medians, trends, valuations, forecasts,
returns, and presentation.

During acquisition, an exact retransmission with the same business key and source-row hash is
collapsed. A changed row under the same business key is retained and receives a deterministic
revision ordered by first source occurrence during import; it is never silently chosen over the
earlier facts.

### Crime series

The complete registered BOCSAR source includes **postcode and suburb** geography. Early Release 0
fixtures used postcode alone; no postcode-to-suburb translation occurs. The builder
retains one exact sorted `observed_months` universe per geography/category, first/last/count,
completeness hash, `blank_means_observed_zero`, sparse positive observations, and coverage-only
series. The v2 coverage capacity is 600 months; the August 2026 official archives currently
contain 372–375 months from 1995 onward, so this is a growth guard rather than a truncation rule.
An absent sparse observation means zero only when that exact month is present and the flag
is true. Outside-coverage months are unavailable, not zero. Feature 1 does not calculate rates,
safety rankings, hotspots, street inference, desirability, predictions, or causality.

### School points

The product preserves stable school code, name, type, operational status (including closed),
original and normalised locality, state, LGA, bounded NSW WGS84 coordinates, hashes, and provenance;
ordering is school code. A point does not prove catchment, eligibility, quality, availability, or a
recommendation. Feature 3 owns distance queries and presentation.

## Registering a future product

Reference products use `propertyscope.reference-feature.v1`: dataset and layer identity, source
record identifier, optional name and EPSG:4326 GeoJSON, explicit geometry validity, publisher
attributes, source URL/CRS/dates and normalisation/release provenance. Publisher field definitions,
counts, filters, edition and geographic extent are retained in the run's source-snapshot artifact.
The source-release identifier is a labelled metadata fingerprint when no common publisher edition
exists. It must not be interpreted as a publication date or an immutable upstream snapshot.
Invalid geometry is retained and labelled rather than silently repaired; missing geometry remains
missing. A source feature's appearance or non-appearance is not a property-level determination.

Reference acquisition is complete within its fixed registered layers and filters. The unchanged
generic run API does not accept arbitrary URLs, bounding boxes or row caps. Canonical rows stream
through JSONB COPY into the owning reference warehouse, and exports use keyset pagination and the
existing verified immutable artifact/review/activation lifecycle. CPI preserves frequency, geography,
period and reference basis; it supplies no inflation-adjustment calculation.

A future owner must complete all of these before startup accepts a registration:

1. Register a source with attribution, target feature, capability state, and safe redistribution
   decision in `config/source-register.yaml`.
2. Add a complete-source job profile naming an existing adapter/import profile or their separately
   tested implementations.
3. Define a versioned product model and checked-in JSON Schema plus synthetic valid/invalid
   fixtures.
4. Register an exact builder key/version with supported import profiles, target, contract, media
   type/encoding, deterministic ordering, row/byte limits, and allowed policies.
5. Add deterministic construction, schema/hash/count, licence, real-HTTP consumer, failure, and
   reconciliation tests.
6. Add the dataset-specific quality policy and document source semantics and limitations.

Unknown builders/versions, mismatched import/target/contract, absent schemas, unsafe policies,
unsupported media, or invalid acquisition scopes fail startup. Complete source remains the default;
the only bounded source profile is the explicit, non-publishable PSI completed-archive-year
candidate defined by ADR-035. The generic catalogue, release, review,
artifact, receipt, and accepted-lookup APIs do not change.

## Deterministic demonstration

From the repository root:

```text
uv sync --locked --all-packages --all-groups
uv run pytest student-1/tests/component/test_real_http_publication.py
uv run scripts/dev.py stack up
```

Open <http://localhost:5200>, then use **Data-product catalogue** to inspect registrations. Launch a
fixture job, inspect the candidate release count/bytes/checksum/coverage/licence/quality evidence,
and submit it for review. Use the real-HTTP publication test above for the independent consumer
accept/reject demonstration; the normal Compose profile intentionally does not pretend that an
unallocated feature backend exists. Reconcile accepted evidence with the accepted-product endpoint.
Ordinary `uv run scripts/dev.py stack down` preserves evidence volumes.

The official-source measurements in `MARKING_EVIDENCE.md` are historical evidence and are not
silently re-labelled as results of the deterministic fixture tests.

## Remaining decisions and governance

Feature 2 must review its sales exclusion/comparable rules. Feature 3 must review presentation,
crime denominator/comparison semantics, and school-distance semantics. Feature 4 and Feature 5
must register real approved sources and contracts before products can exist.

“Written tutor/team approval evidence for the ADR-016 PostgreSQL/PostGIS exception must still be
attached before submission.”
