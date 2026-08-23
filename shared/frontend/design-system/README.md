# PropertyScope frontend design system

A dependency-free, CSS-first foundation for the shared shell and the five independently owned
frontend microservices. The system standardises visual language and accessibility without turning
the shared directory into a domain-component monolith.

## Import order

```html
<link rel="stylesheet" href="./design-system/tokens.css">
<link rel="stylesheet" href="./design-system/base.css">
<link rel="stylesheet" href="./design-system/components.css">
<link rel="stylesheet" href="./styles.css">
```

These base-path-compatible relative imports work when a frontend is served independently or below
its canonical `/features/<slug>/` edge path. The feature stylesheet comes last and may compose
shared primitives, but should not redefine token values locally.

## Stable public surface

- `--ps-*` custom properties in `tokens.css`
- `.ps-container`, `.ps-cluster`, `.ps-stack`, `.ps-grid*`
- `.ps-density--compact` and `.ps-density--comfortable`
- `.ps-button` with primary, danger, quiet, small, disabled and busy states
- `.ps-badge` and evidence/release modifiers
- `.ps-card` and card elements
- `.ps-input-shell`, `.ps-status-list`, `.ps-toast`
- `.ps-table-region` and `.ps-table-scroll-hint` for named, contained horizontal table scrolling
- `.ps-sr-only` and `.ps-skip-link`

Classes without the `ps-` prefix remain private to a page or feature.

## Token categories

Use shared tokens for concepts that should look and behave alike across features:

- `--ps-type-*`, `--ps-leading-*` and `--ps-weight-*` for the common type scale;
- `--ps-ink-*`, `--ps-ocean-*`, surface and semantic-state tokens for colour;
- `--ps-space-*`, semantic layout gaps, responsive gutters, content widths, density-specific
  `--ps-control-height*` values and `--ps-shell-*` for rhythm and shell sizing;
- `--ps-radius-*` and `--ps-shadow-*` for shape and elevation; and
- `--ps-motion-*`, `--ps-ease-*`, `--ps-focus-*` and named `--ps-z-*` layers for shared interaction behaviour.

The rendered development reference is `design-system/gallery.html`. It uses the existing layout
helpers; gallery-specific presentation classes are not a public component API. The full inventory,
migration notes and raw-value convention are documented in `docs/ui/design-token-foundation.md`.

Feature styles may introduce private layout variables, but must not redeclare a `--ps-*` token.
If the shared value is unsuitable, propose a new semantic token instead of silently overriding it.

## Evidence vocabulary

Use semantic states consistently:

| State | Meaning | Never use it to mean |
|---|---|---|
| Confirmed | Supported by current, attributable evidence | Merely successful HTTP response |
| Partial | Some required evidence is present, with a visible limitation | Generic warning |
| Conflicting | Sources or observations disagree | Application error |
| Unknown | Evidence is absent or cannot be interpreted | Zero or false |
| Planned | Designed but not active in the current release/runtime | Disabled because of an outage |

Operational health, data readiness, evidence quality and feature availability are distinct states.

## HTMX and JavaScript ownership

Shared CSS should work with server-rendered HTML and HTMX fragments. Feature frontends own their
routes, forms, domain tables and CRUD behavior. Use small JavaScript islands only for behavior that
HTMX or native HTML cannot express well, such as maps, charts, adaptive polling and complex
review dialogs.

Do not place feature API clients, entities or business rules in this directory.

Domain-neutral JavaScript is a separate public surface. Import DOM helpers from
`browser/index.js` and mapping behavior from `mapping/index.js`; do not deep-import files beside
those barrels. A feature-specific shell projection belongs in that feature's frontend integration
directory, not in this design-system package.

The browser barrel also exposes the small interaction helpers used by real call sites: mobile
drawer focus containment, replacing status toasts and named table-scroll regions. Native dialogs
retain platform focus trapping; Feature 1 owns its form-specific dirty-state
and mutation lifecycle.

## Accessibility baseline

- one visible `main` landmark and a skip link;
- native buttons, links, forms, dialogs and headings before custom interaction;
- visible keyboard focus;
- text labels in addition to colour/icon states;
- minimum 42px interactive target height where practical;
- reduced-motion support;
- responsive layouts down to 320px; and
- status announcements through an appropriate live region.

## Change control

Treat tokens and shared classes as an API. Changes should include:

1. a rationale and affected screens;
2. browser and keyboard evidence;
3. a migration note for breaking changes; and
4. an entry in `CHANGELOG.md`.
