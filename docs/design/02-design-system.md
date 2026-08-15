# PropertyScope NSW design system

## 1. Purpose

The design system gives five independently implemented frontends and shared operational surfaces a
single visual and interaction language without centralising domain code. It is deliberately small,
CSS-first and compatible with HTML/HTMX/vanilla JavaScript.

The reference implementation is in:

```text
repo-overlay/shared/frontend/design-system/
├── tokens.css
├── base.css
└── components.css
```

The polished prototype uses the same design direction in `prototype/styles.css`.

## 2. Brand direction

### Positioning

- calm, analytical and trustworthy;
- evidence-led rather than “AI magic”;
- recognisably connected to NSW landscape colours without imitating NSW Government branding;
- professional enough for data operations, approachable enough for a buyer workflow; and
- visually explicit about uncertainty, review and release status.

### Wordmark

Use **PropertyScope NSW** with the descriptor **Evidence-first property research**. The mark is an
abstract set of stacked layers, representing sources, releases and composed evidence. Avoid state
crests, government waratah marks, official blue palettes and language that implies affiliation.

## 3. Colour system

### Core palette

| Token family | Representative value | Role |
|---|---:|---|
| Ink 950 | `#10262e` | Top bar, highest-emphasis text |
| Ink 900 | `#17333d` | Primary body text |
| Ink 700 | `#385a63` | Secondary text |
| Ink 100 | `#edf2f1` | Neutral status background |
| Ocean 700 | `#086d70` | Primary action, observed/confirmed evidence |
| Ocean 500 | `#159495` | Accent, focus and decorative detail |
| Ocean 50 | `#eef8f7` | Confirmed/positive surface |
| Eucalypt 500 | `#66877b` | Secondary geographic/natural accent |
| Sand 700 | `#7d6847` | Planned/manual/contextual state |
| Sand 50 | `#f8f4ed` | Warm content and roadmap surface |
| Amber 700 | `#8a5a0a` | Partial/requires verification |
| Coral 700 | `#a84f3d` | Conflicting/review attention |
| Red 700 | `#9c3f45` | Destructive/failed only |
| Blue 700 | `#275f89` | Informational/system state |
| Canvas | `#f3f6f5` | Application background |
| Paper | `#ffffff` | Cards, forms and data surfaces |

### Semantic evidence colours

| State | Foreground | Background | Icon/label requirement |
|---|---|---|---|
| Confirmed / observed | Ocean 700 | Ocean 50 | Dot/check + text |
| Partial / verify | Amber 700 | Amber 100 | Triangle + reason |
| Conflicting | Coral 700 | Coral 100 | Split/alert + both sources |
| Unknown / unavailable | Ink 600 | Ink 100 | Neutral dot + explicit wording |
| Failure/destructive | Red 700 | Red 100 | Alert icon + recovery action |
| Information | Blue 700 | Blue 100 | Info icon + context |

Do not map every `status` string directly to a colour in each feature. Use a shared status mapping
function or server-rendered variant class so `partial`, `stale`, `review_required` and `unknown`
remain consistent.

## 4. Typography

The project does not require bundled web fonts. Use a high-quality system stack:

```css
--ps-font-sans: Inter, "Avenir Next", "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
--ps-font-display: "Avenir Next", "Segoe UI", var(--ps-font-sans);
--ps-font-mono: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
```

### Scale

| Style | Suggested size | Use |
|---|---:|---|
| Display | `clamp(2.55rem, 7vw, 5.5rem)` | Shared home hero only |
| Page title | `clamp(2rem, 4vw, 3.3rem)` | Primary route heading |
| Section title | `clamp(1.7rem, 3vw, 2.5rem)` | Major sections |
| Card title | `1.05–1.25rem` | Cards/panels |
| Body | `0.94–1rem` | Standard content |
| Secondary | `0.78–0.86rem` | Metadata, table secondary |
| Eyebrow | `0.72rem`, uppercase | Feature/release context |
| Monospace | `0.74–0.9rem` | IDs, hashes, versions, request IDs |

Use tighter letter spacing for large headings and avoid all-caps body labels. Long IDs should wrap or
truncate with an accessible full value.

## 5. Spacing, shape and elevation

### Spacing

Use a four-pixel base expressed as rem tokens:

