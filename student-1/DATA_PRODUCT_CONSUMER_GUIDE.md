# PropertyScope Release 0 data-product consumer guide

This guide is the implemented provider contract for Feature 1. The normative machine-readable
definitions are `contracts/data-platform-api.v1.openapi.yaml` and the versioned JSON Schemas in
`contracts/`. Consumers use HTTP and immutable artifacts; they do not import Feature 1 Python or
connect to its PostgreSQL/PostGIS database.

## Registered catalogue and readiness

| Dataset | Builder | Contract | Target | Fixture proof | Redistribution |
| --- | --- | --- | --- | --- | --- |
| `fixture-property` | `property-snapshot 1.0.0` | `propertyscope.property-snapshot.v1` | Feature 1 | Executable offline | Download permitted, synthetic fixture |
| `gnaf-nsw` | `property-snapshot 1.0.0` | `propertyscope.property-snapshot.v1` | Feature 1 | Executable fixture and optional official archive | Licence-controlled; public artifact returns 403 |
| `nsw-psi-sales` | `property-sales 1.0.0` | `propertyscope.property-sales.v1` | Feature 2 | Executable bounded fixture and cached/live transport | Bounded derived artifact |
| `bocsar-crime` | `crime-series 1.0.0` | `propertyscope.crime-series.v1` | Feature 3 | Executable bounded fixture and live transport | Approved bounded extract |
| `nsw-government-schools` | `school-points 1.0.0` | `propertyscope.school-points.v1` | Feature 3 | Executable bounded fixture and live transport | Approved bounded extract |

Feature 4 and Feature 5 have no registered source jobs. Spatial database capability is not a data
product, and this feature does not invent planning, hazard, zoning, strata, building, or dossier
data.

## Stable consumer API

All routes below are relative to `/api/data-platform/v1` and are described in OpenAPI 3.1.

- `GET /data-products` lists every registration, builder/schema version, supported scopes,
  capability, limits, redistribution decision, limitations, and latest accepted release.
- `GET /data-products/{dataset_id}` returns one definition.
- `GET /data-products/{dataset_id}/accepted?target_feature=feature-N` reconciles the current
  accepted release after downtime or a missed push.
- `GET /dataset-releases` supports `dataset_id`, `target_feature`, `status`, `schema_version`,
  `limit` (1–100), and bounded `offset` filters.
- `GET /dataset-releases/{release_id}` composes immutable release state, receipts, quality results,
  quality summary, and accepted predecessor evidence.
- `GET /dataset-releases/{release_id}/manifest` returns the manifest for exactly that release.
- `GET /dataset-releases/{release_id}/artifact` returns only a verified, at-most-50 MB
  `release_export` permitted by the source policy. Accepted artifacts include `Digest`, `ETag`,
  `Content-Type`, `Content-Disposition`, and immutable cache headers.
- `GET /dataset-releases/{release_id}/records` is a bounded operator preview. It is not the
  consumer product or an export mechanism.
- `POST /dataset-releases/{release_id}/submit-review`, `/publish`, and `/reject` implement the
  version-checked review lifecycle. Publish also requires an `Idempotency-Key` and explicit human
  approval.
