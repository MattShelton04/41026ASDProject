# Shared and Feature 1 browser UI audit

## Scope

The audit drives the production Shared and Feature 1 HTML, CSS and JavaScript through Playwright
for Python. It uses the loopback-only fixture host documented in
`docs/ui/feature-1-fixture-mode.md`; it does not import test helpers into either frontend, start
Docker, open a database or use the internet. Requests to the configured OpenFreeMap host are
blocked so the checked-in neutral map fallback remains deterministic.

The executable cases in `docs/ui/feature-1-audit-cases.json` account for every state in
`docs/ui/feature-1-audit-config.json`. Each route state names its fixture scenario, optional
request override, setup flow and readiness selector. A configured state is never inferred from a
blind route-by-scenario Cartesian product. Three states are explicitly deferred because the
rendered product cannot truthfully expose them: long dynamic content on the two static Shared
catalogue routes, and a partial run-detail state whose current `Promise.all` composition becomes a
full error.

## Commands

Install the browser once after the locked dependency sync:

```text
uv run playwright install chromium
```

The root quick command covers Shared Home, a populated Property Discovery search and the Data
Operations overview at 1440x1000 and 390x844:

```text
uv run scripts/dev.py ui-audit-quick
```

The complete command covers every executable route case at all four configured viewports:

```text
uv run scripts/dev.py ui-audit-full
```

The package CLI exposes stable selectors and shards:

```text
uv run python -m scripts.ui_audit full --route-group property-discovery --viewport laptop-compact
uv run python -m scripts.ui_audit full --shard-index 0 --shard-total 4
uv run python -m scripts.ui_audit full --resume .propertyscope-runtime/ui-audit/20260823T120000Z
```

Use a non-canonical fixture port with `--port`; the audit owns and cleans up a fixture child only
when the selected loopback port is free. `--resume` reuses a batch only when its configuration,
source-tree and harness fingerprint still match. A corrupt or interrupted `.tmp` file is ignored,
while every completed batch and screenshot remains available.

## Artifacts and coverage

Generated output is Git-ignored under `.propertyscope-runtime/ui-audit/<timestamp>/`:

- `audit.json` is the machine-readable source of truth and conforms to
  `scripts/ui_audit/audit-report.schema.json`;
- `batches/*.json` are atomic route/case/viewport checkpoints used for resume and shard merging;
- `screenshots/<batch>/baseline.png` and post-interaction images retain rendered evidence;
- `index.html` is a compact batch/finding table; and
- `TRIAGE.md` records coverage, timings, deferred states, skipped destructive controls and issue
  counts.

The stable batch key is `workspace/route-group/route/case/viewport`. Shards use the SHA-256 of that
key modulo the shard total, so membership does not move when another case is added. Separate shard
artifact trees can be retained independently; visual CI integration and reviewed baselines are
owned by the later visual-CI prompt.

## Release policy

The 1440x1000 and 1024x768 laptop viewports are full hard gates. Unexpected exceptions, console or
request failures, page overflow, visible clipping, inaccessible controls, duplicate IDs, replay
failures, keyboard traps, focus loss, dialog overflow and unexplained scroll/layout movement fail a
batch.

The 768x1024 and 390x844 captures are required bounded-resilience evidence. They fail for page-level
overflow, a clipped or inaccessible primary/core navigation/search action, an unusable dialog, a
blocked core task or a keyboard trap. Dense-table contained scrolling and non-core responsive
parity remain advisory. Targets below 44x44 CSS pixels are warnings unless the target is a core or
primary control.

Closed off-canvas navigation, hidden/inert/ARIA-hidden trees and fully non-painted elements are
excluded from viewport measurements. A descendant wider than an in-viewport `overflow:auto` or
`overflow:scroll` ancestor is classified as contained scrolling, not document overflow. Clipping
checks intersect rendered content with every clipping ancestor.

## Interaction and destructive-action safety

Each visible non-disabled control receives a stable semantic identity and is replayed from a fresh
browser context. Controls that reveal menus, dialogs, drawers or disclosures add their newly visible
descendants with a reproducible setup path. The report records before/after URL, focus, ARIA state,
open overlays, visible alert/status text, scroll, console output, page exceptions and failed
requests.

Destructive triggers are exercised only far enough to prove the confirmation UI opens. The final
confirmation is inventoried and skipped by default. `--allow-destructive` is accepted only while
the audit owns or reuses the stateless loopback fixture host; it is never an authorization to
target a production-like or arbitrary origin.

## Deterministic canaries

The fixture namespace exposes clean, deliberate-overflow and deliberate-console-error pages only
under `/__ui-fixture__/canary/`. Browser tests prove the clean page passes and that either injected
failure produces its stable finding code and a failed laptop batch. The canaries do not enter the
product navigation or production images.
