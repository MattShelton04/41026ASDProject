# ADR-020: Share the browser mapping provider, not domain layers

- Status: Accepted
- Date: 23 August 2026
- Owner: Shared frontend / affected feature owners
- Related: ADR-016 and the feature integration and experience contract

## Context

The current PropertyScope frontend displays a styled placeholder behind a verified property
coordinate. Earlier `prototype/property` work proved MapLibre with OpenFreeMap, point and polygon
GeoJSON layers, viewport requests, cancellation, caps and layer toggles. Repeating those renderer,
provider, lifecycle and safety mechanics in up to five feature frontends would create inconsistent
coordinate handling, accessibility, CSP, fallback and performance behaviour.

The existing ownership baseline correctly keeps map meaning inside each feature. A shared mapping
implementation must therefore stay domain-neutral and must not become a shared spatial database or
an API that decides what a school, suburb, catchment, hazard, sale or planning layer means.

## Decision

The shared frontend owns a framework-free browser mapping package under
`shared/frontend/mapping/`.

- MapLibre GL JS 5.24.0 is the stable renderer and is vendored with its BSD-3-Clause licence.
- A small provider contract supplies a MapLibre style, attribution metadata and a local neutral
  fallback. OpenFreeMap Liberty is the default basemap and needs no application API key.
- Feature frontends supply bounded RFC 7946 GeoJSON and feature-owned labels, styles, popup fields,
  selection callbacks and viewport endpoints.
- Runtime validation enforces WGS84 longitude/latitude order, supported geometry kinds, closed
  polygon rings, homogeneous logical layers and browser feature/coordinate ceilings.
- Viewport loaders debounce movement, cancel superseded requests, discard late responses and honour
  zoom gates. Dense point layers can cluster. Polygon, line and point render ordering is shared.
- The package exposes only a narrow controller for data, visibility, viewport, camera, refresh,
  resize and destroy. It does not expose another feature's code or persistence.
- GeoJSON is the bounded Release 0 transport. Feature-owned MVT endpoints are the scale-up path when
  measured viewport payloads exceed the documented GeoJSON limits; MapLibre remains the renderer.

Feature ownership changes only at the technical seam. Each feature continues to own its routes,
map composition, API, data contract, coverage language, domain colour scale and user interactions.
The shared package owns provider selection, rendering mechanics and defensive browser policy.

## Consequences

All feature frontends can render points, lines and polygons consistently without adopting a JS
framework or a paid map SDK. Basemap failure does not erase verified data layers, and the browser
never needs statewide raw geometry. Self-hosted or commercial MapLibre styles can replace
OpenFreeMap through configuration without changing feature code.

The repository now carries about 1.1 MB of minified renderer assets and must retain the upstream
licence. The default experience still makes external tile/font/sprite requests, so CSP and privacy
documentation must name the host. Offline mode provides a neutral background, not offline street
tiles. A future commercial token must be origin-restricted and is never a secret once shipped to a
browser.

## Alternatives considered

- Keep one map implementation per feature: preserves maximal ownership but duplicates security,
  provider and lifecycle work and makes cross-feature behaviour inconsistent.
- Hard-code Mapbox or Google Maps: good hosted products, but introduces account, cost, token and
  licensing coupling that is unnecessary for the current scope.
- Use Leaflet with raster OpenStreetMap tiles: workable, but diverges from the proven prototype and
  weakens the direct vector-tile scale-up path.
- Build a custom renderer: avoids a dependency but recreates projection, WebGL, interaction,
  accessibility control and tile work without product value.
- Create a shared spatial backend: would violate feature/database ownership and create a new source
  of domain truth. Rejected.

## Validation

- Dependency-free Node tests cover GeoJSON validation, bounds, provider/layer contracts, viewport
  request construction, API failures and controller behaviour through an injected renderer.
- Feature 1 replaces its mocked property context with the shared provider over its existing public
  `map-context` API.
- The canonical quality gate and a live seeded-property browser scenario verify packaging, CSP,
  the same-origin API boundary and actual rendering.
