# Shared browser mapping provider

This package is the domain-neutral map boundary for PropertyScope frontends. It renders bounded
GeoJSON with MapLibre GL JS, selects a basemap through a small provider contract, and exposes one
controller for data, visibility, viewport, camera and lifecycle interactions. A feature still owns
the meaning of every layer, its API, its popups and any domain-specific colour scale.

The default provider follows the proven `prototype/property` approach:

- renderer: vendored MapLibre GL JS 5.24.0 (BSD-3-Clause);
- basemap: OpenFreeMap Liberty, with OpenStreetMap attribution supplied by the style;
- failure mode: a local neutral style so points and polygons remain usable if tiles are offline;
- data: RFC 7946 GeoJSON in WGS84 longitude/latitude order; and
- scale-up path: viewport-bounded GeoJSON now, vector tiles for genuinely large layers later.

The checked-in MapLibre distribution avoids a runtime script CDN, works with `script-src 'self'`,
and makes the production image reproducible. Only basemap style, tile, sprite and glyph requests go
to `https://tiles.openfreemap.org`. See `vendor/MAPLIBRE-LICENSE.txt` for its licence.

## Use it in a feature frontend

Serve or copy this whole directory at `/mapping`, load the small shared map styles, then start the
feature's ES modules:

```html
<link rel="stylesheet" href="./mapping/mapping.css?v=2">
<script type="module" src="./app.js"></script>
```

`createMap()` loads the self-hosted MapLibre script and stylesheet on first use and shares that
promise across concurrent maps. Pages that never create a map therefore do not download or parse
the roughly 1 MB renderer bundle. Tests can inject a compatible `renderer` object directly.

The page CSP needs the following additions for the default provider. Keep scripts and styles
self-hosted:

```text
connect-src 'self' https://tiles.openfreemap.org;
img-src 'self' data: blob:;
worker-src blob:;
```

Create a point map from Feature 1's existing
`GET /api/data-platform/v1/properties/{property_ref}/map-context` response:

```js
import {
  createMap,
  createOpenFreeMapProvider,
  featureCollection,
  pointFeature,
} from "./mapping/index.js";

const context = await fetch(`/api/data-platform/v1/properties/${propertyRef}/map-context`)
  .then((response) => response.json());

const map = await createMap({
  container: document.querySelector("#map"),
  provider: createOpenFreeMapProvider(),
  layers: [{
    id: "property",
    label: "Property",
    kind: "point",
    data: featureCollection([
      pointFeature(context.longitude, context.latitude, {
        address: context.address_display,
      }, context.property_ref),
    ]),
    popup: { title: "address" },
  }],
  view: { center: [context.longitude, context.latitude], zoom: 16 },
});
```

`createMap()` fits all initial data when `view.bounds` and `view.center` are omitted. Polygon layers
are inserted before lines and points, so school or property markers remain visible over suburb,
catchment, planning or hazard areas.

## Layer contract

Each layer has this stable shape. The implementation is plain JavaScript with JSDoc/runtime checks,
so framework and non-framework frontends can use the same interface.

| Field | Required | Meaning |
|---|---:|---|
| `id` | yes | Stable lowercase kebab-case id, maximum 63 characters. |
| `label` | recommended | Accessible/user-facing layer name. |
| `kind` | yes | `point`, `line`, or `polygon`; mixed geometry kinds belong in separate layers. |
| `data` | one of | A GeoJSON FeatureCollection. Mutually exclusive with `load`. |
| `load(viewport)` | one of | Async viewport loader returning a FeatureCollection. Receives `bbox`, `zoom`, and `signal`. |
| `visible` | no | Initial visibility; defaults to `true`. |
| `minZoom` / `maxZoom` | no | Prevent an expensive loader from running at unsafe zooms. |
| `cluster` | no | Enables MapLibre point clustering for dense point layers. |
| `style` | no | Renderer-neutral colour, opacity, radius/width and stroke values. |
| `popup` | no | Safe text-only `{title, fields}` projection; it never inserts API HTML. |
| `onSelect` | no | Feature-owned click callback. |
| `maxFeatures` | no | Browser safety ceiling, default 10,000 and hard maximum 50,000. |
| `maxCoordinates` | no | Browser safety ceiling, default 250,000 and hard maximum 1,000,000. |

Example with a suburb polygon and clustered schools:

```js
const map = await createMap({
  container,
  layers: [
    {
      id: "suburb-boundary",
      label: "Suburb boundary",
      kind: "polygon",
      data: suburbBoundary,
      style: { color: "#0f766e", opacity: 0.16 },
      popup: { title: "locality", fields: [{ label: "Boundary edition", property: "edition" }] },
    },
    {
      id: "schools",
      label: "Schools",
      kind: "point",
      data: schools,
      cluster: true,
      style: { color: "#238636", radius: 6 },
      popup: {
        title: "school_name",
        fields: [
          { label: "Type", property: "school_type" },
          { label: "Status", property: "status" },
        ],
      },
    },
  ],
});
```

The current Feature 1 data maps directly to these contracts:

| Product/API field | Map representation |
|---|---|
| Property `longitude`, `latitude`, `address_display`, `property_ref` | Point geometry; label/ref properties. |
| G-NAF/property-release `geometry` | Point geometry already emitted by PostGIS as GeoJSON. |
| School `geometry`, `school_code`, `school_name`, `school_type`, `status` | Point geometry and safe popup properties. |
| Future suburb/catchment/planning/hazard geometry | Polygon or MultiPolygon in a feature-owned bounded API. |

Do not infer a suburb boundary from the extent of its addresses, and do not claim a catchment,
hazard or planning area unless its owning feature publishes that geometry and coverage evidence.

## GeoJSON rules

`validateFeatureCollection()` enforces the browser boundary before data reaches MapLibre:

