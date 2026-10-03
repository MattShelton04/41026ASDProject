# GitHub Actions reliability review — 3 October 2026

## Evidence and scope

Reviewed all 294 workflow runs created from **2026-09-26 00:00 UTC** through the pre-change
snapshot on **2026-10-03**. The snapshot ends with the main quality run completing at 03:30 UTC.
Evidence came from the paginated GitHub Actions REST API, failed-job logs, visual job step
timestamps, retained galleries and current source. The one rerun's original attempt also failed
with the same visual instability. Counts below count workflow runs, not attempts or individual jobs.

Changes were made in the separate Codex worktree on `codex/actions-reliability`, based on
`7fc9b29742bad932849c7b237e178c9ad1562401`. No developer stack, database or accepted data was changed.
Raw API responses, logs and reproduction images remain in ignored `Temp/actions-audit/`.

| Workflow | Passed | Failed | Cancelled | Median successful elapsed | Maximum successful elapsed |
|---|---:|---:|---:|---:|---:|
| Integration CI | 44 | 0 | 0 | 302s | 329s |
| Student 1 CI | 23 | 2 | 1 | 196s | 278s |
| Student 2 CI | 33 | 0 | 0 | 81s | 104s |
| Student 3 CI | 34 | 1 | 0 | 49s | 59s |
| Student 4 CI | 34 | 0 | 0 | 96s | 118s |
| Student 5 CI | 31 | 0 | 0 | 109s | 128s |
| Visual Capture | 13 | 10 | 0 | — | — |
| Visual Report | 22 | 0 | 0 | — | — |
| Pages build and deployment | 23 | 0 | 23 | — | — |

Elapsed time uses `run_started_at` to `updated_at`; it includes post-job work. The single cancelled
Student 1 run was superseded, consistent with its deliberate cancellation policy. Cloud deployment
had no runs in this window, so its execution reliability cannot be assessed from this evidence.

## Screenshot failures

**Nine of the ten failed capture runs failed the same Feature 4 review-detail case.** They ended
with `the view did not render identically twice within 5 captures`. No other head case failed in
those runs. The surrounding page content and application responses were stable.

