# PropertyScope NSW — Fieldbook
## Implemented UI/UX overhaul · 7 September 2026

PropertyScope now has one evidence-led visual language across the shared application, all five enabled research areas and the expert AI activity viewer. **Fieldbook** pairs a warm mineral canvas with evergreen ink, restrained parcel-framing geometry and explicit evidence states. Research pages lead with the property, question or case; operations pages retain compact controls, tables, run phases and audit detail. This is an implemented source change, not a prototype or a proposed framework migration.

### What changed

The supplied application had substantial working architecture, deterministic contracts and independently deployable frontends. Its presentation was less coherent: different navigation conventions, heavy panels, inconsistent control sizes, stale “planned feature” messaging, raw technical detail competing with the task and variable handling of polling, errors and mobile layouts. Historical design documents did not always describe the enabled product.

The redesign keeps that architecture and changes its expression. A shared mark, palette, typography, geometry, control language and mobile navigation connect the workspaces. Evidence takes precedence over decoration: observed dates, coverage, missing data, candidate releases and review requirements remain visible. Charts distinguish missing values from recorded zero. Maps expose their unavailable state rather than substituting invented geography.

The assistant receives a substantive interaction redesign: explicit scope and context, bounded memory-only drafts, an autosizing composer, composition-safe keyboard handling, duplicate-turn prevention, stable polling updates, answer/evidence disclosure and durable activity links. Failed submission restores an otherwise empty composer. “Prepare question again” deliberately requires another human submission, rather than silently repeating a failed or invalid request. Review-required is a pause, not success. The capability guide no longer tells the model that four enabled research areas are merely planned; it distinguishes an available product area from tools connected to this particular assistant.

### Concrete changes beyond styling

Mobile pagination no longer inherits negative dialog gutters, and unbroken long table text wraps at narrow widths. Optional History API denial cannot stop a property search before its request. A cancelled run cannot be resurrected by an older poll response. Optional browser-storage denial no longer crashes the activity viewer. Source dates are not replaced by arbitrary fallback dates. Changing a market case clears stale evidence. Closing the suburb comparison dialog no longer triggers required-field validation. A buyer summary’s local workflow ID is no longer presented as a global agent-run ID. Actual generate-and-save behavior is named accurately in site reviews.

### Preserved deliberately

Service ownership, public API boundaries, deployment generation, tool allowlists, database ownership, candidate/accepted release semantics and human approval gates remain intact. The stack stays CSS-first and modular JavaScript, with native controls and existing HTMX islands. No runtime dependency or external asset service was added. The shared directory contains domain-neutral primitives, not a cross-feature data layer.

### Evidence and the completion boundary

The supplied ZIP is untouched. Changes were made in a separate Git-tracked copy from a clean baseline commit. The final source passes the available Node suites, isolated fixture/domain tests and executable architecture/style/generation checks. Real Chromium exercised production markup and JavaScript through an explicitly restricted, injected-document profile. The matrix and interaction evidence are retained, including failures and limitations—not just selected attractive screenshots.

**This environment did not permit a full production-like validation.** Python 3.12 could not be installed, Docker is absent and loopback browser navigation is blocked. The canonical quality gate, real-origin HTMX source forms, CSP/authentication behavior, GPU map rendering and a live model turn therefore remain unverified. Injected rendering is not a substitute for those checks, and this report is not a WCAG certification. See [validation](10_VALIDATION_REPORT.md) before treating the bundle as release-ready.

The product’s visual impact comes from continuity, better hierarchy, trustworthy status, responsive composition and considered small interactions—not from a new hero graphic or decorative animation. Start with the [visual comparison index](SCREENSHOT_GALLERY.html), then read the [design system](03_DESIGN_SYSTEM.md), [assistant experience](06_AI_ASSISTANT_EXPERIENCE.md) and [known limitations](11_KNOWN_LIMITATIONS_AND_FOLLOWUPS.md).
