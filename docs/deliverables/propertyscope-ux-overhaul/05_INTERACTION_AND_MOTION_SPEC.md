# Interaction, motion and perceived performance

## Vocabulary in production

| Token | Value | Meaning |
|---|---|---|
| `--ps-motion-fast` | 100ms | Immediate hover/press or small state feedback |
| `--ps-motion-normal` | 160ms | Normal UI transition |
| `--ps-motion-slow` | 240ms | Larger entry/overlay transition when useful |
| `--ps-motion-progress` | 1200ms | Ambient pending/skeleton cycle, not completion percentage |
| `--ps-motion-distance` | 4px | Small positional continuity cue |
| `--ps-ease-standard` | `cubic-bezier(.2,.8,.2,1)` | Settling entry/response |
| `--ps-ease-exit` | `cubic-bezier(.4,0,1,1)` | Exit vocabulary |

Tokens define a vocabulary; they are not a claim that every component runs every animation. Native disclosure and dialog behavior is preferred where elaborate animation would interfere with semantics. Transform/opacity are preferred to repeated layout measurement. There is no fake route transition across independently deployed applications and no simulated streaming answer.

## Pattern decisions

**Route entry.** Shared entry and supported feature transitions use a short, small movement or opacity treatment. The task title and navigation remain recognizable. List-to-detail continuity comes primarily from preserving the selected record, title and back action, rather than animating a clone across unrelated DOM trees.

**Drawers and dialogs.** A menu change is a genuine expanded/collapsed state with a native button, background/scrim treatment where appropriate, Escape and restored focus. Native dialogs enforce modality. Focus is not delayed until a decorative transition completes. Closing a dialog must remain possible even when required inputs are empty.

**Disclosures.** Detailed sources and technical activity are progressively revealed through native `details`. The expanded state survives unchanged polling updates. Do not animate an unknown payload’s height on every refresh or silently collapse the user’s inspection point.

**Filters.** A changed selection produces real pending state and then new results. Newer requests supersede older ones; stale case evidence is cleared on selection changes. Layout stays stable where possible. Long-running filters do not display a fabricated percent-complete indicator.

**Loading.** A readable status is primary. Skeletons reserve likely text/row geometry and mark the relevant region busy; they do not replace the whole application shell. The slow browser scenario holds actual intercepted API responses and captures the pending screen before releasing them. Empty, failed and not-yet-loaded are different states.

**Toasts and results.** Short feedback confirms an actual response. Persistent validation or network failures stay next to the affected task. A request accepted by the service is not necessarily a completed run, and a completed run is not necessarily complete evidence.

**Assistant polling.** A presentation fingerprint avoids replacing unchanged turns. Updated disclosure, focus and scroll position are carried across necessary rendering. Public phases use recorded status and available events. Last-known state stays visible during a temporary poll failure. A response arriving after cancellation cannot reset the UI to an active state. Cancellation is displayed as final only when confirmed by the server.

**Charts, maps and counters.** Numeric values are not count-up animations. Chart geometry represents actual observations, including missing points. Maps use normal control/popover feedback; unavailable WebGL or coordinates get an explicit fallback. Count changes remain textual and do not move surrounding controls unnecessarily.

## Keyboard conventions

Enter submits a valid assistant question; Shift+Enter inserts a newline; IME composition never submits. A second Enter/click while submitting cannot create a duplicate turn. Cancel and close remain distinct from form submit. Escape closes supported menus/native dialogs and returns focus. Error handling directs focus to the first invalid field or visible error where appropriate, while polling avoids stealing focus from reading or typing.

## Reduced motion

`prefers-reduced-motion: reduce` disables meaningful animation cycles and smooth scrolling through the shared foundation. The interface remains usable without motion; pending state still has text and `aria-busy`. Reduced-motion checks sampled 28 final route/viewport cases and found no active long-duration animation. The focus probe waits for paint before measuring its outline: even a 0.01ms CSS transition has an initial computed frame, which must not be mistaken for a permanently missing focus ring.

## Performance boundary

No runtime dependency or large image was introduced. System fonts avoid a remote font request and late font swap. Stable polling markup reduces unnecessary DOM replacement; scoped abort/revision guards avoid obsolete work. The source-byte comparison is a footprint observation, not a Lighthouse score or an end-to-end latency benchmark. Real network, origin and GPU performance still require an unrestricted environment.