```text
1 = 4px   2 = 8px   3 = 12px  4 = 16px
5 = 20px  6 = 24px  8 = 32px 10 = 40px
12 = 48px 16 = 64px
```

### Radius

| Token | Value | Use |
|---|---:|---|
| XS | 5px | code chips, compact tags |
| SM | 8px | small controls |
| MD | 12px | buttons, inputs, badges |
| LG | 18px | standard cards/panels |
| XL | 26px | hero/high-emphasis surfaces |
| Pill | 999px | badges only |

### Elevation

Use borders before shadows. Most panels use a subtle border plus `shadow-xs`; dropdown/dialog/hero
surfaces may use `shadow-md` or `shadow-lg`. Dense admin tables should not appear as floating cards
inside floating cards.

## 6. Layout primitives

### Container

```css
.ps-container {
  width: min(1240px, calc(100% - 2rem));
  margin-inline: auto;
}
```

The prototype allows a wider application content maximum for operational screens, but report and
shared-shell prose should remain readable.

### Shell

Desktop application screens use:

```text
Sticky top bar
Release/capability strip
├── Sticky feature rail (approximately 248px)
└── Route content (fluid, bounded maximum)
```

The rail becomes an overlay on mobile. The release strip must remain brief and should not consume a
large percentage of small-screen height.

### Grid rules

- Use CSS grid for page composition and flex for inline clusters.
- Prefer `minmax(0, 1fr)` to prevent overflow.
- At 860–980px, collapse three-column operational layouts.
- At 720px, use one-column task flow and convert table density to list/detail where necessary.
- Avoid fixed card heights unless comparing aligned evidence sections.

## 7. Core components

### 7.1 Button

Variants:

- **Primary** — one dominant action per panel/route;
- **Secondary** — standard navigation or safe action;
- **Quiet** — low-emphasis utility;
- **Danger** — destructive action only, normally behind confirmation;
- **Review** — may reuse primary/secondary colour but must say what is being approved.

Requirements:

- minimum visual height around 42px;
- action-first labels: “Publish candidate,” not “OK”;
- loading state retains width and sets `aria-busy`;
- disabled state includes an adjacent explanation when caused by capability/coverage;
- icons reinforce rather than replace text for important actions.

### 7.2 Badge

Badges encode one concise state. Examples:

```text
Accepted release · Confirmed
Coverage partial · Verify
User-supplied price · Information
MCP disabled in cloud · Planned/neutral
```

Never put a paragraph in a badge. Use a badge plus explanatory sentence or disclosure.

### 7.3 Card/panel

A panel has:

- optional eyebrow;
- concise title;
- description or metadata;
- content area; and
- action area aligned to the bottom only when useful.

Use flat sections for long tables and logs. Cards are for meaningful grouping, not for every row.

### 7.4 Form field

Each field needs:

- persistent label;
- optional hint before validation;
- input/select/textarea;
- inline error linked with `aria-describedby`; and
- source/user-supplied indicator where relevant.

Do not use placeholder text as the only label. JSON/configuration fields should have examples and
schema validation; they should not be the primary UI for ordinary users.

### 7.5 Data table

Required patterns:

- semantic `<table>` for tabular data;
- sticky header only when the scroll container is clearly bounded;
- sortable header announces direction;
- primary cell contains the row's readable identity and secondary ID/date;
- row click is never the only way to open detail;
- pagination and limits are explicit;
- empty state is a table-adjacent message, not a fake blank row; and
- mobile either preserves horizontal scroll with priority columns or renders a list alternative.

### 7.6 Evidence item

Canonical anatomy:

```text
[State badge] Observation label
Primary value
Source · effective date · release
Match/coverage method
[Open evidence] [Add verification task]
```

Evidence IDs and source links should survive into the dossier rather than being copied as detached
prose.

### 7.7 Agent phase timeline

Phases should use human-readable labels:

```text
Plan → Retrieve property identity → Retrieve market evidence → Observe gap → Adapt → Draft → Review
```

Each event may reveal technical tool/model/request identifiers, but the default label should explain
what happened. Durable events—not a purely animated simulation—drive progress.

### 7.8 Human review panel

The panel shows:

