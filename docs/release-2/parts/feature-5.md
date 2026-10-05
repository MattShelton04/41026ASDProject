# Feature 5: Buyer Journey and Agent Workspace (Release 2 plan)

Owner: Derek. Do everything in the [common feature checklist](README.md#common-feature-checklist).
This file covers only what is specific to Feature 5.

## Multi-agent workflow (suggestion)

**Buyer case action plan**: given a buyer case:

- **Planner** chooses which case evidence to read.
- **Worker** proposes three to five next actions, using `buyer.cases.inspect.v1`,
  `buyer.evidence.collect.v1`, `buyer.notes.list.v1` and `buyer.tasks.list.v1`.
- **Reviewer** checks each action against the evidence, treats user-entered text as untrusted,
  and flags any limitations that are not cited.
- **Human** approves, partially accepts or rejects the plan.

Optionally, accepted actions can become case tasks. If so, the Feature 5 backend creates them,
not the Multi-Agent Server.

## Endpoint tests (suggestion)

| Endpoint function | Happy path | Failure case |
|---|---|---|
| `POST /api/buyer-workspaces/v1/buyer-cases` | Valid case is created (201) and can be read back | Budget minimum greater than maximum is rejected |
| `POST /api/buyer-workspaces/v1/buyer-cases/{id}/tasks` | Task is added to the case | Unknown case returns 404 |

`student-5/scripts/compose_smoke.py` already covers CRUD. Lift the two cases into
`tests/endpoints/` so the workflow produces JUnit output.

## Carry-over from Release 1

- Make `student-5.yml` consistent with the AI-disabled rule. Either stop starting host AI-mode in
  CI, or document why the offline direct mode is still "disabled". Feature CI must pass without
  the AI tier.

## Steps

1. 9 Oct: endpoint tests and a green `student-5.yml` with JUnit artifact; the AI-mode CI start
   resolved.
2. 13 Oct: workflow manifest, proxy routes and panel. A local UI workflow is captured.
3. 16 Oct: production config; cloud CRUD smoke case passes.
4. 18 Oct: with cloud AI on, the feature checked on Azure. Contribution log and video segment by
   21 Oct.
