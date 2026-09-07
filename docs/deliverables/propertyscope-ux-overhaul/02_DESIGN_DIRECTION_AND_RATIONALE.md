# Design direction and rationale

## Two directions considered

**Fieldbook / Survey Atlas** treats the application as a working record of a property investigation. Open framing corners and an irregular parcel form a compact mark. Warm neutral surfaces carry dark evergreen text. Editorial typography is confined to the entry experience; forms, charts and operations use a familiar system sans. Ruled sections and deliberately quiet surfaces make source dates and uncertainty part of the reading flow.

**Signal Console** would emphasize telemetry: darker technical surfaces, cooler cyan accents, stronger numeric hierarchy, command-center navigation and denser persistent side panels. It would give run histories and platform health a recognizable expert identity, but risk turning ordinary research into an operations dashboard. It would also make the mixed map/chart/form product harder to reconcile, require more inverse-surface contrast work and consume scarce mobile space.

| Criterion | Fieldbook | Signal Console |
|---|---|---|
| Property research | Calm, document-like; suited to reading caveats and comparing sources | Strong monitoring metaphor, weaker exploratory tone |
| Data operations | Compact expression of the same language retains density | Excellent raw telemetry density |
| Evidence and uncertainty | Neutral base leaves semantics available for real states | High contrast decoration could compete with warnings |
| Mobile and accessibility | Light readable surfaces, native controls and fewer persistent regions | More adaptation and inverse-color exceptions |
| Implementation | Evolves current shared tokens and independent ownership | More theme-specific components and exceptions |
| Distinctiveness | Parcel scope, editorial entry, evidence-first hierarchy | Familiar developer-console aesthetic |

Fieldbook was selected because the product’s distinctive value is not simply displaying data or operating jobs. It is helping someone connect a property question to attributable, limited evidence while still letting an expert inspect how that evidence was prepared. The operations experience should be the detailed counterpart of research, not an unrelated dark product.

## Decisions embodied in source

**Evergreen instead of arbitrary novelty.** The old palette already had a restrained natural association. It was evaluated rather than preserved by default. The chosen palette is darker, warmer and less aquatic; public `--ps-ocean-*` names remain compatible aliases to avoid a meaningless token-API migration. Warning, conflict, missing and failure states use separate semantics. Color never alone proves acceptance or completeness.

**Parcel framing instead of a roof and pin.** A scope is a bounded view. The open corners suggest focusing on a defined piece of evidence; the stepped interior suggests parcel geometry without falsely drawing an actual NSW cadastral boundary. The mark works in a square and in one color. “NSW” is geographic product context, not a government crest or endorsement.

**One task heading, not a marketing hero everywhere.** Home can establish the research attitude. A run detail needs its title, current state, timestamps, next actions and evidence. A case needs the selected property, current question and relevant actions. The editorial serif stops at the entry experience so it does not reduce scan speed in operational tables.

**Information layers instead of nested cards.** Page/task, supporting evidence, technical detail and complete activity form four layers. Cards are retained for genuinely separate records and selectable cases; other sections use spacing, headings and a rule. This preserves hierarchy without an endless stack of containers. Technical identifiers remain available where useful, but are not primary labels when a human-readable address or title exists.

**Responsive composition instead of hiding evidence.** The product header and contextual feature navigation collapse independently. Research filters move ahead of the map; dense tables scroll inside a named region; case metrics recompose; dialogs stay native and bounded; assistant controls are laid out for a narrow viewport. The mobile activity view keeps a real visible heading and a path back to the run list.

**Motion as continuity.** Fast press/focus feedback, short entry transitions, stable skeleton geometry and unchanged DOM for identical polls give a sense of response without simulating work. Large numbers and chart values are not animated by default: apparent precision and fake progress would be especially inappropriate in this product.

## Tradeoffs and non-goals

A single universal assistant drawer was rejected. The existing scopes and feature adapters are meaningful safety boundaries. A full-page reading workspace plus explicit contextual entry is more truthful than a floating bubble promising access to everything. A side panel could later be justified for a particular research task, but was not faked through cross-feature state.

No framework migration, remote typeface, icon library, stock photography or decorative map was necessary. This keeps startup and offline behavior close to the baseline. The system allows dense expert tables while using comfortable controls for research and touch. The result is coherent, not identical: domain-specific forms and source semantics stay in their owning features.
