# Feature 3: Suburb, Crime and Liveability Analytics (Release 2 plan)

Owner: James. Do everything in the [common feature checklist](README.md#common-feature-checklist).
This file covers only what is specific to Feature 3.

## Multi-agent workflow (suggestion)

**Suburb comparison review**: given a saved suburb comparison:

- **Planner** chooses the snapshots and the crime series to use.
- **Worker** drafts a comparison, using `suburb.snapshot.v1`, `crime.compare.v1` and
  `crime.methodology.v1`.
- **Reviewer** checks that counts and rates are not mixed, that missing values are not treated as
  zero, and that the draft makes no causal, safety or desirability claims.
- **Human** decides.

## Endpoint tests (suggestion)

| Endpoint function | Happy path | Failure case |
|---|---|---|
| `GET /api/suburb-analytics/v1/suburbs` | Seeded list returns at least 10 items, with paging | Invalid `limit` returns a structured error |
| `POST /api/suburb-analytics/v1/suburb-comparisons` | Create a comparison, then read it back | Unknown locality is rejected |

`student-3.yml` already smoke-tests `/suburbs`. Move it into `tests/endpoints/`.

## Cloud

- The SQLite store lives on the VM's managed disk volume. Check that the comparisons you saved
  are still there after a redeploy.
- The optional official-context corpus is not required in the cloud. The registered guidance
  corpus is enough for the RAG bonus.

## Steps

1. 9 Oct: endpoint tests and a green `student-3.yml` with JUnit artifact.
2. 13 Oct: workflow manifest, proxy routes and panel. A local UI workflow is captured.
3. 16 Oct: production config; cloud CRUD smoke case passes; persistence after redeploy checked.
4. 18 Oct: with cloud AI on, the feature checked on Azure. Contribution log and video segment by
   21 Oct.