- use WGS84/EPSG:4326 positions in `[longitude, latitude]` order;
- omit the deprecated GeoJSON `crs` member and transform server-side;
- close every polygon ring and keep each layer geometry-homogeneous;
- send JSON properties only, never trusted HTML;
- clip polygons to the requested viewport and use `ST_SimplifyPreserveTopology` for display copies;
- retain precise/source geometry in the owning store rather than sending it to the browser; and
- return an explicit empty FeatureCollection when coverage is known but has no features.

An unavailable dataset is different from a valid empty layer. Express unavailable/partial/stale
coverage beside the map; never turn a missing layer into a no-risk or no-feature claim.

## Viewport API interaction

Large suburb, school or area collections should use `createViewportLoader()` rather than embedding
statewide data. It sends a bounded request after pan/zoom settles, cancels the previous request, and
drops late responses:

```js
import { createViewportLoader } from "./mapping/index.js";

const loadSchools = createViewportLoader({
  url: "/api/schools/v1/map-layers",
  layer: "schools",
  extra: { status: "open" },
  maxResponseBytes: 5_000_000,
});

await createMap({
  container,
  layers: [{
    id: "schools",
    label: "Schools",
    kind: "point",
    load: loadSchools,
    minZoom: 10,
    cluster: true,
  }],
});
```

The request is:

```text
GET /api/schools/v1/map-layers?bbox=west,south,east,north&zoom=12&layers=schools&status=open
Accept: application/geo+json, application/json
```

The API may return a FeatureCollection directly, a named top-level layer, or a `layers` envelope:

```json
{
  "schema_version": "propertyscope.map-layers.v1",
  "bbox": [151.18, -33.91, 151.25, -33.84],
  "layers": {
    "schools": {"type": "FeatureCollection", "features": []}
  },
  "coverage": {"schools": "accepted"},
  "truncated": false
}
```

If an API uses a different envelope, pass a `select(payload)` function. A production endpoint should
validate `west < east`, `south < north`, maximum bbox area, an allowlisted layer list, maximum zoom,
per-layer feature/coordinate/byte caps, and response caching. Return `400` for an unsafe viewport
instead of silently returning a misleading sample. Include `truncated: true` when a documented cap
is reached. The browser loader enforces the byte cap from `Content-Length` before reading when it is
available and verifies the actual UTF-8 body size before parsing.

For layers that routinely exceed tens of thousands of features per viewport, publish vector tiles
(MVT) from the owning backend/database boundary instead of continually raising GeoJSON caps. The
provider abstraction deliberately keeps MapLibre stable so that future tile sources do not require
a renderer rewrite.

## Controller API

The promise returned by `createMap()` resolves to:

| Method/property | Use |
|---|---|
| `provider` | Read provider id, label, attribution and whether the basemap is `ready` or `fallback`. |
| `layerIds` / `layerState(id)` | Build an accessible legend or inspect visible/count/loading state. |
| `setLayerData(id, geojson)` | Replace one source after validation without rebuilding the map. |
| `setLayerVisible(id, visible)` | Toggle every rendered part of a logical layer. |
| `getViewport()` | Read `[west, south, east, north]` and zoom. |
| `refresh()` | Explicitly rerun visible viewport loaders. |
| `fitToData(ids?, options?)` | Fit the camera to selected logical layers. |
| `flyTo({longitude, latitude, zoom})` | Move to a selected result. |
| `resize()` | Recalculate after a hidden panel/dialog becomes visible. |
| `destroy()` | Abort loads, disconnect observers and release WebGL resources. |

`mountLayerControls(controller, container)` provides a small accessible checkbox legend. A custom
feature legend can use the same controller instead. `mountMapHelp(container, {text})` adds a compact
bottom-left information button whose text opens on hover or focus and can be pinned with click,
tap, Enter or Space without covering the map permanently.

Primary-button drag pans the map normally. Ctrl/Command + primary-button drag rotates and pitches
the map using MapLibre's native directions and sensitivity. Right-button rotation, wheel, touch,
keyboard and navigation-control interactions also remain renderer-native.

Hiding a viewport-loaded layer aborts its request and clears its data. Moving outside its zoom gate
does the same, preventing stale features from remaining visible; showing it or returning to its zoom
range requests the current viewport again. Superseded responses cannot replace newer data or reset
the newer request's loading state. Removing the map container or aborting the optional `signal`
automatically releases requests, observers and WebGL resources, including during style startup.

## Swap the basemap provider

Rendering does not change when a provider changes. Supply a provider with a MapLibre style URL or
style object plus a fully local version-8 fallback:

```js
const provider = {
  id: "deployment-map-style",
  label: "Deployment map style",
  style: window.PROPERTYSCOPE_CONFIG.mapStyleUrl,
  fallbackStyle: NEUTRAL_STYLE,
  attribution: [{ label: "Required data attribution", url: "https://example.test/licence" }],
};
```

Provider attribution is validated and added to MapLibre's visible attribution control. Set
`attributionInStyle: true` only when the style itself already supplies every required attribution,
as OpenFreeMap Liberty does, to avoid duplicate credits.

Provider selection belongs in external deployment configuration; never put an API key in a
checked-in URL, browser bundle, inline script or repository `.env`. If a commercial provider needs a
browser token, restrict it by origin and scopes and document its cost/quota/failure policy.

## Verification

Run the dependency-free mapping tests and the canonical gate:

```text
node --test shared/frontend/mapping/mapping.test.mjs
uv run python scripts/check.py
```

For a live candidate, run `uv run scripts/dev.py stack up --offline`, open Property search, choose a seeded
address, and verify the real map shows the selected point. Also verify keyboard controls, attribution,
the neutral fallback message with the tile host blocked, and that leaving the route releases the map.
