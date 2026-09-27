---
name: feature-1-data
description: Find out what PropertyScope Feature 1 data is really loaded, collect official NSW sources (G-NAF addresses, PSI sales, schools, SEIFA, BOCSAR crime, reference layers), take candidates through human review and publication, and query the accepted property data over HTTP. Use when a task needs real data rather than the seeded demo baseline, when checking data updates end to end, or when preparing an isolated data environment.
---

# Feature 1 data: check, collect, publish, query

Feature 1 (`student-1/`, the Data Platform) owns every official dataset the application uses. It
acquires registered sources, builds immutable releases, and serves accepted data over HTTP. Other
features and AI-mode never open its PostgreSQL database; neither should you. Use the public API
at `http://127.0.0.1:5200/api/data-platform/v1` (the port follows `PROPERTYSCOPE_PORT`).

## 1. See what is really loaded

```text
uv run scripts/dev.py stack status             # is the stack up, and which Compose project?
uv run python .github/skills/feature-1-data/data_status.py
```

`data_status.py` is read-only. It prints each registered dataset, its accepted record count, and
releases waiting for review. **A fresh database already reports accepted `gnaf-nsw`,
`nsw-psi-sales`, `bocsar-crime`, `nsw-government-schools` and `fixture-property` releases:** these
are a seeded demonstration baseline of about 10 records each (IDs starting `60000000-0000-...`,
addresses such as `FIXTURE STREET`). The script labels them `SEEDED DEMO ONLY`. Never report
those as real data.

`uv run scripts/dev.py operator report` gives the broader read-only publication and health view.

## 2. Pick the job

`uv run scripts/dev.py data collect <job>` always requests the complete registered source. Jobs
are the files in `student-1/config/job-profiles/`; the dataset they produce is in brackets.

| Job | Produces | Size and time (measured locally) | Needs |
|---|---|---|---|
| `fixture-property` | `fixture-property` | 10 synthetic rows, seconds | nothing |
| `schools-master` | `nsw-government-schools` | ≈2,200 schools, seconds | internet |
| `abs-seifa-2021` | `abs-seifa-2021` | ≈4,500 NSW suburbs, under a minute | internet |
| `abs-cpi` | `abs-cpi` | small, about a minute | internet |
| `gnaf-nsw` | `gnaf-nsw` (address register) | 5.2 M addresses; about 10 min from cache plus publish | 1.6 GB archive (cache or download) |
| `psi-sales` | `nsw-psi-sales` | 7.4 M sales; 35-55 min plus publish | PSI archives (`data sync-psi`); accepted G-NAF for address matching |
| `bocsar-crime` | `bocsar-crime` | 10 M observations; about 20 min | internet |
| `nsw-cadastre`, `nsw-planning-controls`, `nsw-bushfire-prone-land`, `nsw-flood-planning`, `abs-geography-2021`, `nsw-suburb-boundaries`, `nsw-school-catchments`, `nsw-strata-schemes`, `nsw-amenities` | same name | large spatial layers; minutes to hours | internet |

Timings are from this repository's recorded runs (`docs/reviews/shared-feature-1-improvements-55.md`,
`docs/reviews/feature-1-reference-live-e2e-2026-09-13.md`) and vary with the machine and publisher.

**Order matters.** Publish G-NAF before running PSI: sales match addresses only against the
*accepted* G-NAF generation, so PSI collected against the seeded baseline has almost no matches.
SEIFA and schools are independent.

## 3. Prepare source caches (large sources only)

The runner reads a read-only host cache, by default `./.propertyscope-source-cache/`:

- `gnaf.zip`: an unmodified official G-NAF PSV archive (≈1.6 GB). Without it the runner downloads
  the latest archive. Set `PROPERTYSCOPE_GNAF_CRS` (GDA94 by default) to match the archive.
- `psi/<year>.zip` and `psi/weekly/<yyyymmdd>.zip`: fill with
  `uv run scripts/dev.py data sync-psi --all` (host download; re-runs keep verified files). The
  publisher blocks container downloads, so do this before collecting `psi-sales`.

To reuse another checkout's cache instead of downloading again, set
`PROPERTYSCOPE_SOURCE_CACHE_DIR` in `.env` (relative paths resolve from the repository root), then
`stack up`. `uv run scripts/dev.py stack doctor` shows the cache in use and whether G-NAF is
present.

## 4. Collect

