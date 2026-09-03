# Shared frontend and design system

This directory owns only domain-neutral browser concerns for the integrated PropertyScope
application: the unified entry point, navigation, honest availability labelling, common design
tokens and shared interaction primitives. Feature-specific behavior remains inside the
independently buildable `student-N/frontend/` services.

## Files

- `index.html` — unified entry point covering all five features and shared operational surfaces.
- `app.js` — shell composition root for home/search, bounded hash routing and mobile navigation.
- `features.js` — the bounded five-area navigation registry and canonical feature ingress paths.
- `fragments/research-areas.html` — same-origin HTMX projection of the five approved research areas.
- `vendor/htmx-2.0.10.min.js` — pinned local HTMX production build; provenance, licence and
  SHA-256 are recorded in `vendor/README.md`.
- `browser/index.js` — stable public JavaScript barrel for domain-neutral DOM helpers.
- `ai-chat/index.js` — reusable assistant client, polling, formatting, semantic states, accessible transcript controller and `createFeatureAssistant` route factory; feature vocabulary is injected by route wrappers.
- `feature-1-bridge.js` — bounded, failure-safe loading for Feature 1's public shell adapter.
- `core.js` — safe DOM, formatting, table and correlated public-request helpers.
- `capabilities.js` — static Release 0 deployment capability manifest; implemented and enabled remain separate.
- `routes/status.js` — live health summary for implemented shared and Property records services.
- `routes/evidence.js` — read-only accepted-release and durable agent-run reference index.
- `routes/roadmap.js` — honest current/planned capability roadmap.
- `routes/features.js` — registry-driven research-area directory without domain data composition.
- `styles.css` — shell-specific composition.
- `Dockerfile` and `nginx.conf` — unprivileged static shell container with health and security headers.
- `design-system/tokens.css` — colour, typography, spacing, radius, shadow and evidence-state tokens.
- `design-system/base.css` — reset, typography, focus, skip-link and reduced-motion foundations.
- `design-system/components.css` — shared buttons, badges, cards, grids, search shell and toast.
- `design-system/README.md` — adoption contract, import order, evidence vocabulary and ownership rules.
- `design-system/CHANGELOG.md` — versioned record of shared visual/API changes.
- `mapping/` — MapLibre/OpenFreeMap provider abstraction, bounded GeoJSON rendering, viewport
  loading, accessible layer controls, vendored renderer and adoption guide.
- `operations/ai-mode/` — existing read-only AI-mode run evidence interface, intentionally retained.

## Runtime links

The shared edge now uses canonical same-origin routes by default:

```text
Property discovery  http://localhost:5100/features/data-platform/#properties
Data operations     http://localhost:5100/features/data-platform/#overview
Agent runs          http://localhost:5100/operations/ai-mode/
```

Feature 1 remains directly reachable at `http://localhost:5200` for isolated development. Its
relative static assets and namespaced public API allow the same image to work at either ingress.
Features 2, 4 and 5 are enabled through manifest-generated live edge routes. Feature 3 retains a
reserved registry/base-path entry and remains visibly unavailable.

A deployment may override them in the same-origin `config.js` loaded before `app.js`:

```js
window.PROPERTYSCOPE_CONFIG = {
  propertyDiscovery: "/features/data-platform/#properties",
  dataOperations: "/features/data-platform/#overview",
  agentRuns: "/operations/ai-mode/",
};
```

The default file contains an empty object and is safe to replace or mount per environment. It must
not contain secrets. Keeping configuration in this external asset satisfies the shell's
`script-src 'self'` Content Security Policy; inline configuration is unsupported.

The shell presents product research areas rather than assignment feature/release terminology. Only
Manifest-enabled research areas are linked as live user journeys. Feature 3 remains visibly
unavailable and does not fall through to another feature. Data and agent operations are secondary
operator destinations.
The shell does not infer service health from a static page or claim future functionality is running.

## Shared-shell HTMX flow

The home-page research-area directory is the shared Release 0 HTMX slice. `index.html` contains an
understandable Property data fallback and a retry control, then HTMX performs a real same-origin
`GET /fragments/research-areas.html` and swaps the returned HTML into `#feature-area-list`. Nginx
serves shared static fragments directly and returns `404` for an unknown fragment instead of the
SPA shell. Feature 1 fragment paths have a separate backend proxy.

HTMX is vendored as version 2.0.10 from the upstream `htmx.org` npm distribution and runs with
evaluation and fragment script execution disabled. `dashboard.test.mjs` verifies its exact SHA-256
and compares every fragment row with `features.js`: ID, label, owner, canonical route,
`implemented`, and `enabled`. This deliberate parity check keeps the static no-build fragment honest;
only manifest-enabled features are interactive and Feature 3 remains planned.

Small external JavaScript listeners retain ownership of configuration-link projection, request
status, retry focus, and re-processing after the shell hash router restores the home markup. Maps,
AI chat and run timelines, adaptive polling, dashboards, and other existing routes intentionally
remain JavaScript because they need richer client state than an HTML swap provides.

## Public frontend boundary

Feature frontends consume Shared JavaScript only through documented `index.js` barrels. The current
public modules are `browser/index.js` for domain-neutral DOM construction and `mapping/index.js` for
the map controller/provider contract. Files beside those barrels are implementation details and may
change without a feature migration contract. CSS remains public only through the documented
`design-system/` assets and `--ps-*`/`.ps-*` surface.

The first implemented slice has one explicit, bounded bridge; this is not a generic feature plugin
framework. Feature 1 owns
`/features/data-platform/integration/shell.js`, which projects its search route, published-release
response, owned health dependencies and activity links into the domain-neutral shape consumed here.
Shared loads that module at runtime through the single allowlisted ingress and never imports Feature 1
source. The shell renders before the short optional load completes. If the feature is unavailable,
the shell retains registry navigation and reports unavailable evidence without inventing domain data.
`scripts/validate_architecture.py` enforces both the Shared-to-feature prohibition and public-barrel
imports in the canonical quality gate. Network-URL module imports fail closed rather than bypassing
same-origin ownership resolution.
Any later feature bridge requires a reviewed real call site and a separately allowlisted public ingress.

Assistant adoption does not require a Shared shell bridge. Feature-owned assistant routes use the
domain-neutral `createFeatureAssistant` export and the independent backend recipe in
[`docs/release-0/feature-client-adoption.md`](../../docs/release-0/feature-client-adoption.md).

## Shared dashboards

The framework-free shell exposes four shared hash routes:

```text
http://localhost:5100/#features
http://localhost:5100/#assistant
http://localhost:5100/#system-status
http://localhost:5100/#evidence
http://localhost:5100/#release-roadmap
```

System status checks only implemented components and excludes deliberately gated services from the
overall result. The evidence index reads bounded public API projections through same-origin Nginx
routes; it never accesses a feature database or interprets feature-owned business facts. Both views
preserve successful sections when a dependency is unavailable and retain request IDs where supplied.

## Local shared-shell container

The shared shell is part of the canonical Release 0 development topology. Start it with the rest
of the application from the repository root:

```bash
uv run scripts/dev.py stack up
```

Open `http://localhost:5100`. The shell remains an independently built container and the development
overlay bind-mounts its source for the same edit-refresh loop as the other frontends.

For deterministic validation, run `uv run scripts/dev.py ui serve`, open the printed Shared URL,
and inspect the request for `/fragments/research-areas.html`. Run `uv run scripts/dev.py ui smoke`
for the request/status/card-count assertions. Compose validation uses the same local HTMX asset and
fragment at `http://localhost:5100`; neither path needs internet access.
