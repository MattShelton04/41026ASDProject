# Feature 1 suburb-map spatial API: request review and implementation plan (2026-10-17)

Point-in-time record. Feature 3 (Suburb, Crime and Liveability Analytics) asked Feature 1 for an
accepted-generation spatial projection of gazetted suburb boundaries, government schools and
registered amenities, suitable for an interactive map. This document reviews that request
against the data Feature 1 actually holds, records what we accept, adjust or decline, and gives
the implementation plan. The consumer guide is
[`student-1/SUBURB_MAP_API_CONSUMER_GUIDE.md`](../../student-1/SUBURB_MAP_API_CONSUMER_GUIDE.md).

## 1. Data inspected

Observed read-only in the developer `ps-dev` stack (PostgreSQL/PostGIS), 17 October 2026. None of
the three releases is accepted there yet; each is `awaiting_review` with no blocking quality
failures.

| Dataset | Release | Rows | Shape | Notes |
|---|---|---|---|---|
| `nsw-suburb-boundaries` (`feature-1`) | `a5a79703…` | 4,607 | Polygon/MultiPolygon, EPSG:7844 source → 4326 | 1 invalid (CAMBEWARRA, ring self-intersection); 20 without postcode; 79 names used more than once (170 rows), always with distinct postcodes |
| `nsw-amenities` (`feature-1`) | `36460dde…` | 9,866 | 16 point layers + `protected-reserve` polygons | 9 invalid reserve polygons; 126 of 582 train stations carry publisher `operationalstatus=6` |
| `nsw-government-schools` (`feature-3`) | `47e3fab4…` | 2,210 | `propertyscope.school-points.v2` points | All `Open`; the accepted pointer still names the 10-row seeded demo |

Measured on the real boundaries (`ST_SimplifyPreserveTopology`, per polygon):

| Tolerance (degrees) | ≈ ground distance | max vertices | p99 | median | max GeoJSON bytes (6 dp) | invalid after |
|---|---|---|---|---|---|---|
| 0 (source) | — | 99,668 | 7,564 | 713 | 2,369,658 | 0 |
| 0.00002 | 2 m | 4,967 | 2,198 | 223 | 118,122 | 0 |
| 0.0001 | 10 m | 2,360 | 1,020 | 123 | 56,180 | 0 |
| 0.0005 | 50 m | 892 | 418 | 60 | 21,233 | 0 |

The whole-layer simplification at four tolerances took 194 s. That is too slow for a request
path but acceptable as a one-off, release-scoped step during publication.

Other observations:

- Parramatta (`cadid` 108033054) covers 7 government schools and 27 amenity points. The
  amenity query took 736 ms without a generation-scoped spatial index, because the only GiST
  index on `warehouse.reference_feature` spans every retained release, including about 3.4 M
  cadastre, planning and bushfire polygons.
- **230 of 2,210 government schools (10.4%) lie inside a gazetted suburb whose name differs
  from their `locality` label.** Name equality would misplace them. Spatial association is
  therefore required, not optional.
- Protected reserves reach 62,549 vertices (Kosciuszko). A reserve intersecting a suburb must be
  clipped to the map view and simplified before it is returned.
- The amenity source's ArcGIS services publish no coded-value domain for `operationalstatus`.
  Spot checks match code 1 to open stations (Central, Parramatta, Dubbo, Goulburn) and code 6
  to closed branch-line stations (Crookwell, Kandos, Temora, Bombala).

## 2. Review of the request

### Accepted as requested

- **Search and detail endpoints** use `suburb_id` = publisher `cadid`. Search is exact on the
  normalised name, takes an optional postcode, and returns `match: none|unique|ambiguous`.
- **`GET /suburbs/{suburb_id}/map-context`** returns a GeoJSON boundary, bbox, one
  FeatureCollection per category, per-layer coverage, release provenance and truncation
  evidence.
