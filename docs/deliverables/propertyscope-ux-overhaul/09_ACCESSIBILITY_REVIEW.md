# Accessibility and interaction review

## Scope and evidence standard

The design targets WCAG 2.2 AA behavior. This is **not a conformance certification**. Real Chromium rendered production markup with deterministic browser fixtures under an opaque-origin injected-document profile. Automated probes and scripted keyboard actions are useful evidence, but do not replace assistive-technology testing, real mobile devices, actual origin behavior or a complete criterion-by-criterion audit.

The supplemental audit covers 14 representative routes at 360 and 1440px (28 cases), including shared and feature assistants, property search/detail, operations lists/detail, AI activity, market cases, suburb exploration/trends/comparisons, site review and buyer detail. It records headings, landmarks, names, labels, duplicate IDs, target geometry, computed text contrast and reduced motion. The raw report is retained under `validation/`.

## Findings fixed

Navigation now uses explicit native controls with accessible expanded state and focus restoration. Native dialogs retain their actual platform modality. Suburb comparison Cancel/Close bypasses field validation. Long text, data tables and map controls use contained/wrapping layouts rather than offscreen essential content. Status colors have textual labels; unavailable evidence is not encoded as zero.

The activity viewer’s title was hidden on mobile; it is now visible. Optional storage denial previously crashed the viewer in the restricted browser context; defensive cursor storage keeps the reading experience usable. Assistant polling no longer replaces identical message DOM, loses expanded evidence or revives a cancelled turn. Rejected submissions preserve the original question without overwriting a new draft. Market selection changes cannot leave the prior case’s evidence attached to a new title.

## Measured outcomes

The final sampled audit found zero unnamed controls, zero unnamed fields, zero duplicate IDs and one visible H1 per tested screen. Every sampled skip link had a target. Computed visible text checks found no failure among the measured samples; the final count is 2,132 measured text samples. All 28 sampled focus probes resolved to a visible 3px outline after paint. Reduced-motion mode showed no active long-duration animation.

The contrast algorithm deliberately excludes image/gradient backgrounds, transparent ancestor-opacity effects it cannot reliably model, SVG/canvas rendering, disabled controls and hidden content. It does not establish border/icon contrast or certify every state. It samples text against computed/composited solid surfaces. These exclusions matter; do not turn “zero measured failures” into “every pixel passes.”

## Keyboard and dialog behavior

The scripted workflow pass exercised opening mobile navigation, Escape, returning focus, native modal creation/editing, required-field recovery, assistant Enter/Shift+Enter/IME behavior and activity navigation. A native market-case dialog was tested through twelve forward Tab and twelve reverse Tab moves without focus escaping; Escape closed it and restored the opener. Comparison Cancel worked with empty required fields. Busy actions were checked against duplicate submission.

Skip links, page landmarks and task headings are present in the sampled surfaces. Polling does not intentionally take focus. Form error focus moves to the relevant field/alert, while asynchronous status announcements remain concise. The audit does not claim a complete manual screen-reader reading-order review of every dynamic state.

## Target size and focus interpretation

Comfortable controls are 44px; expert desktop controls may be 38px with spacing. A conservative 44px geometry probe reports small native checkbox boxes and some inline/brand links; a checkbox’s associated label can provide a larger activation area. A raw input-box dimension is not by itself proof of a WCAG target-size failure or pass. Dense desktop and inline text exceptions must be evaluated in their actual layout. The 360px and additional 320px smoke evidence are retained rather than assuming desktop rules are sufficient.

The first focus probe measured immediately after Tab and sometimes saw the initial frame of a 0.01ms reduced-motion transition. A follow-up probe observed 3px after paint. The test was corrected to wait for two animation frames, not to suppress a missing-focus failure. The final report records both `:focus-visible` and the computed outline width.

## Standards consulted and remaining checks

Reference criteria and patterns: [WCAG 2.2](https://www.w3.org/TR/WCAG22/), [modal dialog pattern](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/), and [native dialog technique H102](https://www.w3.org/WAI/WCAG22/Techniques/html/H102).

Outstanding release validation includes manual screen-reader use, zoom/reflow beyond the scripted widths, forced colors, non-text contrast, actual iOS/Android keyboard interaction, Safari/Firefox, real-origin HTMX focus after swaps and GPU-backed maps. There was no claim that unavailable tools or environment constraints made these checks pass. See the limitations document for the precise release boundary.