- proposed output or mutation;
- evidence/citation coverage;
- reviewer findings;
- unresolved items;
- exact effect of approval;
- approve / request changes / reject; and
- reviewer comment.

Approval cannot be the same control as generating the draft.

### 7.9 Map and chart frame

The frame owns title, legend, source/effective date, coverage, controls, accessible alternative and
empty/failure treatment. The map/chart implementation remains feature-owned.

### 7.10 Toast and inline feedback

Use toasts for brief successful actions. Errors, version conflicts and review consequences belong
inline near the affected content. A toast must not be the only evidence that a destructive or
important action occurred.

## 8. Page patterns

### Collection/list

```text
Page header + create action
Filter/search bar
Summary counts/status
Table or cards
Pagination
Empty/error state
```

### Detail

```text
Breadcrumb/context
Identity + status + actions
Summary facts
Tabs/sections
Evidence/provenance
Activity/history
Danger zone where appropriate
```

### Compare

```text
Selection and method controls
Comparable period/measure validation
Side-by-side summary
Chart/map + table alternative
Coverage and exclusions
Save/update comparison
AI explanation using current selection only
```

### Report/review

```text
Report identity and evidence-as-of date
Section completeness matrix
Source-linked sections
Reviewer findings
Unassessed criteria
Disposition controls
Print layout
```

### Operations/failure recovery

```text
Accepted state remains visible
Candidate/run identity and failure phase
Failed rules and artifacts
AI diagnosis plan
Review-gated recovery action
New run/release lineage
```

## 9. Iconography

Use simple line icons with a consistent stroke width. A compact local SVG symbol set avoids network
and package dependencies. Core concepts:

- layers — product/source layers;
- database — Feature 1;
- trend — Feature 2;
- map — Feature 3;
- shield/layers — Feature 4;
- briefcase/file — Feature 5;
- sparkles — AI action, never evidence truth;
- link/book — provenance/citation;
- activity — run status;
- user/check — human review.

Do not use a robot icon as the primary brand identity; AI is a capability, not the product promise.

## 10. Motion

Motion is restrained:

- 120–180ms hover/focus/expand transitions;
- progress updates tied to actual durable phase changes;
- no continuous pulsing except a small active-run indicator;
- no decorative parallax; and
- full `prefers-reduced-motion` support.

## 11. Print design

The dossier print view should:

- remove navigation and interactive controls;
- use black/dark ink on white;
- preserve source URLs in readable form or footnotes;
- avoid splitting evidence cards/tables unpredictably;
- show evidence-as-of date, report version and human disposition on each page/header where feasible;
- include methodology and limitations; and
- never rely on background colour alone for status.

## 12. CSS architecture and adoption

### Shared files

```text
shared/frontend/design-system/
  tokens.css       # values only
  base.css         # reset, type, focus, accessibility
  components.css   # product-neutral UI primitives
```

### Feature files

```text
student-N/frontend/
  styles.css       # imports/copies approved shared version
  feature.css      # feature composition only
```

Two viable distribution approaches:

1. **Versioned copied assets for Release 0.** Each independently built frontend copies a tagged
   design-system snapshot. This is simple and avoids runtime coupling.
2. **Shared static package through the edge.** Feature containers import `/assets/design-system/...`
   only after the shared edge is reliable and cloud paths are tested.

Do not let a shared UI package import domain data clients or Feature 1 status semantics.

### Versioning

Use a tiny changelog:

```text
Design system 0.1 — tokens, base, button/card/badge/form/table
0.2 — agent timeline, evidence item, review panel
0.3 — map/chart frame and print rules
```

Breaking token/component changes require screenshots for all five feature shells and the AI-mode
operations interface.

## 13. Design review checklist

Before merging a new screen:

- Is feature ownership clear?
- Is current versus planned capability honest?
- Does every key fact show source/freshness/coverage or user-supplied status?
- Are confirmed, partial, conflicting and unknown states distinct without colour alone?
- Does the primary task work without AI?
- Are loading, empty, partial and failure states designed?
- Is the route keyboard-complete and usable at 390px width?
- Does a map/chart have a table/text alternative?
- Is human review separate from generation?
- Does the screen use shared tokens rather than new one-off colours/spacing?

Storyboard reference: `../design-assets/storyboards/04-screen-system-and-design.jpg`.
