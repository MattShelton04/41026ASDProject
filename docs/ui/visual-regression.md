# Visual regression review

Status: living guide, introduced 2026-09-28. Source: `scripts/visual/`,
`.github/workflows/visual-capture.yml` and `.github/workflows/visual-report.yml`.

Every pull request that touches a frontend, a feature backend or seed, the deployment model or the
harness renders each PropertyScope research area in a real Chromium browser, **before and after the
change**. It then publishes a pixel comparison to GitHub Pages and posts one pull request comment
that is edited in place on every push. Merges to `main` are compared with the previous `main`
commit, so the Pages history also records how the product's appearance changed over time.

The comparison informs review; it doesn't approve anything. A human decides whether a change is
intended. Nothing in the system fails a pull request because pixels changed.

- Site: `https://<owner>.github.io/<repo>/visual/` (landing page at the site root)
- Local loop: `uv run scripts/dev.py ui visual` (see [Local use](#local-use))

## What is captured

| Section | Provider | Views | Data |
|---|---|---|---|
| Shared | fixture (+1 stack) | home, research areas, data status, sources history, assistant, roadmap, activity history, knowledge sources; empty and error states | `scripts/ui_fixtures.py` scenarios |
| Feature 1 · Property data | fixture | search, results, property, assistant, overview, jobs, runs, releases, sources, quality, artifacts, coverage and detail pages; empty, error, long-content and large-list states | fixture scenarios `populated`, `empty`, `error`, `long-content`, `large` |
| Feature 2 · Sales & market | stack | market cases with a selected case, new-case dialog | Feature 2 seed data |
| Feature 3 · Suburb context | stack | explore (map), trends, published, comparisons, assistant | Feature 3 seed data |
| Feature 4 · Site & planning | stack | site reviews, review detail, new-review dialog | Feature 4 seed data |
| Feature 5 · Buyer workspace | stack | buyer cases, case detail | Feature 5 seed data |

`uv run python -m scripts.visual cases` prints the live inventory from `scripts/visual/cases.py`.

**Why two providers?**

- The **fixture** provider reuses the deterministic fixture server (`scripts/ui_fixture_server.py`),
  which serves the real Shared and Feature 1 frontends against synthetic API responses. It needs no
  Docker, starts in about a second, and every scenario is reproducible.
- Features 2–5 have no fixture server, but each seeds fixed demonstration records into its own
  database on start. The **stack** provider starts the offline Compose stack
  (`uv run scripts/dev.py stack up --offline`, with no model key, MCP or RAG) and captures those
  pages through the shared edge on port 5100. It covers the real backends and nginx routing too.

## Architecture

```text
pull_request / push to main
        │
        ▼
Visual Capture (untrusted, contents: read)          4 jobs: {base, head} × {fixture, stack}
  1. check out the harness at github.sha (the PR merge commit)
  2. scripts/visual/refs.py → base = merge base, head = PR head (push: before → after)
  3. check out the base or head revision into app/
  4. uv sync both; install lockfile-pinned Chromium
  5. stack jobs: dev.py stack up --offline inside app/
  6. python -m scripts.visual capture --target ../app → PNG + capture-<provider>.json
  7. upload artifact visual-<revision>-<provider> (14 days)
        │ workflow_run: completed
        ▼
Visual Report (trusted, default branch only)
  1. validate the event (source workflow path, repository, conclusion, attempt)
  2. download the four artifacts; extract flat, bounded *.png / capture-*.json only
  3. find the open PR whose head is this exact commit (forks included)
  4. build_report: validate PNGs, diff pixels, write the gallery
  5. publish to gh-pages (rebase-and-retry, prune, squash long history)
  6. write the job summary; wait for Pages; create or update the sticky comment
```

The harness always comes from the workflow revision, so a base commit that predates a new case or
policy is still captured with today's rules. A view the base doesn't have yet is reported as
**base unavailable**, not as a failure.

### Trust boundary

Pull request code, including code from forks, runs only in *Visual Capture*, which has a read-only
token. *Visual Report* runs from the default branch through `workflow_run`. It never checks out,
installs or executes anything from the pull request, and it installs only the `visual` dependency
group (Pillow and NumPy, via `uv sync --only-group visual`). Artifacts are treated as hostile data:

- Archive member names must match `^[a-z][a-z0-9-]{0,63}\.png$` or `capture-(fixture|stack).json`.
  Symlinks, nested paths and anything else reject the whole artifact. `*.failed.png` diagnostics
  are skipped.
- Size limits: 16 MB per PNG, 400 KB per manifest, 400 MB per artifact, 160 views.
- A PNG must be 1440 px wide, 200–6000 px tall, 8-bit RGB/RGBA, non-interlaced, and contain only
  CRC-valid `IHDR`/`IDAT`/`IEND` chunks before Pillow decodes it.
- Manifest text is length-limited. The trusted case inventory supplies the order, sections and
  labels. The capture SHA must match the workflow run's head.
- Gallery pages carry a CSP with `default-src 'none'`, pin their one script and stylesheet by
  SHA-256, and embed data as JSON that cannot close its `<script>` element. Comment text is
  entity-escaped for both Markdown and HTML, and image URLs are built only from SHA-256 file names.
- The artifact download drops the API token before following the redirect to storage.
- The sticky comment is only ever edited when it was written by `github-actions[bot]` and carries
  the marker. A stamp (`<!-- run:<id>:<attempt> -->`) stops an older re-run from overwriting
  newer results.

## Determinism

A comparison is only useful if an unchanged page renders byte-identically. The harness controls
every source of variation it knows about (`scripts/visual/policy.py`, `capture.py`):

| Source | Control |
|---|---|
| Viewport and DPI | 1440 × 1000, device scale factor 1, full page clipped at 6000 px |
| Clock | Playwright clock fixed at `2026-09-01T10:00:00+10:00`; `Australia/Sydney`, `en-AU` |
| Randomness | seeded `Math.random`; `crypto.randomUUID` returns a counter-based v4 UUID |
| Animation | reduced motion, a same-origin stylesheet that disables animations, transitions, smooth scrolling and carets, and Playwright's `animations="disabled"` |
| Network | same-origin only; the Feature 3 map style is replaced by a blank style; everything else is aborted and listed in the view's notes |
| Rendering | Chromium flags `--disable-partial-raster --disable-skia-runtime-opts --force-color-profile=srgb --font-render-hinting=none`; light colour scheme; service workers blocked |
| Readiness | the case's ready selector → network idle → no visible `[aria-busy=true]` or `.ps-skeleton` → fonts loaded → two animation frames |
| Stability | screenshots are repeated until two consecutive captures are byte-identical (at most 5) |
| Measured values | per-case `mask` selectors paint genuinely measured values (only health-check latency today) in a flat colour |

The "still" stylesheet is served from the page's own origin through request interception, so the
stack's strict `style-src 'self'` CSP stays enforced. A CSP regression still shows up as a console
error instead of being bypassed.

Unexpected console errors, failed requests or a timed-out ready selector fail the view. The
screenshot is kept as `<id>.failed.png` in the capture artifact for diagnosis, and the gallery
lists the view as **incomplete** with its first errors.

## Reading a comparison

Classification (triage only):

| Status | Meaning |
|---|---|
| changed | any pixel differs by more than 8/255, more than 128 pixels differ, or the page height changed |
| subtle | at most 128 pixels differ and none by more than 8/255 (usually anti-aliasing) |
| unchanged | byte-identical pixels |
| base unavailable | the view is new, or the base revision could not render it |
| incomplete | the head view failed to capture or its PNG was rejected |

The gallery (one per run) lists views by section, with counts per section and a search box. Views
with the same changed areas are grouped ("same change as …"). Modes:

- **Side by side** and **Before / after** (press `T` to toggle)
- **Wipe**: drag the divider or use the arrow keys
- **Overlay**: adjustable opacity
- **Difference**: the after image dimmed with changed pixels highlighted, at thresholds of 0, 8, 16
  or 32 per channel. Numbered region boxes jump to 100% zoom on that region.

Zoom with fit-width or 100%, and drag to pan. The URL hash keeps the section, view, mode, zoom and
threshold, so a link opens the exact comparison. `changes.json` next to each gallery lists exact
metrics, changed areas and image URLs for scripts and agents.

The history page at `visual/` has three tabs:

- **Pull requests**: the latest run per PR with previews, and earlier pushes folded underneath
- **Main**: each merge compared with the previous main commit
- **View timeline**: one view across runs, showing only runs where its image actually changed

The site keeps the newest 30 main runs and the newest 30 pull request runs. Images are
content-addressed (`visual/img/<sha256>.png`) and shared between runs, and any image no retained
run references is deleted on publish. Once the `gh-pages` branch reaches 150 commits, the
publisher replaces its history with a single commit of the current tree, so the repository doesn't
grow without bound.

## The pull request comment

The comment includes:

- a verdict and links to the gallery and the history
- the compared commits, the attempt and the workflow run
- a table of changed, subtle, unchanged and limited views per section (Shared, Features 1–5)
- the first three changed views expanded, each with a viewport-tall preview of the changed areas
  and folded 1:1 before/after close-ups of the two largest areas
- the rest of the changed views, the subtle views and the limitations, each folded with deep links

It is bounded at 60,000 characters. If a report would exceed that, the comment falls back to the
table and a gallery link. The publisher waits for Pages to serve the new gallery before
commenting, so images aren't cached as broken.

## Local use

The local loop needs no GitHub, and the fixture provider needs no Docker:

```text
uv run scripts/dev.py ui visual                         # 1st run: save a baseline of the working tree
# ... make a frontend change ...
uv run scripts/dev.py ui visual                         # capture again and build the gallery
uv run scripts/dev.py ui visual --case f1-runs --case f1-overview   # narrow while iterating
uv run scripts/dev.py ui visual --section feature-1 --reset-baseline
uv run scripts/dev.py ui visual --provider stack        # Features 2-5; needs a running stack
```

Output goes to `.propertyscope-visual/local/<provider>/` (git-ignored). Open `report/index.html`.
The lower-level commands are `python -m scripts.visual capture|compare|cases`. Stack captures use
whichever stack owns port 5100 (or `PROPERTYSCOPE_SHARED_PORT`). The harness only reads from it.

## Adding or changing a case

1. Add a `VisualCase` to `CASES` in `scripts/visual/cases.py`. Use an `fN-` prefix for Feature N
   (a case's section is inferred from its prefix) and any other ID for Shared. IDs are permanent
   history keys, so don't rename them.
2. Choose `ready`: a selector that exists only once the view's data has rendered. Use `steps` for
   dialogs or interactions, and `expected_errors` for a deliberately failing fixture scenario.
3. Mask only values that are genuinely measured at runtime. Fix any other non-determinism at its
   source (fixture data, seeds, the clock or the random seed).
4. Run `uv run scripts/dev.py ui visual --case <id>` twice with a reset baseline in between. The
   second run must report the view as identical.
5. Run `uv run pytest scripts/tests/test_visual_*.py -q`.

A new case appears in pull request comparisons as **base unavailable** until the change merges.

## Setup and operations

GitHub Pages is served from the `gh-pages` branch root. Deploying from a branch is simpler than an
Actions deployment here: each publication is an ordinary commit, content-addressed images are
reused across runs, and there's no deployment artifact size or environment protection to manage.
One-time setup:

```text
git switch --orphan gh-pages
git commit --allow-empty -m "visual: initialise Pages branch"   # the publisher writes the pages
git push origin gh-pages
git switch -
gh api -X PUT repos/<owner>/<repo>/pages -f "source[branch]=gh-pages" -f "source[path]=/" \
  -f build_type=legacy                                          # or POST if Pages is not yet enabled
```

In the repository's Actions settings, workflows need read and write permission for the
`GITHUB_TOKEN`, as the report workflow's `permissions:` block requests. Free Actions minutes and
Pages hosting on this public repository cover it: a run uses four capture jobs (about 15–25
runner-minutes in total, mostly building stack images) and one short publish job.

**Bootstrap limitation.** GitHub runs `workflow_run` workflows only from the default branch. The
pull request that introduces this setup can capture and upload artifacts, but no gallery or comment
appears until *Visual Report* exists on `main`. Its first publication is the merge itself, or a
manual *Visual Capture* dispatch after merging.

Troubleshooting:

| Symptom | Where to look |
|---|---|
| A view is incomplete | the capture job log (per-view errors), then `<id>.failed.png` in the `visual-head-*` artifact |
| All stack views are incomplete | the capture job's "Stack logs on failure" step |
| No comment on a PR | the Visual Report run summary; comments skip PRs whose head moved on (a newer run will comment) |
| Gallery 404 right after publishing | Pages deploys a minute or two after the push; the run's `visual-gallery-<id>` artifact holds a standalone copy |
| An unchanged view shows differences | the pixel regions in the gallery's Difference mode; fix the non-determinism at its source, not with a mask |

## Limitations

- Captures use one width (1440 px) and the light theme. Responsive and dark-mode regressions need
  more cases.
- Pages over 6000 px tall are clipped, and the view's notes say so.
- The Feature 3 map renders without tiles, so the markers, controls and scale are compared but the
  basemap isn't.
- Stack views depend on each feature's seed data. Changing a seed is a visual change by design.
- Base captures are re-rendered on every run instead of reusing stored main captures. That's
  simpler and immune to browser drift, at the cost of runner minutes.
