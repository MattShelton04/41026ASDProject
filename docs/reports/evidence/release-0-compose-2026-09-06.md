# Release 0 all-feature Compose execution record

Captured on 6 September 2026 at 11:56:55 Australia/Sydney (01:56:55 UTC).
Software commit: `7d5350d19023fb1e978e85127a72e3500a1556f3`. The detached checkout had no tracked or untracked source changes.
This is a later execution of the exact report commit, not an execution of the later report branch.

Environment: Windows, Docker Engine 29.2.1, Compose 5.0.2.
Project: `ps-release0-evidence`; all five manifest-enabled features, 21 services and seven fresh named volumes.
The project name was selected through `COMPOSE_PROJECT_NAME`; the three versioned Compose files and
all software source were unchanged. Existing `ps-dev` containers and volumes were not started or modified.
Application images were rebuilt from the pinned checkout and its locked dependencies.

## Commands and outcome

Run from the detached checkout, with `COMPOSE_PROJECT_NAME=ps-release0-evidence`:

```text
uv sync --locked --all-packages --all-groups
uv run scripts/dev.py stack up --offline --build
uv run scripts/dev.py stack status
uv run scripts/dev.py data collect fixture-property
```

All commands exited 0. `stack up` uses Compose's `--wait --wait-timeout 180` and reloads the shared
Nginx edge once dependencies are ready. The final startup output included the following exact lines:

```text
Container ps-release0-evidence-f3-backend-1 Healthy
Container ps-release0-evidence-f1-db-loader-1 Healthy
Container ps-release0-evidence-f3-database-1 Healthy
Container ps-release0-evidence-f5-db-api-1 Healthy
Container ps-release0-evidence-f4-backend-1 Healthy
Container ps-release0-evidence-f2-backend-1 Healthy
Container ps-release0-evidence-f1-postgres-1 Healthy
Container ps-release0-evidence-f1-db-api-1 Healthy
Container ps-release0-evidence-f5-frontend-1 Healthy
Container ps-release0-evidence-f3-frontend-1 Healthy
Container ps-release0-evidence-f1-backend-1 Healthy
Container ps-release0-evidence-f4-postgres-1 Healthy
Container ps-release0-evidence-f5-backend-1 Healthy
Container ps-release0-evidence-f2-db-api-1 Healthy
Container ps-release0-evidence-f4-frontend-1 Healthy
Container ps-release0-evidence-f1-runner-1 Healthy
Container ps-release0-evidence-f4-db-api-1 Healthy
Container ps-release0-evidence-f2-frontend-1 Healthy
Container ps-release0-evidence-shared-frontend-1 Healthy
Container ps-release0-evidence-shared-ai-mode-1 Healthy
Container ps-release0-evidence-f1-frontend-1 Healthy
```

Compose's startup progress uses `Healthy` for readiness completion, including running workers.
The explicit status snapshot below distinguishes actual configured healthchecks: **19 healthy services
and two running workers without Docker healthchecks**, all running simultaneously. The successful
fixture task below also exercises the runner and loader. Only the service, state and health columns
are retained from `docker compose ... ps --format json`; empty health values are preserved.

```text
SERVICE              STATE    HEALTH
f1-backend           running  healthy
f1-db-api            running  healthy
f1-db-loader         running  
f1-frontend          running  healthy
f1-postgres          running  healthy
f1-runner            running  
f2-backend           running  healthy
f2-db-api            running  healthy
f2-frontend          running  healthy
f3-backend           running  healthy
f3-database          running  healthy
f3-frontend          running  healthy
f4-backend           running  healthy
f4-db-api            running  healthy
f4-frontend          running  healthy
f4-postgres          running  healthy
f5-backend           running  healthy
f5-db-api            running  healthy
f5-frontend          running  healthy
shared-ai-mode       running  healthy
shared-frontend      running  healthy
```

## Deterministic acquisition output

Exact dev-helper output:

```text
Collection plan validated: fixture-property-full (complete source); network_required=False; source_cache_required=False
Collection run queued: dba21177-a26c-41b2-af5f-2b5f3b143041
Collection run dba21177-a26c-41b2-af5f-2b5f3b143041: queued
Collection run dba21177-a26c-41b2-af5f-2b5f3b143041: staging
Collection run dba21177-a26c-41b2-af5f-2b5f3b143041: succeeded
Candidate release ready: a5ac859d-322a-4d7e-9850-905723a82fc2 (candidate, 10 records).
Publication remains blocked until explicit human review and approval.
```

This proves an HTTP-controlled acquisition, runner task, database loader and persisted 10-record
candidate. Publication was not approved or executed. It does not claim all-feature CRUD or live-model
execution; the existing CI and AI evaluation records provide those separately bounded results.

## Shared edge HTTP checks

The shared home, five feature entrypoints and AI operations interface returned HTTP 200:

```text
GET / -> HTTP 200
GET /features/data-platform/ -> HTTP 200
GET /features/market-intelligence/ -> HTTP 200
GET /features/suburb-analytics/ -> HTTP 200
GET /features/due-diligence/ -> HTTP 200
GET /features/buyer-workspaces/ -> HTTP 200
GET /operations/ai-mode/ -> HTTP 200
```

Selected exact access-log lines from the same run (container-local addresses only):

```text
shared-frontend-1  | 2026-09-06T01:56:55.420028997Z 172.22.0.1 - - [06/Sep/2026:01:56:55 +0000] "GET /features/data-platform/ HTTP/1.1" 200 8474 "-" "python-httpx/0.28.1" "-"
shared-frontend-1  | 2026-09-06T01:56:55.425702436Z 172.22.0.1 - - [06/Sep/2026:01:56:55 +0000] "GET /features/market-intelligence/ HTTP/1.1" 200 7590 "-" "python-httpx/0.28.1" "-"
shared-frontend-1  | 2026-09-06T01:56:55.430348351Z 172.22.0.1 - - [06/Sep/2026:01:56:55 +0000] "GET /features/suburb-analytics/ HTTP/1.1" 200 12377 "-" "python-httpx/0.28.1" "-"
shared-frontend-1  | 2026-09-06T01:56:55.436200983Z 172.22.0.1 - - [06/Sep/2026:01:56:55 +0000] "GET /features/due-diligence/ HTTP/1.1" 200 6773 "-" "python-httpx/0.28.1" "-"
shared-frontend-1  | 2026-09-06T01:56:55.440929262Z 172.22.0.1 - - [06/Sep/2026:01:56:55 +0000] "GET /features/buyer-workspaces/ HTTP/1.1" 200 11430 "-" "python-httpx/0.28.1" "-"
shared-frontend-1  | 2026-09-06T01:56:55.451957368Z 172.22.0.1 - - [06/Sep/2026:01:56:55 +0000] "GET /operations/ai-mode/ HTTP/1.1" 200 9987 "-" "python-httpx/0.28.1" "-"
```

A bounded log snapshot used the same three files and release profile as `stack logs`, with
`logs --no-color --timestamps --tail 30` instead of following indefinitely. Only the relevant
access-log lines are versioned here; repetitive health polling and build-cache output are omitted.
No credentials, environment dumps, databases or private AI reasoning are included.

The stack used the helper's offline credential placeholder. AI-mode readiness was allowed to degrade
at the provider boundary; no live model request or official-source acquisition was part of this run.
Fresh fixture records and seeded feature databases were isolated from the ordinary development data.
