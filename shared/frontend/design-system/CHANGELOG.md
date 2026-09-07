# Design-system changelog

## 2026-09-07 — Release 1 grounded evidence

The shared assistant extends Fieldbook with typed findings, keyboard-accessible source inspection,
source/index dates, evidence-kind and corpus-version labels, confidence rationale and explicit
insufficient-context states. It uses existing public tokens and native disclosures; no migration
or token changes are required. Availability views now distinguish implemented MCP/RAG from observed
configuration and health. Grounding Node behavior tests cover safe links, text-only rendering,
source focus and changed-evidence presentation; browser fixture checks exercise narrow layouts.

## 2026-09-07 — Fieldbook

Evergreen/mineral evidence palette, outlined parcel identity, shared navigation, research/operator density,
44px comfortable controls, 100/160/240ms motion, reduced-motion-safe skeletons and consistent evidence grammar.
Public token names and independent frontend ownership remain compatible. See the overhaul deliverables
for the route inventory, assistant interaction contract, browser findings and explicit validation limits.

All notable changes to the shared PropertyScope frontend design system are recorded here.

## 0.5.0 — 2026-08-26

- Added the dependency-free `ai-chat/index.js` public component barrel for application-global and
  feature-scoped assistant wrappers.
- Standardised accessible turn status, evidence disclosures, durable run links, cursor polling,
  degraded refresh states and responsive chat composition without exposing private reasoning.
- Kept feature scope labels, suggestions, context projection and same-origin API roots injectable so
  the shared component does not acquire feature-owned vocabulary or tool rules.

## 0.4.0 — 2026-08-25

- Increased the shared body, label and caption roles so dense operational views remain readable.
- Raised compact controls to 38 pixels and comfortable controls to the 44-pixel touch baseline.
- Normalised mobile buttons, shell navigation, search and footer links to reliable touch targets.
- Relaxed shared body leading for clearer long-form and supporting copy.

## 0.3.0 — 2026-08-23

- Added semantic colour and typography roles over the existing palette and type scales.
- Added compact/comfortable density, responsive gutters/content widths, border, motion and named
  overlay-layer tokens.
- Normalised the existing container, cluster, stack and grid helpers without adding gallery-only
  layout primitives.
- Added a backend-free design-foundation gallery and a checked-in raw-colour/off-scale-spacing gate.
- Migrated Shared, Feature 1 and AI activity call sites in a bounded pass without rewriting local
  table, map or decorative geometry.
- Added the retained danger/busy button states and a named contained table-scroll region.
- Added browser helpers for the existing mobile drawer, status toast and table-scroll call sites;
  native Feature 1 dialogs now return focus and lock page scroll through their form lifecycle.

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
