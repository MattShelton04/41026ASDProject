# Suburb-map API consumer guide

Feature 1 answers Feature 3's request for a suburb-map spatial API with three read-only endpoints.
They return accepted NSW gazetted suburb boundaries, plus the government schools and official
amenities inside each suburb, ready to draw on a MapLibre map. This guide is written for Feature 3
(Suburb, Crime and Liveability Analytics). Feature 4, or any other backend, can use it unchanged.

- Normative contract: `contracts/data-platform-api.v1.openapi.yaml` (operations
  `searchAcceptedSuburbs`, `getAcceptedSuburb`, `getAcceptedSuburbMapContext`).
- Response schemas: `suburb-search.v1`, `suburb-detail.v1`, `suburb-map-context.v1`. These are
  closed JSON Schemas, also shipped in the product-contract package at
  `GET /api/data-platform/v1/product-contracts/v1`.
- Design record: the
  [request review and plan](../docs/reviews/feature-1-suburb-map-api-review-2026-10-17.md),
  including what was accepted, what was changed, and the live evidence.

## At a glance

All paths are relative to `/api/data-platform/v1`.

| Endpoint | Use it to | Caching |
|---|---|---|
| `GET /suburbs/search?q=&postcode=&limit=` | Turn a suburb name (and optionally a postcode) into a stable `suburb_id` | `no-cache`, no ETag |
| `GET /suburbs/{suburb_id}` | Read one suburb's identity, label point, bbox, source dates and release | ETag + `no-cache` |
| `GET /suburbs/{suburb_id}/map-context?categories=&zoom=\|detail=&limit=&operational=` | Draw the map: display boundary plus one GeoJSON layer per category, with coverage per layer | ETag + `no-cache` |

`suburb_id` is the publisher's `cadid` from the NSW gazetted suburb layer, for example `108033054`
for PARRAMATTA. It matches `^[1-9][0-9]{0,11}$` and stays the same across Feature 1 releases for
the same gazetted suburb. Store this ID, not the display name. 79 suburb names are used more than
once in NSW.

## Where to call it from

Call Feature 1 **from your backend**, never from the browser:

- Feature 3's CSP is `connect-src 'self' https://tiles.openfreemap.org`, and Feature 1 sits on
  another origin.
- Your backend already has a client for this origin: `PROPERTY_DATA_URL` in Feature 3 and
  `PROPERTYSCOPE_DATA_PLATFORM_URL` in Feature 4. Both default to `http://f1-backend:5201` inside
  Compose.
- Proxy a narrow route of your own, such as `GET /api/suburb-analytics/v1/suburbs/{id}/map`, and
  return the Feature 1 payload, or the parts you need, to your page.

Send an `X-Request-ID` header so failures can be traced across both services. Feature 1 echoes it
back on every response, including problems.

Feature 1 gives each read a 3.5 s budget. Measured on real data, the first request for 12
categories took a median of 96 ms and at most 628 ms. Your existing 4 s client timeout is
therefore enough.

## Typical flow