- Property identity consumers use `GET /properties/search`, `/properties/{property_ref}`,
  `/properties/{property_ref}/map-context`, `/properties/{property_ref}/coverage`, and
  `/properties/{property_ref}/report-section`.

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
→ awaiting_review → consumer validation → durable receipt
→ accepted (prior accepted release becomes superseded)
```

The runner pages a private release projection over HTTP. Every response declares the same release
and candidate-generation ID, and a count or generation change aborts construction. The runner has
no database credentials. Candidate data does not enter accepted property search. The public API
does not advertise a draft as current.

Publication sends a versioned request containing release and dataset IDs, schema, exact byte
SHA-256, record count, manifest, provider-relative artifact path, and idempotency key. The consumer
resolves that path against its configured Feature 1 origin, downloads without redirects, validates
the schema/hash/count, and returns a typed receipt. Feature 1 durably records that receipt before
the accepted-pointer transaction. A rejected, malformed, mismatched, unavailable, or timed-out
consumer leaves the predecessor active.

For Feature 1's own property products there is no separate downstream service. Before recording
its local receipt, the provider re-reads the registered `release_export` from content-addressed
storage and verifies the manifest, artifact registration, exact bytes, product schema/release ID,
and record count. It does not synthesize acceptance from release metadata alone.

Replaying an operation that produced an accepted receipt returns that retained receipt and
completes any interrupted pointer transition without a duplicate import. A recorded rejected,
failed, or unavailable attempt is immutable; after correcting the cause, the operator starts a new
publication operation with a new idempotency key. The same target/key with different release evidence conflicts. A consumer that missed the push calls
the accepted-product endpoint repeatedly; lookups are stable and do not mutate state.

Accepted artifacts and manifests are immutable. Corrections are new releases with a supersession
reference. Cached reprocessing creates a new candidate from retained verified evidence and cannot
replace an accepted artifact in place.

## Envelope, hashing, and bounds

Every product is UTF-8 JSON with no byte-order mark, compression, or trailing newline. Object keys
are lexicographically sorted, separators are `,` and `:`, non-ASCII text is retained as UTF-8, and
NaN/infinity are forbidden. Builders make record ordering explicit. Null source values remain JSON
`null`; dates are ISO `YYYY-MM-DD`; decimals that require source fidelity are canonical strings.
SHA-256 covers the exact downloadable bytes, not a re-serialised object. The manifest count is the
number of records in the product envelope and its byte count is the exact artifact length.

Release 0 uses one immutable JSON artifact per release. Every builder enforces a row limit and the
50,000,000-byte artifact limit. Planning resolves the selected declarative profile first, so its
registered `maximum_records` is present even when an operator supplies only the profile name; an
override cannot exceed the product builder limit. PSI full acquisition still narrows its downstream
release to explicit years and its partition year is retained even when business dates are null. Exceeding either bound fails
with an instruction to narrow geography, period, category, or record scope. There is no silent
truncation and no multipart or compressed-product fallback.

Schemas are closed (`additionalProperties: false`). Additive record fields therefore require a
new declared schema revision and builder registration; silently changing v1 is not compatible.
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
Ordering is business key then revision, and a duplicate key/revision fails construction. Unmatched,
nominal, unusual, part-sale, bulk, and future-dated source records are not silently converted into
analytics. Feature 2 owns exclusions, comparable semantics, medians, trends, valuations, forecasts,
returns, and presentation.

During acquisition, an exact retransmission with the same business key and source-row hash is
collapsed. A changed row under the same business key is retained and receives a deterministic
revision ordered by first source occurrence during import; it is never silently chosen over the
earlier facts.

### Crime series

Release 0 uses verified BOCSAR **postcode** geography. The registered scopes and integration
fixtures use `geography_kind=postcode`; no postcode-to-suburb translation occurs. The builder
retains one exact sorted `observed_months` universe per geography/category, first/last/count,
completeness hash, `blank_means_observed_zero`, sparse positive observations, and coverage-only
series. An absent sparse observation means zero only when that exact month is present and the flag
is true. Outside-coverage months are unavailable, not zero. Feature 1 does not calculate rates,
safety rankings, hotspots, street inference, desirability, predictions, or causality.

### School points

The product preserves stable school code, name, type, operational status (including closed),
original and normalised locality, state, LGA, bounded NSW WGS84 coordinates, hashes, and provenance;
ordering is school code. A point does not prove catchment, eligibility, quality, availability, or a
recommendation. Feature 3 owns distance queries and presentation.

## Registering a future product

A future owner must complete all of these before startup accepts a registration:

1. Register a source with attribution, target feature, capability state, and safe redistribution
   decision in `config/source-register.yaml`.
2. Add a bounded job profile naming an existing adapter/import profile or their separately tested
   implementations.
3. Define a versioned product model and checked-in JSON Schema plus synthetic valid/invalid
   fixtures.
4. Register an exact builder key/version with supported import profiles, target, contract, media
   type/encoding, deterministic ordering, row/byte limits, and allowed policies.
5. Add deterministic construction, schema/hash/count, licence, real-HTTP consumer, failure, and
   reconciliation tests.
6. Add the dataset-specific quality policy and document source semantics and limitations.

Unknown builders/versions, mismatched import/target/contract, absent schemas, unsafe policies,
unsupported media, or unbounded scopes fail startup. The generic catalogue, release, review,
artifact, receipt, and accepted-lookup APIs do not change.

## Deterministic demonstration

From the repository root:

```text
uv sync --locked --all-packages --all-groups
uv run pytest student-1/tests/component/test_real_http_publication.py
uv run scripts/dev.py up
```

Open <http://localhost:5200>, then use **Data-product catalogue** to inspect registrations. Launch a
showcase job, inspect the candidate release count/bytes/checksum/coverage/licence/quality evidence,
submit it for review, and publish. Stop or reject a test consumer to demonstrate a retained
predecessor, then restore it and retry with a new idempotency key. Reconcile with the accepted-product
endpoint. Ordinary `uv run scripts/dev.py down` preserves evidence volumes.

The official-source measurements in `MARKING_EVIDENCE.md` are historical evidence and are not
silently re-labelled as results of the deterministic fixture tests.

## Remaining decisions and governance

Feature 2 must review its sales exclusion/comparable rules. Feature 3 must review presentation,
crime denominator/comparison semantics, and school-distance semantics. Feature 4 and Feature 5
must register real approved sources and contracts before products can exist.

“Written tutor/team approval evidence for the ADR-016 PostgreSQL/PostGIS exception must still be
attached before submission.”
