# Shared design-token and layout foundation

## Ownership and source

`shared/frontend/design-system/tokens.css` is the one token source for Shared, Feature 1 and the
shared AI activity view. Feature styles may keep private aliases while call sites migrate, but
those aliases resolve to `--ps-*` semantic roles and must not redeclare shared tokens.

The foundation separates semantic intent from palette values:

| Concern | Public roles |
|---|---|
| Colour | `--ps-color-background`, `surface`, `surface-elevated`, `text`, `text-muted`, `border`, `focus`, `accent`, `success`, `warning`, `danger`, `disabled-*` and inverse/overlay roles |
| Typography | `--ps-text-caption`, `label`, `body`, `body-large`, `heading-small`, `heading-medium`, `heading-large` and `display` |
| Rhythm | the 4px-based `--ps-space-*` scale plus small/default/large layout gaps |
| Density | 34px compact and 42px comfortable controls, with a separate 58px large/search control |
| Shape and elevation | border widths, six radii and four elevations |
| Layout | readable, standard and wide content widths plus one responsive page gutter |
| Motion | fast/normal/slow durations, standard/exit easing and the existing reduced-motion override |
| Layers | shell, sticky, dropdown, popover, drawer, dialog, toast and skip-link ordering |

## Density profiles

Property Discovery sets `data-density="comfortable"` on its route host. Data Operations uses
`data-density="compact"`. Both profiles use the same controls and tokens; density changes control
height/padding and does not fork colours, focus treatment or component behaviour. At narrow widths,
core task reachability remains the requirement; dense tables retain their intentional contained
scrolling rather than being mechanically cardified.

## Layout primitives

The dependency-free CSS public surface remains intentionally small:

- `ps-container` for the shared content width and responsive gutter;
- the existing `ps-stack`, `ps-cluster` and explicit `ps-grid-*` helpers; and
- `ps-sr-only`, the existing visually-hidden primitive.

No gallery-only layout API was added. A new domain-neutral helper should wait until real production
call sites need it. Feature-specific table columns, map geometry, workflow panels and property
language stay in Feature 1.

## Reference and validation

Serve the repository through its normal fixture or Shared host, then open
`/design-system/gallery.html`. The page renders semantic colours, type roles, spacing, shape,
elevation, widths/gutter, motion/reduced-motion guidance, layers, both density profiles, the retained
layout helpers and control states without a backend.

Run the lightweight source gate with:

```text
uv run python scripts/validate_frontend_styles.py
```

The checked-in `frontend-style-baseline.json` contains repository-relative reviewed exceptions.
The baseline records 112 reviewed raw-colour and 403 reviewed off-scale-spacing occurrences across
non-vendored production CSS. Raw colours include hex, RGB/HSL, modern colour functions and CSS
named colours; semantic keywords such as `currentColor`, `inherit` and `transparent` remain valid.
New occurrences fail the gate. A genuinely local exception needs an inline
`style-check: allow(reason)` comment with a concrete reason; intentional baseline review is explicit
through `--write-baseline`.

## Intentional visual changes and deferred local values

- Property Discovery controls use the comfortable 42px profile; operator routes use the compact
  34px profile. Existing `small` actions no longer drop below the compact height.
- Shared and Feature 1 page padding now resolve through one responsive gutter. Existing content
  width and laptop composition remain otherwise stable.
- Drawer, dialog, toast and skip-link layers now use named ordering rather than unrelated numbers.
- Dark headers use a separate high-contrast inverse focus ring; the ordinary teal ring remains on
  light surfaces.
- Shared shadows, neutral tables, form borders and feedback surfaces consume semantic roles.

Raw values remain where they describe local artwork or geometry rather than a reusable decision:

- Shared home hero gradients, decorative rings and brand translucency;
- Feature 1 property hero decoration, dense table geometry and code/evidence surfaces;
- AI activity's fixed viewport workspace proportions; and
- shared map-provider geometry and renderer-specific styling.

Those values are recorded by the validator baseline; this task deliberately does not rewrite map or
table geometry merely to reduce a source-audit count.
