# Shared frontend and design system

This directory owns only domain-neutral browser concerns for the integrated PropertyScope
application: the unified entry point, navigation, honest availability labelling, common design
tokens and shared interaction primitives. Feature-specific behavior remains inside the
independently buildable `student-N/frontend/` services.

## Files

- `index.html` — unified entry point covering all five features and shared operational surfaces.
- `app.js` — shell composition root for home/search, bounded hash routing and mobile navigation.
- `features.js` — the bounded five-area navigation registry and canonical feature ingress paths.
- `browser/index.js` — stable public JavaScript barrel for domain-neutral DOM helpers.
- `integrations.js` — validation and failure-safe loading for feature-owned shell adapters.
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
Features 2–5 have reserved registry/base-path entries but no live edge route until their complete
feature slice is implemented and enabled.

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
Property records is linked as a live user journey; the other areas remain visibly unavailable and
do not fall through to Feature 1. Data and agent operations are secondary operator destinations.
The shell does not infer service health from a static page or claim future functionality is running.

## Public frontend boundary

Feature frontends consume Shared JavaScript only through documented `index.js` barrels. The current
public modules are `browser/index.js` for domain-neutral DOM construction and `mapping/index.js` for
the map controller/provider contract. Files beside those barrels are implementation details and may
change without a feature migration contract. CSS remains public only through the documented
`design-system/` assets and `--ps-*`/`.ps-*` surface.

An enabled feature may provide a shell adapter from its own frontend ingress. Feature 1 owns
`/features/data-platform/integration/shell.js`, which projects its search route, published-release
response, owned health dependencies and activity links into the domain-neutral shape consumed here.
Shared loads that module at runtime and never imports Feature 1 source. If the feature is unavailable,
the shell retains registry navigation and reports unavailable evidence without inventing domain data.
`scripts/validate_architecture.py` enforces both the Shared-to-feature prohibition and public-barrel
imports in the canonical quality gate.

## Shared dashboards

The framework-free shell exposes four shared hash routes:

```text
http://localhost:5100/#features
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
uv run scripts/dev.py up
```

Open `http://localhost:5100`. The shell remains an independently built container and the development
overlay bind-mounts its source for the same edit-refresh loop as the other frontends.
