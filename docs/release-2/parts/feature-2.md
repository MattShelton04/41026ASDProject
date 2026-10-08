# Feature 2: Property Sales Explorer and Market Cases (Release 2 plan)

Owner: Burhan. Do everything in the [common feature checklist](README.md#common-feature-checklist).
This file covers only what is specific to Feature 2.

## Multi-agent workflow (suggestion)

**Market case brief**: given a saved market case:

- **Planner** chooses the evidence to gather.
- **Worker** summarises the sale observations, using the existing two market-case tools.
- **Reviewer** checks the summary against that evidence. It flags any valuation, forecast or
  buy recommendation, and any claim that the evidence does not support.
- **Human** accepts, corrects or rejects the brief.

Keep the case-scoping rule from Release 1: a workflow can only read the case it was started for.

## Endpoint tests (suggestion)

| Endpoint function | Happy path | Failure case |
|---|---|---|
| `POST /api/market-intelligence/v1/market-cases` | Valid Feature 1 property creates a case (201) | Unknown property reference is rejected; no case is created |
| `PUT /api/market-intelligence/v1/market-cases/{id}` | Update with the current version succeeds | A stale version returns a conflict |

## Carry-over from Release 1

- When the selected market case changes, clear the assistant history and rebind the scope,
  including any active run. Switching from case A to case B must not reuse A's context.

## Steps

1. 9 Oct: endpoint tests and a green `student-2.yml` with JUnit artifact.
2. 13 Oct: workflow manifest, proxy routes and panel. A local UI workflow is captured.
3. 16 Oct: production config; cloud CRUD smoke case passes.
4. 18 Oct: with cloud AI on, the feature checked on Azure. Contribution log and video segment by
   21 Oct.