- **Spatial association:**
  - Points match with `ST_Covers(boundary, point)`, so boundary points count as inside.
  - Polygons match with `ST_Intersects`.
  - A bbox `&&` filter runs first, and only `geometry_status='valid'` rows are considered.
- **Accepted-only reads.** Every query resolves the pointer in `serving.accepted_generation`
  once, inside one read-only repeatable-read snapshot. Candidate, superseded and rejected rows
  are never read.
- **School contract preserved.** School features carry exact `propertyscope.school-points.v2`
  records as their properties.
- **`parks` is not exposed.** A request for it receives a structured 422 that names
  `protected-reserve` and explains its NPWS-only coverage.
- **Versioned contract.** `propertyscope.suburb-map-context.v1` (plus `suburb-search.v1` and
  `suburb-detail.v1`) is generated from Pydantic models, checked into `student-1/contracts/`, and
  referenced by the OpenAPI document.

### Accepted with a defined interpretation

| Request item | Interpretation, and why |
|---|---|
| `stale` coverage state | No publisher defines freshness. Feature 1 declares a freshness window per dataset: 400 days from the accepted release's acquisition. An older layer is reported `stale`, and its data is still returned. |
| `partial` coverage state | A layer is `partial` when it was truncated by the feature ceiling, or when invalid source geometry was excluded although its bbox touches the suburb. Both counts are in `layer_details`. |
| "truncated" vs "reject unsafe requests" | Each layer has a per-layer feature ceiling (default 500, maximum 1,000). Hitting it truncates deterministically (ordered by name, then id), sets `truncated: true` and makes the layer `partial`. Out-of-range parameters, too many categories, and responses beyond the vertex or byte ceiling are **rejected** with 422; we never sample silently. |
| Operational status | The publisher defines no code list, so we return the raw `operational_status_code` and a derived `operational_status` (`operational` for 1, `non-operational` for any other code, `null` when absent). By default `operational=current` keeps only operational facilities and reports `excluded_non_operational`; `operational=all` returns everything. Without this default, a map labelled "train stations" would show 126 closed rural stations. |
| ETag and caching | The strong ETag hashes the contract version, the normalised request and every accepted release ID used. Responses send `Cache-Control: no-cache`, so clients always revalidate. A revalidation costs one pointer read and returns 304 until a release is published. |
| `zoom` or `detail` | `detail=low\|medium\|high` uses 50 m, 10 m and 2 m tolerances. `zoom` maps ≤11 to low, 12–14 to medium and ≥15 to high. Supplying both is a 422. |
| Centroid | We return `centroid` (`ST_Centroid`, which can fall outside a concave or multi-part suburb) **and** `label_point` (`ST_PointOnSurface`, always inside). |
| Query plans "at expected source scale" | Recorded on the real 4,607 / 9,866 / 2,210-row releases in a disposable stack (§5). The new GiST indexes lead with `dataset_release_id`, so retained generations do not enlarge the probe. |

### Pushed back or deferred

1. **Fuzzy or prefix suburb search.** Not in v1. The request asks for exact normalised matching,
   and fuzzy matching would reintroduce the "which Mayfield?" problem. Feature 3 should search
   with name and postcode, or offer the `ambiguous` list to the user.
2. **Automatic repair of invalid boundaries** (one suburb). We do not invent geometry. The
   suburb is returned with `geometry_status: invalid`, a `null` boundary geometry and every
   layer `unavailable`. `ST_MakeValid` repair can be added later as a labelled derived
   geometry.
3. **Shared topology between neighbouring suburbs.** Simplification is per polygon, so
   simplified neighbours may not share edges exactly. That is acceptable for the
   single-suburb display this request covers.
4. **Viewport, radius and vector-tile endpoints** stay out of scope, as the request itself states.
5. **FOI education layers vs `schools`.** `schools` means the Department of Education
   government-school master (typed contract). `primary-school`, `high-school`,
   `combined-school`, `preschool`, `technical-college` and `university` are NSW Spatial Services
   facility points that include non-government institutions. Requesting both double-counts
   government schools, and the guide says so.
