# Feature 1: Data Platform and Property Discovery (Release 2 plan)

Owner: Matthew. Do everything in the [common feature checklist](README.md#common-feature-checklist).
This file covers only what is specific to Feature 1.

## Multi-agent workflow (suggestion)

**Release readiness review**: given a candidate release ID:

- **Planner** lists the publication checks.
- **Worker** collects record counts, quality results, provenance and the accepted predecessor,
  using the existing read-only data-platform tools.
- **Reviewer** compares those results with the publication criteria and flags gaps.
- **Human** approves or rejects the *recommendation*.

Publishing stays a separate, explicit operator action. The workflow never publishes. Feature 1 is
also the first UI integration of the shared panel, so it serves as the reference for the other
features.

## Endpoint tests (suggestion)

| Endpoint function | Happy path | Failure case |
|---|---|---|
| `GET /api/data-platform/v1/properties/search` | Seeded address returns at least one typed result | Missing or too-short `q` returns a structured error |
| `GET/POST /api/data-platform/v1/sources` (source-definition CRUD) | Create, then list contains it | Invalid payload is rejected and nothing is persisted |

`student-1.yml` already smoke-tests both endpoints. Move them into `tests/endpoints/` so the
workflow produces JUnit output.

## Cloud

- Decide what data the cloud uses (see the open decisions in the implementation plan). The
  default is the seeded demonstration baseline, labelled as such. Any real release is collected
  and published in the cloud only after the usual review.
- Feature 1 also provides the shared edge and home page, so its cloud smoke case also covers
  `/` and the feature routing.
- `f1-runner` and `f1-db-loader` must start in the Azure override without host source-cache
  mounts.

## Steps

1. 8 Oct: endpoint tests and a green `student-1.yml`.
2. 11 Oct: workflow manifest and backend proxy routes against the fake server.
3. 13 Oct: panel mounted. A full UI workflow runs locally and its evidence is captured.
4. 16 Oct: cloud config confirmed; cloud CRUD smoke case passes.
5. 18 Oct: with cloud AI on, the grounded chat and the workflow both checked on Azure.