| Date (UTC) | Failed runs | Cause |
|---|---|---|
| September 30 | [36734488017](https://github.com/MattShelton04/41026ASDProject/actions/runs/36734488017), [36738990441](https://github.com/MattShelton04/41026ASDProject/actions/runs/36738990441) | Below-viewport WebGL capture |
| October 1 | [36816718003](https://github.com/MattShelton04/41026ASDProject/actions/runs/36816718003) | Read-only nested bind-mount creation |
| October 1 | [36824582830](https://github.com/MattShelton04/41026ASDProject/actions/runs/36824582830), [36866213565](https://github.com/MattShelton04/41026ASDProject/actions/runs/36866213565), [36866227567](https://github.com/MattShelton04/41026ASDProject/actions/runs/36866227567), [36876629095](https://github.com/MattShelton04/41026ASDProject/actions/runs/36876629095), [36876648811](https://github.com/MattShelton04/41026ASDProject/actions/runs/36876648811), [36905626518](https://github.com/MattShelton04/41026ASDProject/actions/runs/36905626518) | Below-viewport WebGL capture |
| October 3 | [37093164397](https://github.com/MattShelton04/41026ASDProject/actions/runs/37093164397) | Below-viewport WebGL capture |

### Full-page WebGL capture

An isolated reproduction served the actual Feature 4 frontend with deterministic API responses,
the real self-hosted MapLibre renderer and the production content-security policy. Consecutive
full-page screenshots alternated about 258,595 pixels exclusively inside the environmental map,
below the 1000px viewport. Its rounded, overflow-clipped wrapper triggers the compositor problem.
One frame retained the map background; the next blanked most of it.
This explains why an unchanged application sometimes passed a PR run and failed its merge run.

CSS animation suppression, the fixed clock and network-idle checks do not preserve an offscreen
WebGL drawing buffer. GPU flags, software rendering and `preserveDrawingBuffer` alone did not fix
the reproduction. The capture harness now preserves the WebGL drawing buffer and freezes its
rendered pixels into a same-sized image before the full-page screenshot. It also waits for map
loading indicators. Actual map pixels remain visible; no map mask, relaxed pixel threshold or
larger viewport is used. This is capture-only behavior, like the existing animation suppression.

The reproduction produced 15 identical consecutive frames after freezing the canvas. Browser
regression coverage uses the real vendored MapLibre renderer in a rounded, clipped container below
the viewport and validates its background and property marker pixels, delayed readiness, viewport
geometry and repeatability. The smaller canary does not reproduce the compositor fault on every
run; the full application before/after reproduction supplies that evidence.
Application behavior, seed data and feature ownership remain unchanged.

### Read-only nested mounts

Run 36816718003 never reached capture. Docker attempted to create
`/usr/share/nginx/html/ai-chat` below a read-only frontend-root bind mount and failed with
`mkdirat ...: read-only file system`. Development mounts made a CI job dependent on whether that
directory happened to exist in the checked-out feature frontend.

Visual CI now uses `stack up --offline --no-reload --build`: each revision is built into images,
and the development source mounts and reload workers are omitted. Local development keeps its
existing reload workflow. Workflow tests enforce this startup mode and its packaging/runtime
triggers.

## Reporting and publication

Visual Report intentionally publishes diagnostics after a capture failure. Its successful status
does not certify that captures succeeded. The latest failed run's gallery already showed the
Feature 4 case as incomplete, so it was not hiding that particular error.

However, the reporter skipped trusted cases when both revisions lacked that provider's manifest.
A stack startup failure could therefore omit whole feature sections. CI now declares both expected
providers and renders missing provider artifacts or omitted cases as explicit incomplete entries.
Local selected-case comparisons remain scoped. Job summaries show the source capture conclusion.

All 23 published Pages commits had a pair of deployment runs: one completed and one was cancelled.
The publisher previously requested a build unconditionally after pushing. It now checks for a
queued, building or completed build for that exact commit before requesting another. An explicit
API fallback remains after ten seconds because workflow-token pushes may not start Pages builds.
Historical logs establish duplicate deployment work; they do not establish GitHub's internal
trigger order. Hosted behavior of this change must be confirmed after the trusted publisher merges.

Late PR-origin reports also previously fell back to the main history when the PR closed or its
head moved. The source PR identity now remains attached to the retained gallery; sticky comments
are only updated for an open PR whose current head matches the captured SHA. Artifact extraction,
PNG validation, read-only capture permissions and the trusted default-branch publisher remain intact.

## Other actions and bottlenecks

| Observation | Evidence | Result |
|---|---|---|
| Stale Feature 1 navigation assertion | [36229788377](https://github.com/MattShelton04/41026ASDProject/actions/runs/36229788377), 1 failed / 67 passed | Already corrected by `e7485af` / PR #117; no duplicate fix |
| Feature 1 route callback outlived its browser context | [36407008967](https://github.com/MattShelton04/41026ASDProject/actions/runs/36407008967), 67 passed / 1 setup error | Already corrected by `6378d8b` / PR #124 with waiting route cleanup |
| Feature 3 BuildKit transport EOF | [36229788385](https://github.com/MattShelton04/41026ASDProject/actions/runs/36229788385), before Dockerfile execution | Dedicated pinned Buildx/Bake builder, explicit loaded images and builder diagnostics |
| Missed input triggers | Workflow path filters compared with actual workspace and Docker inputs | All five student workflows now cover workspace manifests; missing deployment, Docker and workflow-only push triggers repaired |
| Cache service can fail otherwise successful builds | Existing required Bake cache export | Student 1 and 3 cache I/O capped at two minutes; exports optional; image builds and smoke checks remain required |
| Chromium installation outliers | 409s, 362s and 311s visual install steps; Ubuntu package downloads consumed most of the delay | Install only the headless shell that capture uses, retain required OS dependencies |

The underlying reason for the historical BuildKit daemon disconnection is unknown: its logs
contained only the RPC EOF. The dedicated builder is a mitigation, and the added diagnostics make
a recurrence investigable. No unsupported OOM or Dockerfile diagnosis is claimed.

Recent five-success samples put the Integration quality command at 181–281s (median 233s),
Feature 1's required browser forms at 136–141s (median 138s), and the other features' image builds
at 9–30s. Those timings do not justify duplicating the canonical gate, increasing parallel browser
workers, weakening coverage or adding caches to every feature.

The long Chromium installations were mainly slow Ubuntu mirror transfers, not browser downloads.
Removing unused headed Chrome avoids one download but does not eliminate that external bottleneck.
[Playwright's CI guidance](https://playwright.dev/python/docs/ci#caching-browsers) explains that
browser caches generally cost about as much to restore as downloading, and Linux dependencies
still require installation. A future version-matched browser image could eliminate repeated apt
work, but needs a separate measured Linux capture baseline and stack-network validation.

The report workflow's concurrency setting also permits replacement of pending runs during rapid
pushes; no such report cancellation was observed in this week. Its comments now document this
platform limitation instead of promising that every queued report is retained.

## Validation

Completed locally: `uv run python scripts/check.py` (all stages and configured coverage thresholds),
pinned actionlint 1.7.12, 86 focused visual/workflow tests with the browser required, and two complete
29-view fixture captures with matching SHA-256 hashes for every view. The real Feature 4 page
reproduction produced 15 identical frames after the fix. The full gate includes 238 passing Node
tests. Expected platform and opt-in PostgreSQL integration skips remain reported by that gate.

Hosted PR checks are recorded in the pull request. Local script tests and
browser reproductions use deterministic responses; they do not establish a real-provider answer,
official data coverage or live database integration. Linux workflow smoke and capture jobs supply
the container validation. The trusted publisher changes execute from `main` after merge, so their
PR validation consists of deterministic regression tests and workflow lint.