6. **Publication is an operator decision.** The endpoints serve nothing until the three releases
   above are published. Publishing `nsw-government-schools` also delivers the real school
   release to Feature 3's own importer, replacing its seeded 10-row demo. That is the normal
   flow, but the release owner should do it knowingly.

## 3. Design

```text
Feature 3 backend ──HTTP──> f1-backend /api/data-platform/v1/suburbs/...   (public contract, ETag relay)
                              └──HTTP──> f1-db-api /internal/data-platform/v1/suburbs/...
                                            └── PostgreSQL/PostGIS (accepted pointers only)
```

- **Persistence** (migration `064_suburb_map_projection.sql`):
  - `serving.suburb_boundary_display` is a release-scoped projection with one row per suburb. It
    holds the name, normalised name, postcode, centroid, label point, bbox, geometry status,
    source vertex count, and precomputed `low`/`medium`/`high` display geometries with their
    vertex counts. It is keyed `(dataset_release_id, suburb_id)`, with a lookup index on
    `(dataset_release_id, name_normalised, postcode)`.
  - `serving.build_suburb_boundary_display(release_id)` is an idempotent SQL function that
    rebuilds the projection for one release. The migration back-fills any already accepted
    suburb release.
  - It adds the `btree_gist` extension and two generation-scoped GiST indexes:
    - `warehouse.reference_feature (dataset_release_id, layer, geom)`, partial on valid geometry
      in the registered map layers;
    - `warehouse.school (dataset_release_id, geom)`.
- **Publication:** `materialize_release_activation` builds the projection for
  `nsw-suburb-boundaries` before the pointer switch. It runs in its own cancellable
  transaction, like the G-NAF `published` step, so the pointer never names a release without
  display geometry.
- **Reads:** a new `_suburb_map_reads.py` sits behind `PropertyScopeStore`, under the existing
  interactive read budget. One connection runs a `REPEATABLE READ READ ONLY` snapshot. The
  category registry in `suburb_map_catalog.py` maps each public category to its dataset, target
  feature, source layer and predicate, and a unit test keeps it in step with the partial-index
  predicate.
- **HTTP:**
  - The internal routes validate parameters, compute the ETag and answer `If-None-Match` with
    304.
  - The public routes in `suburb_routes.py` relay bytes, `ETag` and `Cache-Control`. Problem
    codes are specific: `invalid_request`, `unsupported_category`, `suburb_not_found`,
    `suburb_boundaries_unavailable` and `response_limit_exceeded`.
- **Limits** (documented in the contract): at most 12 categories; per-layer features default
  500, maximum 1,000; 60,000 response vertices; 4 MiB response bytes. Coordinates have 6 decimal
  places (≈0.1 m). Reserve display geometry is clipped to the suburb bbox, expanded by 10%, and
  marked `display_clipped`.

## 4. Plan

1. Migration and SQL function; activation hook; partial and composite GiST indexes.
2. Category registry, read module and repository facade; internal and public routes; OpenAPI
   paths and schemas; Pydantic response models and generated JSON Schemas with fixtures.
3. Tests:
   - unit tests for parameter parsing, the category registry, coverage-state derivation, the
     ETag and the response guards (using a scripted read owner);
   - PostGIS component tests, gated by `PROPERTYSCOPE_TEST_POSTGRES_URL`, for ambiguous names,
     empty vs unavailable layers, boundary points, invalid geometry, generation switches,
     truncation, ETag changes on publication, and index use in `EXPLAIN`;
   - backend route tests for ETag/304 relay and problem passthrough;
   - contract drift tests;
   - live endpoint tests (`pytest -m endpoint`).
4. Live validation in an isolated `ps-scratch` stack: collect the three sources, review and
   publish them there, exercise every endpoint, and record timings and `EXPLAIN` plans.
5. Write the consumer guide, then run the full gate (`scripts/check.py`) and open a PR.

## 5. Live validation evidence

Recorded after implementation; see the PR description for the commands and outputs.
