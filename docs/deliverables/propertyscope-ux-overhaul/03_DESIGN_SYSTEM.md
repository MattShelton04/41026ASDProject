# Implemented design system

## Source and adoption

Production foundations live in `shared/frontend/design-system/{tokens,base,components,shell}.css`. The gallery is `shared/frontend/design-system/gallery.html`. Features import shared CSS and consume public browser/assistant/mapping barrels; domain-specific rendering stays local. [TOKEN_REFERENCE.md](TOKEN_REFERENCE.md) is generated from the final `tokens.css`, not manually reconstructed.

Import tokens, base and components before feature CSS. Use semantic public tokens instead of redeclaring `--ps-*` locally. Private feature layout variables are allowed. A shared component must not import a feature API or entity type. Existing stable CSS/DOM selectors are retained where possible; tests accompany behavior changes.

## Foundations

| Foundation | Implemented values and use |
|---|---|
| Canvas and ink | Canvas `#f5f4ee`, paper `#ffffff`, warm paper `#fffef9`; strong ink `#192d27`, body `#263b33`, muted `#4c6056` |
| Brand | Evergreen accent `#285442`, hover/focus `#1b4032`, subdued field `#f0f5ee` |
| Semantic states | Confirmed evergreen; partial `#8a5a0a` on `#fbefd7`; conflicting coral; failure `#9c3f45` on `#f8e2e4`; informational blue; unknown neutral |
| Font | System sans for tasks, native/system monospace for technical content; Georgia/Times serif for the editorial home heading only |
| Type | 12px caption, 14px label, 16px body, 1.12rem large; fluid title 1.875–2.75rem and display 2.5–4rem |
| Spacing | 4, 8, 12, 16, 20, 24, 32, 40, 48, 64px; responsive gutter 16–32px |
| Width | General content 1240px, wide 1460px, readable 760px; contextual rail 216px |
| Controls | Comfortable 44px, compact 38px, large 56px; content may increase height rather than clip |
| Shape | 4/6/8/12/16px radii; pill token retained for compatible semantic uses, not a default for every component |
| Elevation | Thin rules for normal sections; small shadows for controls/panels; stronger elevation for overlays only |
| Icons/brand | 16/20/24px icons; 36px standard header mark |
| Focus | 3px evergreen outline, 2px offset; inverse token available |
| Layers | Shell 20, sticky 30, dropdown 40, popover 50, drawer 60, dialog 70, toast 80, skip link 1000 |

Palette tokens are raw material, not a promise that every possible foreground/background combination passes contrast. Use documented semantic pairs; validate actual composition, especially overlays, charts and disabled states.

## Research and operations density

Use `.ps-density--comfortable` for discovery, case research and the assistant. Use `.ps-density--compact` when rows, status controls and technical inspection are the task. Mobile controls return to useful touch geometry. Compact does not mean smaller body text or suppressed evidence. A 38px desktop control remains separate from its neighbors; comfortable controls are 44px and labels may enlarge checkbox hit regions.

```html
<section class="ps-density--comfortable" aria-labelledby="evidence-heading">
  <h2 id="evidence-heading">Source coverage</h2>
  <p>Coverage is incomplete. Check the observation date before relying on this result.</p>
  <details>
    <summary>Source and methodology</summary>
    <p>Render the actual source, effective date and limitations returned by the service.</p>
  </details>
</section>
```

## Component and pattern contract

| Pattern | Implementation rule |
|---|---|
| Global/context navigation | Brand returns to product home; available-area links come from the enabled registry; contextual rail names the current feature. A button controls a narrow-screen drawer with expanded state, Escape and focus restoration. |
| Page header | Eyebrow is optional; one visible primary heading; short purpose/limitation text; primary action next to the task, not hidden in a generic menu. |
| Buttons and links | Native semantics; links navigate, buttons act. Primary evergreen, quiet secondary and explicit danger. Disable the initiating mutation control while pending; do not hide its label. |
| Inputs and filters | Visible label, useful placeholder only as an example, description/error association, native select by default. Search has a distinct submit action where the API requires it. |
| Cards and metrics | Group independent records; use rules for related subsections. Distinguish unavailable from zero. Let long addresses wrap. Do not claim “live” without a live source. |
| Tables | Semantic table headings, named contained horizontal scroll where needed, readable columns and a discoverable scroll hint. Never hide essential columns simply to fit mobile. |
| Status badges | Text plus color, separate evidence state from run state and service health. “Partial”, “Unknown” and “Failed” are not interchangeable. |
| Source/evidence row | Human label first, actual observed/effective date where available, source link only for a safe URL, limitation near the claim; technical identifiers in disclosure. |
| Tabs/section links | Use existing native navigation/route semantics. Buyer section buttons scroll without corrupting the router hash. Avoid pretending a link set is a keyboard-managed ARIA tablist. |
| Dialogs | Native `dialog`, bounded to viewport and 720px shared maximum where appropriate, meaningful title, close/cancel path, first-error focus and restoration. No parallel custom focus trap over the browser’s native modal behavior. |
| Disclosure | Native `details`/`summary`, sufficiently large activation area; preserve expanded state across polling updates. |
| Toast/banner | Replacing transient notification with status semantics; persistent errors remain visible near the failing task. Color is not the only differentiator. |
| Pagination | Own contained layout, not borrowed dialog action gutters. Results count and page actions remain reachable at 360px. |
| Loading | Real pending work with readable status and `aria-busy`; stable skeleton geometry; no percent-complete guess. |
| Empty/error/partial | Say what is missing, preserve input/context and offer a real recovery action. Partial evidence may coexist with a successful request. |
| Charts | True data proportions, legible labels, differentiated series and missing-value gaps; scroll chart region when necessary rather than compress all labels. |
| Maps | Local controls/legend, accessible alternatives and an explicit unavailable fallback. Do not draw a coordinate or parcel not supplied by a source. |
| Activity/timeline | Recorded states, timestamps and available tool/evidence summaries; detailed payloads are progressively disclosed. |
| Assistant | Scope/context → conversation → answer/evidence → durable activity. See the dedicated experience specification. |

## Responsive rules

The breakpoints are local CSS composition rules, not a new JavaScript device classifier. Shared navigation transforms at 960px; independently owned feature shells at 1100px; the denser activity header uses 1360px and its single-column mobile treatment uses 720px. Additional feature grids adapt according to content. The measured matrix covers 360, 390, 430, 768, 1024, 1440 and 1728px; the existing feature smoke additionally covers 320px.

Header and availability-strip offsets are measured where needed instead of assuming one line of header text. Dialogs fit the viewport. Maps, lists and evidence can stack, but evidence is not dropped. Dense tables and the suburb trend plot have contained scrolling. The assistant composer uses safe-area padding and becomes normal-flow on mobile rather than relying on an untested virtual-keyboard overlay.

## Data visualization and truth

Use the primary evergreen, secondary blue and tertiary sand tokens for comparable series, not for semantic failure states. The second crime series also uses a dash pattern. Chart missing observations remain null/gaps or an explicit missing label; recorded zero remains zero. A successful HTTP response, accepted release, complete evidence, healthy service and enabled feature are five different claims. A UI must never infer one from another.

## Maintaining the system

Add a shared token only for a reusable concept, and update this reference/gallery with it. Keep domain logic in features. Avoid deep imports beside the shared public barrels. The raw-style exception baseline was reduced rather than widened; existing exceptions still need careful migration, not automatic deletion. The source footprint increased modestly for actual interaction resilience and QA, not a runtime UI library. See the changelog and validation report for measured scope.
