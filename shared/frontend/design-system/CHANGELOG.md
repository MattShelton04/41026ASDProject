# Design-system changelog

All notable changes to the shared PropertyScope frontend design system are recorded here.

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