```text
uv run scripts/dev.py data collect schools-master              # waits, prints the candidate
uv run scripts/dev.py data collect gnaf-nsw --no-wait           # long jobs: queue and return
uv run scripts/dev.py stack logs --no-follow --tail 50 f1-runner      # acquisition progress
uv run scripts/dev.py stack logs --no-follow --tail 50 f1-db-loader   # import progress
```

Poll a queued run with `GET /ingestion-runs/{run_id}` until its `status` is `succeeded`, `failed`
or `cancelled`. The Update history page at <http://localhost:5200/#runs> shows the same timeline.
A successful run ends with a **candidate** release. Nothing becomes current yet.

## 5. Review and publish (human decision)

Publication makes a candidate the current data for everyone. It is a deliberate human
checkpoint.

- **Do not submit, publish or reject a release unless the user has explicitly approved that
  specific release in this conversation** (dataset, release ID and record count). "Get the data
  loaded" is not approval to publish; ask. Approval for a disposable isolated environment does
  not carry over to the developer's main stack.
- Before asking, show the evidence: record count, quality results and warnings
  (`GET /dataset-releases/{id}` and `GET /ingestion-runs/{run_id}/quality-results`).
- Prefer letting the user publish in the UI: **Published data** at <http://localhost:5200>, open
  the version, then **Submit for review** and **Publish**.
- Never publish a partial PSI candidate (selected archive years). The API refuses to let it
  replace complete history anyway.

With approval, the API sequence is (each step needs the release's current `version`):

```text
GET  /dataset-releases/{id}                     -> release.version (for example 3)
POST /dataset-releases/{id}/submit-review        {"version": 3, "comment": "why"}
                                                -> status awaiting_review, version 4
POST /dataset-releases/{id}/publish              {"version": 4, "comment": "Approved by <user>", "approved": true}
     header Idempotency-Key: <new uuid>          -> 202, activation queued
GET  /dataset-releases/{id}                      -> poll until status accepted
```

Small releases become `accepted` within seconds; G-NAF and PSI activation can take many minutes
because the loader materialises the whole generation. The previous accepted release stays live
until then. `POST /dataset-releases/{id}/reject` with `{"version", "comment"}` discards a
candidate.

## 6. Query accepted data

```text
GET /properties/search?q=10 Smith Street Glebe            # accepted address register
GET /properties/{property_ref}                            # identity, location, coverage summary
GET /properties/{property_ref}/sale-history               # matched PSI sales
GET /properties/{property_ref}/seifa                      # SEIFA 2021 for the locality
GET /properties/locality-summary?locality=SUTHERLAND&postcode=2232
GET /data-products/{dataset_id}/accepted                  # current release and manifest
GET /dataset-releases/{id}/records?limit=100              # bounded preview, not an export
```

Only accepted generations appear in search and property pages; candidates never do. Address
records are not titles, parcels or dwellings, and SEIFA describes an area, not a household. Keep
those limits in any answer. The full contract is
`student-1/contracts/data-platform-api.v1.openapi.yaml`; dataset semantics are in
`student-1/DATA_PRODUCT_CONSUMER_GUIDE.md`.

## 7. When a run fails

- Read the run: `GET /ingestion-runs/{run_id}`, its `tasks`, and `activity`. Then read
  `stack logs --no-follow f1-runner` or `f1-db-loader`.
- `POST /ingestion-runs/{run_id}/resume` retries a retryable failed import after its cause is
  fixed. `reprocess-cached` rebuilds from the verified artifact without downloading again. Both
  change durable state, so confirm with the user first.
- Never delete volumes, edit tables by hand, or restart a worker that is mid-import to "fix" a
  run. `docs/release-0/feature-1-large-data-operations.md` is the recovery runbook.

## 8. Use a disposable environment for experiments

For a clean database that cannot disturb the user's data, follow "Isolated environments" in
`AGENTS.md`: a separate worktree whose `.env` sets `COMPOSE_PROJECT_NAME` and
`PROPERTYSCOPE_SOURCE_CACHE_DIR`, then `stack up --offline`. Every `dev.py` command, including
`stack reset`, then acts only on that project. Remove it with `stack reset` from the same checkout
and `git worktree remove`.

## Report

State which datasets are real, and which are seeded, with their record counts and release IDs.
Say what you collected and which releases the user approved and published. Record timings and
any failures, and say whether observations came from the user's stack or a disposable one.
