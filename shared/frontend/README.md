# Shared frontend and design system

This directory owns only domain-neutral browser concerns for the integrated PropertyScope
application: the unified entry point, navigation, honest availability labelling, common design
tokens and shared interaction primitives. Feature-specific behavior remains inside the
independently buildable `student-N/frontend/` services.

## Files

- `index.html` — unified entry point covering all five features and shared operational surfaces.
- `app.js` — tiny configuration/search/planned-capability behavior; no domain data access.
- `styles.css` — shell-specific composition.
- `Dockerfile` and `nginx.conf` — unprivileged static shell container with health and security headers.
- `design-system/tokens.css` — colour, typography, spacing, radius, shadow and evidence-state tokens.
- `design-system/base.css` — reset, typography, focus, skip-link and reduced-motion foundations.
- `design-system/components.css` — shared buttons, badges, cards, grids, search shell and toast.
- `design-system/README.md` — adoption contract, import order, evidence vocabulary and ownership rules.
- `design-system/CHANGELOG.md` — versioned record of shared visual/API changes.
- `operations/ai-mode/` — existing read-only AI-mode run evidence interface, intentionally retained.

## Runtime links

Defaults target the current local services:

```text
Property discovery  http://localhost:5200/#properties
Data operations     http://localhost:5200/#overview
Agent runs          http://localhost:5005/operations/ai-mode/
```

A future edge/container may override them before `app.js` loads:

```html
<script>
  window.PROPERTYSCOPE_CONFIG = {
    propertyDiscovery: "/features/data-platform/#properties",
    dataOperations: "/features/data-platform/#overview",
    agentRuns: "/operations/ai-mode/"
  };
</script>
```

The shell presents product research areas rather than assignment feature/release terminology. Only
Property records is linked as a live user journey; the other areas remain visibly unavailable and
do not fall through to Feature 1. Data and agent operations are secondary operator destinations.
The shell does not infer service health from a static page or claim future functionality is running.

## Local shared-shell container

The shared shell is part of the canonical Release 0 development topology. Start it with the rest
of the application from the repository root:

```bash
uv run scripts/dev.py up
```

Open `http://localhost:5100`. The shell remains an independently built container and the development
overlay bind-mounts its source for the same edit-refresh loop as the other frontends.
