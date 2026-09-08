# Fieldbook shared UI implementation

## Approved direction

On 8 September 2026 the user selected the temporary Fieldbook prototypes for implementation,
with persistent side navigation like the existing application. The reference is the seven-page
Fieldbook set in `propertyscope-design-lab-20260908/fieldbook/`. The implementation keeps the
current application contracts and real data; illustrative diagrams communicate feature purposes
and must never masquerade as retrieved evidence.

## Delivery sequence

1. **Shell and home.** Adopt the reference's editorial hierarchy, warm paper/evergreen palette,
   parcel illustration and five-scene research tour. Retain a responsive persistent sidebar,
   registry-driven feature links, working address search and the same-origin HTMX directory.
   Make scroll effects disposable on route changes, keyboard accessible and reduced-motion aware.
2. **Shared working views.** Give research areas distinct representative diagrams; compact service
   availability with expandable technical detail; emphasise accepted publication references;
   retain the assistant's real conversation, evidence and limited scope; express the three
   roadmap states clearly. Preserve loading, empty, partial and error states and cancellation.
3. **Activity.** Align the separately served agent activity shell and typography with Fieldbook
   while retaining filtering, source inspection, polling, cancellation and review controls.
4. **Verification.** Run focused deterministic/browser checks and the canonical quality gate.
   Start the complete local Docker workflow and compare each shared surface with the approved
   reference. Record desktop/mobile screenshots, intentional differences and runtime limits.

Each implementation stage will be committed separately on the user's current branch.

## Constraints and intentional differences

- Persistent side navigation replaces the prototype's horizontal primary navigation.
- Real runtime state replaces prototype demo counts, service times and scripted AI answers.
- Empty evidence and unavailable services stay honest; no sample data is inserted into production.
- Existing shared tokens and browser/assistant public boundaries remain intact.
- No dependencies, persistence, service contracts, student ownership or deployment architecture change.
- Feature-specific functionality remains in its owning feature. A separately delegated Feature 1
  prototype set is an exploration in a temporary directory, not a production feature rewrite.

## Verification targets

- Manifest navigation and HTMX fragment parity, functional address forwarding, and hash-route lifecycle.
- Scene selection, cleanup, reduced-motion handling and keyboard activation without scroll hijacking.
- Source/health projection failure isolation and existing request cancellation semantics.
- Assistant submission, progress, citations and activity links; activity list/detail controls.
- Narrow viewport layout, focus visibility, meaningful headings and colour-independent states.
- `uv run python scripts/check.py`; focused Shared browser audit; real-origin Docker inspection.

Completion evidence and any remaining limitations will be recorded alongside this plan.