1. **Resolve the suburb once.**
   - Call `GET /suburbs/search?q=Mayfield&postcode=2304`.
   - When `match` is `unique`, store `items[0].suburb_id`.
   - When it is `ambiguous`, ask the user to choose by postcode. The response lists every candidate.
   - When it is `none`, show "not found". The search matches exact names only; see
     [Search](#search).
2. **Fetch the map** with `GET /suburbs/{suburb_id}/map-context?zoom=13`. Keep the `ETag`.
3. **Render it.**
   - Fit the camera to `suburb.bbox`.
   - Draw `suburb.boundary` as a fill and outline.
   - Add each entry of `layers` as a GeoJSON source.
   - Put the suburb label at `suburb.label_point`.
4. **Explain gaps.** For every key in `coverage`, check whether the state is `accepted`. If it is
   not, show the reason from `layer_details`; see [Coverage states](#coverage-states).
5. **Revalidate** on the next view by sending `If-None-Match: <etag>`. A `304` means your copy is
   still the current accepted data.

## Search

```text
GET /suburbs/search?q=mayfield
```

```json
{
  "schema_version": "propertyscope.suburb-search.v1",
  "geography": "nsw-gazetted-suburb",
  "query": {"q": "mayfield", "normalised": "MAYFIELD", "postcode": null},
  "availability": {"status": "available", "reason": "Exact normalised name match within the accepted suburb release."},
  "match": "ambiguous",
  "items": [
    {"suburb_id": "108032118", "name": "MAYFIELD", "postcode": "2304", "state": "NSW",
     "geometry_status": "valid", "centroid": [151.738166, -32.8978],
     "label_point": [151.73809, -32.89768],
     "bbox": [151.726447, -32.908681, 151.74837, -32.886759]},
    {"suburb_id": "108031813", "name": "MAYFIELD", "postcode": "2540", "...": "..."}
  ],
  "count": 4,
  "has_more": false,
  "release": {"dataset_id": "nsw-suburb-boundaries", "...": "see Releases"}
}
```

- **Exact, normalised name match.** Case, punctuation and repeated spaces are ignored, so
  `"  st. leonards "` matches `ST LEONARDS`. There is no fuzzy or prefix matching: `Parramata`
  returns `match: "none"`. For autocomplete, keep your own list of names; Feature 1 does not
  provide one.
- **Postcode.** `postcode` narrows the result to that four-digit postcode. 20 suburbs have no
  postcode in the source; for those, `postcode` is `null`.
- **Limit.** `limit` defaults to 20 and is capped at 50. `has_more` reports whether more
  candidates exist.
- **No accepted boundaries.** If no suburb-boundary release has been accepted, the response is
  still `200`, with `availability.status: "dataset_unavailable"`, `match: "none"` and
  `release: null`. Treat that as "Feature 1 has no suburb data yet", not as "suburb unknown".
- **Unknown parameters.** Any parameter other than `q`, `postcode` and `limit` is rejected with
  `422 invalid_request`.

## Suburb detail

`GET /suburbs/{suburb_id}` returns the search fields together with the following:

- `source`: publisher record ID and dates;
- `display`: vertex counts at each detail level;
- `coverage`: `accepted`, `stale` or `unavailable`;
- `release`.

It returns no geometry. Use it for a header card or to check a stored ID.

## Map context

```text
GET /suburbs/{suburb_id}/map-context?categories=schools,train-station&zoom=13
```

### Parameters

| Parameter | Default | Rules |
|---|---|---|
| `categories` | `schools,train-station,library,protected-reserve` | Comma-separated keys from the table below, at most 12. Unknown keys give `422 unsupported_category` |
| `zoom` | — | Integer 0–22. ≤ 11 → `low`, 12–14 → `medium`, ≥ 15 → `high` |
| `detail` | `medium` | `low`, `medium` or `high`. Cannot be combined with `zoom` |
| `limit` | 500 | 1–1000 features per layer |
| `operational` | `current` | `current` hides facilities the publisher marks as not operating; `all` returns them with their status |

The display boundary is simplified ahead of time at publication. Tolerances are 0.0005° (about
50 m) for `low`, 0.0001° (about 10 m) for `medium` and 0.00002° (about 2 m) for `high`. On real
data the largest suburb, LAKE MACQUARIE, returns 713, 1,993 and 5,508 vertices respectively. A
typical suburb returns well under 200. Spatial matching always uses the full-precision source
geometry; simplification affects only what you draw.

### Categories

| Key | Source | Geometry | Matched when |
|---|---|---|---|
| `schools` | NSW Department of Education government schools (`school-points.v2`) | Point | the suburb covers the point (edges and vertices count as inside) |
| `train-station`, `bus-station`, `airport` | NSW Spatial Services transport facilities | Point | covers |
| `library`, `hospital`, `ambulance-station`, `police-station`, `fire-and-rescue-station`, `rural-fire-station`, `ses-headquarters` | NSW Spatial Services community and emergency facilities | Point | covers |
| `preschool`, `primary-school`, `high-school`, `combined-school`, `technical-college`, `university` | NSW Spatial Services education facilities, all sectors | Point | covers |
| `protected-reserve` | NPWS protected estate (nature reserves, national parks, state conservation areas and other NPWS reserves) | Polygon | the reserve intersects the suburb |

Choose categories with care:

- **There is no `parks` category.** Feature 1 has no official source with complete park
  coverage. Requesting `parks` returns `422 unsupported_category`, and the message points to
  `protected-reserve`. Never label `protected-reserve` as "parks": it excludes council parks,
  sports grounds and most urban green space. Each reserve feature carries a `coverage_note` that
  says so.
- **Don't add `schools` to the education categories.** `schools` holds government schools only,
  from the Department of Education. `primary-school`, `high-school` and `combined-school` come
  from a different publisher and cover every sector, so most government schools appear in both.
  Use `schools` for "government schools" or the education categories for "all schools", never
  the sum of the two.
- **Matching is spatial, never by name.** 230 of the 2,210 government schools (10.4%) sit inside
  a different gazetted suburb from the locality in their address. The map context places them by
  location, so a count from here can legitimately differ from a count of schools whose address
  names the suburb.

### Response

Excerpt from a live response (NEWTOWN, `categories=train-station&detail=low`):

```json
{
  "schema_version": "propertyscope.suburb-map-context.v1",
  "geography": "nsw-gazetted-suburb",
  "suburb": {
    "suburb_id": "108033102", "name": "NEWTOWN", "postcode": "2042", "state": "NSW",
    "geometry_status": "valid",
    "centroid": [151.179351, -33.898591],
    "label_point": [151.178084, -33.899877],
    "bbox": [151.171164, -33.908812, 151.189303, -33.890976],
    "boundary": {
      "type": "Feature", "id": "108033102",
      "properties": {"suburb_id": "108033102", "name": "NEWTOWN", "postcode": "2042",
                     "detail": "low", "tolerance_degrees": 0.0005,
                     "source_vertex_count": 675, "display_vertex_count": 29},
      "geometry": {"type": "Polygon", "coordinates": ["..."]}
    }
  },
  "request": {"categories": ["train-station"], "detail": "low", "tolerance_degrees": 0.0005,
              "limit": 500, "operational": "current"},
  "layers": {
    "train-station": {"type": "FeatureCollection", "features": [
      {"type": "Feature", "id": "train-station:504378880",
       "properties": {"amenity_id": "train-station:504378880", "category": "train-station",
                      "name": "NEWTOWN RAILWAY STATION", "source_feature_id": "504378880",
                      "source_updated_at": "2014-05-27T15:56:45Z", "match": "covers",
                      "operational_status": "operational", "operational_status_code": 1},
       "geometry": {"type": "Point", "coordinates": [151.17964, -33.897843]}}
    ]}
  },
  "coverage": {"boundary": "accepted", "train-station": "accepted"},
  "layer_details": {
    "train-station": {"category": "train-station", "dataset_id": "nsw-amenities",
                      "predicate": "ST_Covers", "matched_count": 1, "eligible_count": 1,
                      "excluded_non_operational": 0, "excluded_invalid_geometry": 0,
                      "excluded_missing_geometry": 0, "feature_count": 1,
                      "truncated": false, "reason": null, "stale": false, "...": "..."}
  },
  "releases": {"boundary": {"...": "..."}, "train-station": {"...": "..."}},
  "truncated": false,
  "limits": {"max_categories": 12, "default_layer_limit": 500, "max_layer_limit": 1000,
             "max_response_vertices": 60000, "max_response_bytes": 4194304,
             "coordinate_decimals": 6},
  "response_vertices": 30
}
```

Coordinates are WGS84 `[longitude, latitude]` with six decimal places, so you can pass them
straight to MapLibre. The full, schema-valid examples are in the contract fixtures:
`suburb-map-context.v1.valid.json`, `suburb-search.v1.valid.json` and
`suburb-detail.v1.valid.json`.

Feature properties by layer:

- **`schools`.** `properties` is exactly the published `school-points.v2` record that your
  importer already stores, including `school_code`, `school_name`, `school_type`,
  `operational_status`, `lga` and `provenance`. Join on `school_code`.
- **Point amenities.** Each has an `amenity_id` (`<category>:<publisher id>`), a `name`, and
  `operational_status`: `operational`, `non-operational`, or `null` when the publisher gives no
  status. The raw `operational_status_code` is also included. The publisher documents no code
  list. Code 1 matches open facilities. Code 6 matches closed ones, such as Sydney's three
  monorail stations, which closed in 2013.
- **`protected-reserve`.** Each has the publisher's `reserve_type` code (`NR` nature reserve, `NP` national park, `SC` state conservation area, and a few others such as `AA`, `RP`, `HS` and `KC`) and a
  `coverage_note`. Large reserves are clipped to the suburb's bbox plus a 10% margin, so
  Kosciuszko does not send 62,000 vertices to a Thredbo map. When this happens,
  `display_clipped: true` is set. Do not compute areas from display geometry.

### Coverage states

`coverage` has one entry for `boundary` and one for each requested category.

| State | Meaning | What to show |
|---|---|---|
| `accepted` | Complete answer from the current accepted release | The layer |
| `partial` | Some matching features are missing: the layer was truncated by `limit`, or the source has invalid or missing geometry near this suburb | The layer, plus "some features not shown" |
| `stale` | Complete, but the release was acquired more than `freshness_days` (400) ago | The layer, plus the `acquired_at` date |
| `unavailable` | No answer, for the reason in `layer_details[category].reason` | A note instead of an empty layer |

**An empty `accepted` layer is a real zero.** For example, PARRAMATTA has no protected reserves.
An `unavailable` layer means *unknown*. Never show "0" for an unavailable layer.

When several states apply, the most severe one is reported, in the order
`unavailable` > `partial` > `stale` > `accepted`.

`reason` values:

| Reason | Cause |
|---|---|
| `dataset_unavailable` | No accepted release exists for that dataset, so the layer could not be answered |
| `unsupported_schema` | The accepted release uses a schema version this API does not read |
| `layer_not_in_release` | The accepted amenity release does not contain that source layer |
| `boundary_geometry_unavailable` | The suburb's own boundary is invalid in the source, so nothing can be matched spatially. Only CAMBEWARRA (`108029947`) is affected today. It still has a `bbox` for camera fitting, but its boundary geometry is `null` |

A layer counts as `partial` if any row anywhere in that layer has no geometry. This is
deliberately conservative: a feature without a location cannot be placed in or out of a suburb.
No accepted layer has any such rows today.

### Truncation and size limits

- Each layer returns at most `limit` features, ordered by name. When more match,
  `layer_details[c].truncated` is `true`, the coverage is `partial`, and the top-level
  `truncated` is `true`. `eligible_count` still reports the full total, so you can show
  "showing 500 of 812".
- The whole response is capped at 60,000 vertices and 4 MiB. A request over either limit is
  rejected with `422 response_limit_exceeded` rather than silently cut. Retry with a lower
  `detail` or fewer categories. No real NSW suburb comes near these limits: the largest observed
  response was 5,606 vertices and 144 KB.

## Caching and revalidation

`/suburbs/{id}` and `/suburbs/{id}/map-context` return a strong `ETag` and
`Cache-Control: no-cache`.

- **What the ETag covers.** It identifies the exact request, after normalisation, together with
  the accepted releases that answered it. It changes as soon as any of those releases is
  replaced. A cached copy is therefore valid only until the next publication, and
  revalidating is cheap.
- **How to revalidate.** Send `If-None-Match` with the stored ETag. A `304 Not Modified` has no
  body: reuse your copy.
- **Wildcards.** `If-None-Match: *` is not honoured and returns a normal `200`.
- **Feature 3's `HttpClient` needs one change.** `urllib` raises `HTTPError` for a 304, so the
  current client would turn it into a `ServiceError`. Handle it explicitly:

```python
import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

API = "/api/data-platform/v1"


@dataclass(frozen=True)
class CachedMap:
    etag: str
    body: dict[str, Any]


def fetch_suburb_map(
    base_url: str,
    suburb_id: str,
    *,
    categories: list[str],
    zoom: int,
    request_id: str,
    cached: CachedMap | None = None,
    timeout: float = 4.0,
) -> CachedMap:
    query = urlencode({"categories": ",".join(categories), "zoom": zoom})
    headers = {"Accept": "application/json", "X-Request-ID": request_id}
    if cached is not None:
        headers["If-None-Match"] = cached.etag
    url = f"{base_url}{API}/suburbs/{quote(suburb_id, safe='')}/map-context?{query}"
    try:
        with urlopen(Request(url, headers=headers), timeout=timeout) as response:
            return CachedMap(response.headers["ETag"], json.loads(response.read()))
    except HTTPError as exc:
        if exc.code == 304 and cached is not None:
            return cached
        raise  # map to your ServiceError as HttpClient.request does
```

Key the cache on `(suburb_id, categories, detail-or-zoom, limit, operational)`. A small
in-process LRU is enough: the payload for a typical suburb is 10–60 KB.

## Errors

Every error is an RFC 9457 `application/problem+json` body with a stable `code` and the echoed
request ID.

| Status | `code` | When | Consumer action |
|---|---|---|---|
| 422 | `invalid_request` | Bad or unknown parameter, malformed `suburb_id`, `zoom` together with `detail`, more than 12 categories, `limit` out of range | Fix the request; do not retry |
| 422 | `unsupported_category` | Unknown category, including `parks` | Fix the request; the `detail` names the alternative |
| 422 | `response_limit_exceeded` | Response would exceed 60,000 vertices or 4 MiB | Retry with lower `detail` or fewer categories |
| 404 | `suburb_not_found` | `suburb_id` is not in the accepted release | Re-resolve the name with search; the ID may predate a boundary change |
| 503 | `suburb_boundaries_unavailable` | No accepted suburb release, or its display projection is not built yet | Show "suburb maps unavailable"; retry later |
| 503 | `read_budget_exceeded` | The read exceeded its 3.5 s budget | Retry once with backoff |

## Versioning and compatibility

- **Schema version.** Each response states its `schema_version`. The `v1` shapes are closed:
  unknown properties fail validation. Any change to a field's type or meaning, and any new field,
  ships as a new `v2` schema and path version. A `v2` would run alongside `v1`, not replace it in
  place.
- **New categories.** Adding a category key to the registry is additive. Existing requests are
  unchanged, but the default category set will never change within `v1`.
- **Freshness.** Releases are swapped atomically by publication. Every layer names the exact
  release that answered it, in `releases[category].dataset_release_id`, together with publisher,
  licence and acquisition dates. Show the publisher attribution ("© NSW Spatial Services",
  "NSW Department of Education") on the map.

## Testing your integration

- **Unit tests.**
  - Copy the three `*.valid.json` fixtures into your own test data and validate your parser
    against the schemas from the product-contract package. Feature 1 regenerates these fixtures
    from a PostGIS test world, and its contract tests check them against the schemas.
  - The `invalid-*` fixtures show shapes your parser must reject.
  - Your code must not import Feature 1 Python or read its repository paths at runtime.
- **Live checks.** Run Feature 1's endpoint tests against your stack:

  ```bash
  PROPERTYSCOPE_ENDPOINT_BASE_URL=http://localhost:5200 uv run pytest student-1/tests/endpoints/test_suburb_map_endpoint.py -m endpoint --no-cov -q
  ```

- **Data in your stack.** A freshly seeded stack has no suburb boundaries or amenities, so search
  answers `dataset_unavailable`. Load real data with the `feature-1-data` skill:

  ```bash
  uv run scripts/dev.py data collect nsw-suburb-boundaries
  ```

  Do the same for `nsw-amenities` and `nsw-government-schools`, then review and publish them.

## Not provided

- Fuzzy, prefix or autocomplete search.
- Viewport, radius or vector-tile (MVT) queries. Each request covers exactly one suburb.
- Shared topology between neighbouring suburbs. Each outline is simplified on its own, so
  adjacent suburbs can show hairline gaps or overlaps at `low` detail.
- Repair of invalid source boundaries.
- Complete park or green-space coverage.
- Any statement of school catchment, enrolment eligibility or facility capacity. Points are
  locations only.
