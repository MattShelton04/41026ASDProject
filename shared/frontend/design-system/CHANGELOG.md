# Design-system changelog

All notable changes to the shared PropertyScope frontend design system are recorded here.

## 0.3.0 — 2026-08-23

- Added semantic colour and typography roles over the existing palette and type scales.
- Added compact/comfortable density, responsive gutters/content widths, border, motion and named
  overlay-layer tokens.
- Normalised the existing container, cluster, stack and grid helpers without adding gallery-only
  layout primitives.
- Added a backend-free design-foundation gallery and a checked-in raw-colour/off-scale-spacing gate.
- Migrated Shared, Feature 1 and AI activity call sites in a bounded pass without rewriting local
  table, map or decorative geometry.

## 0.2.0 — 2026-08-22

- Added stable type-scale, line-height and weight tokens.
- Added shared control-height, shell-size, focus and layering tokens.
- Updated shared primitives and Feature 1 controls to consume the public token surface.
- Documented the token-extension rule so feature styles cannot silently redefine `--ps-*` values.

## 0.1.0 — 2026-08-15

- Established the `--ps-*` colour, type, spacing, shape, elevation and motion tokens.
- Added semantic evidence states for confirmed, partial, conflicting, unknown, danger and info.
- Added accessible base typography, focus treatment, skip-link and reduced-motion foundations.
- Added shared layout, button, badge, card, input-shell, status-list and toast primitives.
- Introduced the first unified five-feature application shell and release-aware capability labels.
- Kept feature domain models, CRUD behavior and API clients outside the shared package.
